from __future__ import annotations

"""Runtime compatibility layer adding K and D/ST throughout DraftEdge.

DraftEdge's original engine was written for QB/RB/WR/TE.  This module extends
its league configuration, canonical schema, scoring helpers, roster accounting,
and synthetic demo pool without forcing a large rewrite of the stable legacy
engine.  App entry points call :func:`apply_special_teams_support` before the
ranking/data modules are imported.
"""

from dataclasses import dataclass
import re
from typing import Any

import numpy as np
import pandas as pd


FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
SPECIAL_POSITIONS = ("K", "DST")

SPECIAL_STAT_COLUMNS = [
    "kicker_fg_attempts", "kicker_fg_made", "kicker_fg_missed",
    "kicker_xp_attempts", "kicker_xp_made", "kicker_xp_missed",
    "dst_sacks", "dst_interceptions", "dst_fumble_recoveries", "dst_td",
    "dst_safeties", "dst_blocked_kicks", "dst_return_td", "dst_two_point_returns",
    "dst_points_allowed", "dst_yards_allowed",
]

POSITION_ALIASES = {
    "HB": "RB",
    "FB": "RB",
    "PK": "K",
    "KICKER": "K",
    "DEF": "DST",
    "D/ST": "DST",
    "D-ST": "DST",
    "D ST": "DST",
    "TEAM DEF": "DST",
    "TEAM DEFENSE": "DST",
    "TD": "DST",
    "TMD": "DST",
}

NFL_TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]


def normalize_position(value: Any) -> str:
    raw = str(value or "").upper().strip()
    raw = raw.replace("D/ST", "DST")
    return POSITION_ALIASES.get(raw, raw)


def _pa_points_per_game(avg_points_allowed: pd.Series, config: Any) -> pd.Series:
    """Approximate D/ST points-allowed scoring from season-average PA/game."""
    avg = pd.to_numeric(avg_points_allowed, errors="coerce")
    values = np.select(
        [
            avg.le(0),
            avg.between(0.0001, 6.9999),
            avg.between(7, 13.9999),
            avg.between(14, 20.9999),
            avg.between(21, 27.9999),
            avg.between(28, 34.9999),
            avg.ge(35),
        ],
        [
            float(config.dst_pa_0),
            float(config.dst_pa_1_6),
            float(config.dst_pa_7_13),
            float(config.dst_pa_14_20),
            float(config.dst_pa_21_27),
            float(config.dst_pa_28_34),
            float(config.dst_pa_35_plus),
        ],
        default=0.0,
    )
    return pd.Series(values, index=avg.index, dtype=float)


def apply_special_teams_support(engine_module) -> None:
    """Patch the loaded ``fantasy_engine`` module in-place once."""
    if getattr(engine_module, "_draftedge_special_teams_enabled", False):
        return

    BaseLeagueConfig = engine_module.LeagueConfig
    base_columns = list(engine_module.CANONICAL_COLUMNS)
    base_aliases = dict(engine_module.ALIASES)
    base_assign_role = engine_module.assign_role

    @dataclass
    class LeagueConfig(BaseLeagueConfig):
        k: int = 1
        dst: int = 1

        kicker_xp_made: float = 1.0
        kicker_xp_missed: float = 0.0
        kicker_fg_made: float = 3.0
        kicker_fg_missed: float = 0.0

        dst_sack: float = 1.0
        dst_interception: float = 2.0
        dst_fumble_recovery: float = 2.0
        dst_td: float = 6.0
        dst_safety: float = 2.0
        dst_blocked_kick: float = 2.0
        dst_return_td: float = 6.0
        dst_two_point_return: float = 2.0

        dst_points_allowed_enabled: bool = True
        dst_pa_0: float = 10.0
        dst_pa_1_6: float = 7.0
        dst_pa_7_13: float = 4.0
        dst_pa_14_20: float = 1.0
        dst_pa_21_27: float = 0.0
        dst_pa_28_34: float = -1.0
        dst_pa_35_plus: float = -4.0

    LeagueConfig.__name__ = "LeagueConfig"
    LeagueConfig.__qualname__ = "LeagueConfig"
    LeagueConfig.__module__ = engine_module.__name__

    columns = base_columns + [c for c in SPECIAL_STAT_COLUMNS if c not in base_columns]
    aliases = dict(base_aliases)
    aliases.update({
        "kicker_fg_attempts": ["kicker_fg_attempts", "fg_attempts", "fga", "kck_fga"],
        "kicker_fg_made": ["kicker_fg_made", "fg_made", "fgm", "kck_fgc"],
        "kicker_fg_missed": ["kicker_fg_missed", "fg_missed", "fgmiss", "kck_fgm"],
        "kicker_xp_attempts": ["kicker_xp_attempts", "xp_attempts", "xpa", "kck_xpa"],
        "kicker_xp_made": ["kicker_xp_made", "xp_made", "xpm", "kck_xpc"],
        "kicker_xp_missed": ["kicker_xp_missed", "xp_missed", "xpmiss", "kck_xpm"],
        "dst_sacks": ["dst_sacks", "def_sacks", "sacks", "tmd_sck"],
        "dst_interceptions": ["dst_interceptions", "def_interceptions", "tmd_int"],
        "dst_fumble_recoveries": ["dst_fumble_recoveries", "fumble_recoveries", "tmd_fmr"],
        "dst_td": ["dst_td", "def_td", "defensive_td", "tmd_td"],
        "dst_safeties": ["dst_safeties", "safeties", "tmd_saf"],
        "dst_blocked_kicks": ["dst_blocked_kicks", "blocked_kicks", "tmd_blk"],
        "dst_return_td": ["dst_return_td", "return_td", "special_teams_td"],
        "dst_two_point_returns": ["dst_two_point_returns", "def_2pt", "tmd_2pr"],
        "dst_points_allowed": ["dst_points_allowed", "points_allowed", "pa", "tmd_pa"],
        "dst_yards_allowed": ["dst_yards_allowed", "yards_allowed", "ya", "tmd_ya"],
    })

    def _clean_col(col: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(col).lower())

    def normalize_player_data(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or len(df) == 0:
            return pd.DataFrame(columns=columns)

        out = pd.DataFrame(df).copy()
        normalized_lookup = {_clean_col(c): c for c in out.columns}
        rename: dict[str, str] = {}
        used_source: set[str] = set()
        for canonical, alias_list in aliases.items():
            for alias in alias_list:
                key = _clean_col(alias)
                if key in normalized_lookup and normalized_lookup[key] not in used_source:
                    source = normalized_lookup[key]
                    rename[source] = canonical
                    used_source.add(source)
                    break
        out = out.rename(columns=rename)

        if "position" not in out.columns:
            raise ValueError("Input must include a position column (Position/Pos/FantPos).")
        out["position"] = out["position"].map(normalize_position)

        if "player" not in out.columns:
            if "team" in out.columns and out["position"].eq("DST").all():
                out["player"] = out["team"].fillna("").astype(str).str.upper().str.strip() + " D/ST"
            else:
                raise ValueError("Input must include a Player/name column.")

        for col in columns:
            if col not in out.columns:
                out[col] = np.nan

        out["player"] = (
            out["player"].astype(str)
            .str.replace(r"[+*]+$", "", regex=True)
            .str.replace("&apos;", "'", regex=False)
            .str.strip()
        )
        out["team"] = out["team"].fillna("FA").astype(str).str.upper().str.strip()
        out["position"] = out["position"].map(normalize_position)
        out = out[out["position"].isin(FANTASY_POSITIONS)].copy()

        string_cols = {
            "player_id", "sleeper_id", "gsis_id", "player", "team", "position", "injury_status",
            "practice_status", "depth_chart_position", "image_url", "data_source",
        }
        for col in [c for c in columns if c not in string_cols]:
            out[col] = pd.to_numeric(out[col], errors="coerce")

        for id_col in ["player_id", "sleeper_id", "gsis_id"]:
            out[id_col] = out[id_col].fillna("").astype(str).replace({"nan": "", "None": ""})

        missing_id = out["player_id"].eq("")
        if missing_id.any():
            synthetic = []
            for _, row in out.loc[missing_id].iterrows():
                pos = str(row.get("position") or "")
                team = str(row.get("team") or "")
                name = str(row.get("player") or "")
                if pos == "DST" and team and team != "FA":
                    synthetic.append(f"DST_{team}")
                else:
                    synthetic.append(f"N{engine_module.normalize_name(name)[:18]}_{len(synthetic)+1:04d}")
            out.loc[missing_id, "player_id"] = synthetic

        out["games"] = out["games"].fillna(0).clip(lower=0)
        out["age"] = out["age"].fillna(26)
        out["years_exp"] = out["years_exp"].fillna(3)
        out["injury_status"] = out["injury_status"].fillna("").astype(str)
        out["practice_status"] = out["practice_status"].fillna("").astype(str)
        out["depth_chart_position"] = out["depth_chart_position"].fillna("").astype(str)
        out["image_url"] = out["image_url"].fillna("").astype(str)
        out["data_source"] = out["data_source"].fillna("").astype(str)

        return out[columns].drop_duplicates(subset=["player_id"], keep="first").reset_index(drop=True)

    def score_fantasy_points(df: pd.DataFrame, config: LeagueConfig) -> pd.Series:
        def n(col: str) -> pd.Series:
            if col not in df.columns:
                return pd.Series(0.0, index=df.index)
            return pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        pos = df.get("position", pd.Series("", index=df.index)).map(normalize_position)
        reception_value = n("receptions") * float(config.ppr)
        if config.te_premium:
            reception_value += n("receptions") * pos.eq("TE").astype(float) * float(config.te_premium)

        offensive = (
            n("passing_yards") / float(config.pass_yd_per_point)
            + n("passing_td") * float(config.pass_td)
            + n("interceptions") * float(config.interception)
            + n("rushing_yards") / float(config.rush_yd_per_point)
            + n("rushing_td") * float(config.rush_td)
            + reception_value
            + n("receiving_yards") / float(config.rec_yd_per_point)
            + n("receiving_td") * float(config.rec_td)
            + n("fumbles") * float(config.fumble)
        )

        kicker = (
            n("kicker_xp_made") * float(config.kicker_xp_made)
            + n("kicker_xp_missed") * float(config.kicker_xp_missed)
            + n("kicker_fg_made") * float(config.kicker_fg_made)
            + n("kicker_fg_missed") * float(config.kicker_fg_missed)
        )

        dst = (
            n("dst_sacks") * float(config.dst_sack)
            + n("dst_interceptions") * float(config.dst_interception)
            + n("dst_fumble_recoveries") * float(config.dst_fumble_recovery)
            + n("dst_td") * float(config.dst_td)
            + n("dst_safeties") * float(config.dst_safety)
            + n("dst_blocked_kicks") * float(config.dst_blocked_kick)
            + n("dst_return_td") * float(config.dst_return_td)
            + n("dst_two_point_returns") * float(config.dst_two_point_return)
        )
        if bool(config.dst_points_allowed_enabled):
            games = n("games").replace(0, np.nan)
            avg_pa = n("dst_points_allowed") / games
            dst += _pa_points_per_game(avg_pa, config).fillna(0.0) * games.fillna(0.0)

        result = offensive.copy()
        result.loc[pos.eq("K")] = kicker.loc[pos.eq("K")]
        result.loc[pos.eq("DST")] = dst.loc[pos.eq("DST")]
        return result

    def assign_role(row: pd.Series) -> str:
        pos = normalize_position(row.get("position", ""))
        if pos == "K":
            return "Kicker"
        if pos == "DST":
            return "Team Defense / Special Teams"
        return base_assign_role(row)

    def roster_counts(draft_log: list[dict], slot: int) -> dict[str, int]:
        counts = {p: 0 for p in FANTASY_POSITIONS}
        for pick in draft_log or []:
            try:
                if int(pick.get("slot", -1)) != int(slot):
                    continue
            except Exception:
                continue
            pos = normalize_position(pick.get("position", ""))
            if pos in counts:
                counts[pos] += 1
        return counts

    def roster_need_factor(position: str, counts: dict[str, int], config: LeagueConfig) -> float:
        pos = normalize_position(position)
        targets = {
            "QB": int(config.qb), "RB": int(config.rb), "WR": int(config.wr), "TE": int(config.te),
            "K": int(config.k), "DST": int(config.dst),
        }
        missing = max(targets.get(pos, 0) - int(counts.get(pos, 0)), 0)
        if pos in SPECIAL_POSITIONS:
            if targets.get(pos, 0) <= 0:
                return 0.45
            if missing > 0:
                return 1.02
            return 0.55

        if missing > 0:
            return 1.13 + min(0.12, 0.04 * missing)
        if pos == "QB" and int(config.superflex) > 0:
            if counts.get("QB", 0) < int(config.qb) + int(config.superflex):
                return 1.12

        flex_eligible = pos in {"RB", "WR", "TE"}
        base_skill_starters = int(config.rb) + int(config.wr) + int(config.te)
        skill_owned = counts.get("RB", 0) + counts.get("WR", 0) + counts.get("TE", 0)
        if flex_eligible and skill_owned < base_skill_starters + int(config.flex):
            return 1.06

        if int(config.superflex) > 0:
            total_sf = sum(counts.get(p, 0) for p in ["QB", "RB", "WR", "TE"])
            primary = int(config.qb) + int(config.rb) + int(config.wr) + int(config.te) + int(config.flex)
            if total_sf < primary + int(config.superflex):
                return 1.05 if pos == "QB" else 1.01
        return 0.92 if pos in {"QB", "TE"} else 0.98

    engine_module.LeagueConfig = LeagueConfig
    engine_module.CANONICAL_COLUMNS = columns
    engine_module.ALIASES = aliases
    engine_module.normalize_player_data = normalize_player_data
    engine_module.score_fantasy_points = score_fantasy_points
    engine_module.assign_role = assign_role
    engine_module.roster_counts = roster_counts
    engine_module.roster_need_factor = roster_need_factor
    engine_module.normalize_position = normalize_position
    engine_module.FANTASY_POSITIONS = FANTASY_POSITIONS
    engine_module.SPECIAL_POSITIONS = SPECIAL_POSITIONS
    engine_module._draftedge_special_teams_enabled = True


def install_demo_support(demo_module, engine_module) -> None:
    if getattr(demo_module, "_draftedge_special_demo_enabled", False):
        return
    original = demo_module.make_demo_players

    def make_demo_players(seed: int = 2026) -> pd.DataFrame:
        base = pd.DataFrame(original(seed)).copy()
        rng = np.random.default_rng(seed + 97)
        rows = []
        for i, team in enumerate(NFL_TEAMS):
            rows.append({
                "player_id": f"DK{i+1:03d}", "player": f"{team} Demo Kicker", "team": team, "position": "K",
                "games": 17, "age": int(rng.integers(23, 36)), "projection": round(132 - i * 0.75 + rng.normal(0, 4), 1),
                "adp": round(145 + i * 1.5 + rng.normal(0, 5), 1), "ecr": np.nan,
                "data_source": "Synthetic demo data",
            })
            rows.append({
                "player_id": f"DDST_{team}", "player": f"{team} D/ST", "team": team, "position": "DST",
                "games": 17, "age": 0, "projection": round(118 - i * 0.65 + rng.normal(0, 5), 1),
                "adp": round(150 + i * 1.4 + rng.normal(0, 6), 1), "ecr": np.nan,
                "data_source": "Synthetic demo data",
            })
        return pd.concat([base, pd.DataFrame(rows)], ignore_index=True, sort=False)

    demo_module.make_demo_players = make_demo_players
    demo_module._draftedge_special_demo_enabled = True
