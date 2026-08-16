from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from math import exp
from typing import Dict, List, Optional
import re

import numpy as np
import pandas as pd


CANONICAL_COLUMNS = [
    "player_id", "sleeper_id", "gsis_id", "player", "team", "position", "age", "years_exp", "games",
    "passing_yards", "passing_td", "interceptions", "rushing_attempts", "rushing_yards", "rushing_td",
    "targets", "receptions", "receiving_yards", "receiving_td", "fumbles", "fantasy_points",
    "projection", "adp", "ecr", "injury_status", "practice_status", "depth_chart_order",
    "depth_chart_position", "data_source",
]


@dataclass
class LeagueConfig:
    teams: int = 12
    rounds: int = 16
    user_slot: int = 6
    qb: int = 1
    rb: int = 2
    wr: int = 2
    te: int = 1
    flex: int = 1
    superflex: int = 0
    bench: int = 7
    ppr: float = 1.0
    te_premium: float = 0.0
    pass_yd_per_point: float = 25.0
    pass_td: float = 4.0
    interception: float = -2.0
    rush_yd_per_point: float = 10.0
    rush_td: float = 6.0
    rec_yd_per_point: float = 10.0
    rec_td: float = 6.0
    fumble: float = -2.0

    def to_dict(self) -> dict:
        return asdict(self)


ALIASES = {
    "player_id": ["player_id", "id"],
    "sleeper_id": ["sleeper_id", "sleeperid"],
    "gsis_id": ["gsis_id", "gsisid"],
    "player": ["player", "name", "player_name", "player_display_name", "full_name", "display_name"],
    "team": ["team", "tm", "recent_team", "team_abbr", "club_code"],
    "position": ["position", "pos", "fantpos", "fantasy_position"],
    "age": ["age"],
    "years_exp": ["years_exp", "experience", "exp"],
    "games": ["games", "g", "games_played"],
    "passing_yards": ["passing_yards", "pass_yds", "passyds", "passingyds"],
    "passing_td": ["passing_td", "passing_tds", "pass_td", "passtd", "passingtd"],
    "interceptions": ["interceptions", "int", "ints", "passing_interceptions"],
    "rushing_attempts": ["rushing_attempts", "rush_att", "rushatt", "carries", "rushing_attempts"],
    "rushing_yards": ["rushing_yards", "rush_yds", "rushyds", "rushingyds"],
    "rushing_td": ["rushing_td", "rushing_tds", "rush_td", "rushtd", "rushingtd"],
    "targets": ["targets", "tgt"],
    "receptions": ["receptions", "rec"],
    "receiving_yards": ["receiving_yards", "rec_yds", "recyds", "receivingyds"],
    "receiving_td": ["receiving_td", "receiving_tds", "rec_td", "rectd", "receivingtd"],
    "fumbles": ["fumbles", "fmb", "fum", "rushing_fumbles", "receiving_fumbles"],
    "fantasy_points": ["fantasy_points", "fantpt", "ppr", "points", "fantasypoints", "fantasy_points_ppr"],
    "projection": ["projection", "projected_points", "proj", "projectedpoints", "fpts", "projected_fantasy_points"],
    "adp": ["adp", "average_draft_position", "averagedraftposition", "avg_pick"],
    "ecr": ["ecr", "rank", "overall_rank", "fantasypros_rank"],
    "injury_status": ["injury_status", "injury", "status"],
    "practice_status": ["practice_status", "practice_participation", "report_status"],
    "depth_chart_order": ["depth_chart_order", "depth_order", "depth"],
    "depth_chart_position": ["depth_chart_position", "depth_position"],
    "data_source": ["data_source", "source"],
}


def _clean_col(col: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(col).lower())


def _safe_num(value, default: float = 0.0) -> float:
    try:
        val = float(value)
        return default if np.isnan(val) else val
    except (TypeError, ValueError):
        return default


def normalize_name(name: str) -> str:
    s = str(name or "").lower().strip()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?$", "", s).strip()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def normalize_player_data(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize PFR/nflverse/projection-style tables into the app schema."""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    out = df.copy()
    normalized_lookup = {_clean_col(c): c for c in out.columns}
    rename: dict[str, str] = {}
    used_source: set[str] = set()
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            key = _clean_col(alias)
            if key in normalized_lookup and normalized_lookup[key] not in used_source:
                source = normalized_lookup[key]
                rename[source] = canonical
                used_source.add(source)
                break
    out = out.rename(columns=rename)

    if "player" not in out.columns:
        raise ValueError("Input must include a Player/name column.")
    if "position" not in out.columns:
        raise ValueError("Input must include a position column (Position/Pos/FantPos).")

    for col in CANONICAL_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan

    out["player"] = (
        out["player"].astype(str)
        .str.replace(r"[+*]+$", "", regex=True)
        .str.strip()
    )
    out["team"] = out["team"].fillna("FA").astype(str).str.upper().str.strip()
    out["position"] = (
        out["position"].astype(str).str.upper().str.strip()
        .replace({"HB": "RB", "FB": "RB", "PK": "K"})
    )
    out = out[out["position"].isin(["QB", "RB", "WR", "TE"])].copy()

    numeric_cols = [
        c for c in CANONICAL_COLUMNS
        if c not in {
            "player_id", "sleeper_id", "gsis_id", "player", "team", "position", "injury_status",
            "practice_status", "depth_chart_position", "data_source"
        }
    ]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    for id_col in ["player_id", "sleeper_id", "gsis_id"]:
        out[id_col] = out[id_col].fillna("").astype(str).replace({"nan": "", "None": ""})

    missing_id = out["player_id"].eq("")
    if missing_id.any():
        synthetic_ids = [
            f"N{normalize_name(p)[:18]}_{i:04d}"
            for i, p in enumerate(out.loc[missing_id, "player"], start=1)
        ]
        out.loc[missing_id, "player_id"] = synthetic_ids

    out["games"] = out["games"].fillna(0).clip(lower=0)
    out["age"] = out["age"].fillna(26)
    out["years_exp"] = out["years_exp"].fillna(3)
    out["injury_status"] = out["injury_status"].fillna("").astype(str)
    out["practice_status"] = out["practice_status"].fillna("").astype(str)
    out["depth_chart_position"] = out["depth_chart_position"].fillna("").astype(str)
    out["data_source"] = out["data_source"].fillna("").astype(str)

    return out[CANONICAL_COLUMNS].drop_duplicates(subset=["player_id"], keep="first").reset_index(drop=True)


def score_fantasy_points(df: pd.DataFrame, config: LeagueConfig) -> pd.Series:
    def n(col: str) -> pd.Series:
        if col not in df.columns:
            return pd.Series(0.0, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    reception_value = n("receptions") * config.ppr
    if "position" in df.columns and config.te_premium:
        reception_value += n("receptions") * df["position"].eq("TE").astype(float) * config.te_premium

    return (
        n("passing_yards") / config.pass_yd_per_point
        + n("passing_td") * config.pass_td
        + n("interceptions") * config.interception
        + n("rushing_yards") / config.rush_yd_per_point
        + n("rushing_td") * config.rush_td
        + reception_value
        + n("receiving_yards") / config.rec_yd_per_point
        + n("receiving_td") * config.rec_td
        + n("fumbles") * config.fumble
    )


def assign_role(row: pd.Series) -> str:
    pos = str(row.get("position", ""))
    g = max(_safe_num(row.get("games"), 17.0), 1.0)
    rush_att_pg = _safe_num(row.get("rushing_attempts")) / g
    rush_yd_pg = _safe_num(row.get("rushing_yards")) / g
    tgt_pg = _safe_num(row.get("targets")) / g
    rec_pg = _safe_num(row.get("receptions")) / g
    rec_yd = _safe_num(row.get("receiving_yards"))
    rec = max(_safe_num(row.get("receptions")), 1.0)
    ypr = rec_yd / rec
    pass_yd_pg = _safe_num(row.get("passing_yards")) / g
    pass_td_pg = _safe_num(row.get("passing_td")) / g
    rush_td_pg = _safe_num(row.get("rushing_td")) / g
    rec_td_pg = _safe_num(row.get("receiving_td")) / g

    if pos == "QB":
        if rush_yd_pg >= 35 or rush_td_pg >= 0.35:
            return "Dual-Threat QB"
        if pass_yd_pg >= 260 and pass_td_pg >= 1.6:
            return "High-Volume Passer"
        if pass_yd_pg >= 225:
            return "Pocket QB"
        return "Streaming / Developmental QB"
    if pos == "RB":
        if rush_att_pg >= 15 and rec_pg >= 2.5:
            return "Workhorse RB"
        if rec_pg >= 3.5 or tgt_pg >= 4.5:
            return "Receiving RB"
        if rush_td_pg >= 0.55 and rush_att_pg >= 10:
            return "Goal-Line RB"
        if rush_att_pg >= 10:
            return "Early-Down / Committee RB"
        return "Handcuff / Upside RB"
    if pos == "WR":
        if tgt_pg >= 8:
            return "Alpha / Target-Hog WR"
        if ypr >= 15.5 and tgt_pg >= 4:
            return "Deep-Threat WR"
        if rec_td_pg >= 0.5:
            return "Red-Zone WR"
        if rec_pg >= 4.5:
            return "Possession WR"
        return "Boom/Bust / Upside WR"
    if pos == "TE":
        if tgt_pg >= 7:
            return "Elite Target TE"
        if tgt_pg >= 5:
            return "High-Volume TE"
        if rec_td_pg >= 0.4:
            return "Red-Zone TE"
        return "Streaming / Upside TE"
    return "Other"


def _minmax(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").fillna(0.0)
    lo, hi = float(s.min()), float(s.max())
    if hi <= lo:
        return pd.Series(np.full(len(s), 50.0), index=s.index)
    return (s - lo) / (hi - lo) * 100.0


def _health_score(status: str) -> float:
    s = str(status or "").lower()
    if any(x in s for x in ["ir", "injured reserve", "pup", "out"]):
        return 25.0
    if "doubt" in s:
        return 45.0
    if "question" in s:
        return 70.0
    if "prob" in s:
        return 85.0
    return 100.0


def _injury_projection_multiplier(status: str) -> float:
    s = str(status or "").lower()
    if any(x in s for x in ["ir", "injured reserve", "pup"]):
        return 0.82
    if "out" in s:
        return 0.88
    if "doubt" in s:
        return 0.93
    if "question" in s:
        return 0.98
    return 1.0


def prepare_rankings(players: pd.DataFrame, config: LeagueConfig) -> pd.DataFrame:
    df = normalize_player_data(players)
    if df.empty:
        return df

    calculated = score_fantasy_points(df, config)
    base_points = df["fantasy_points"].copy()
    base_points = base_points.where(base_points.notna(), calculated)

    # If the table is historical, annualize the available sample. If a true current
    # projection is supplied (including a blended one), that value wins.
    games_for_rate = df["games"].replace(0, np.nan).fillna(17).clip(lower=1)
    ppg = base_points.fillna(0) / games_for_rate
    annualized = ppg * 17
    projection = df["projection"].where(df["projection"].notna(), annualized)

    # Players without usable stats/projections receive a conservative position baseline.
    has_signal = (projection.fillna(0) > 0)
    pos_med = projection.where(has_signal).groupby(df["position"]).transform("median")
    overall_pos_defaults = {"QB": 230.0, "RB": 130.0, "WR": 135.0, "TE": 105.0}
    fallback = df["position"].map(overall_pos_defaults).astype(float)
    projection = projection.where(has_signal, pos_med.fillna(fallback) * 0.65)

    sample_weight = (df["games"].clip(upper=17) / 17.0).clip(lower=0.35)
    supplied_projection = df["projection"].notna()
    regressed = projection * sample_weight + projection.groupby(df["position"]).transform("median") * (1 - sample_weight)
    projection = projection.where(supplied_projection, regressed)

    projection *= df["injury_status"].map(_injury_projection_multiplier)

    df["projection"] = projection.round(2)
    df["fantasy_ppg"] = ppg.round(2)
    df["role"] = df.apply(assign_role, axis=1)
    df["health_score"] = df["injury_status"].map(_health_score)

    demand = {
        "QB": max(1, int(round(config.teams * (config.qb + 0.78 * config.superflex)))),
        "RB": max(1, int(round(config.teams * (config.rb + 0.42 * config.flex + 0.05 * config.superflex)))),
        "WR": max(1, int(round(config.teams * (config.wr + 0.48 * config.flex + 0.05 * config.superflex)))),
        "TE": max(1, int(round(config.teams * (config.te + 0.10 * config.flex + 0.02 * config.superflex)))),
    }

    replacement: dict[str, float] = {}
    for pos, grp in df.groupby("position"):
        vals = grp["projection"].sort_values(ascending=False).reset_index(drop=True)
        idx = min(max(demand.get(pos, 1) - 1, 0), len(vals) - 1)
        replacement[pos] = float(vals.iloc[idx]) if len(vals) else 0.0

    df["replacement_points"] = df["position"].map(replacement).fillna(0)
    df["vor"] = df["projection"] - df["replacement_points"]

    g = df["games"].replace(0, np.nan).fillna(17).clip(lower=1)
    usage = pd.Series(0.0, index=df.index)
    usage += (df["rushing_attempts"].fillna(0) / g) * df["position"].eq("RB") * 1.4
    usage += (df["targets"].fillna(0) / g) * df["position"].isin(["RB", "WR", "TE"]) * 2.0
    usage += (df["passing_yards"].fillna(0) / g / 25.0) * df["position"].eq("QB")
    df["usage_index"] = _minmax(usage)

    df["floor_score"] = _minmax(df["projection"] * (0.82 + 0.18 * (df["games"].clip(upper=17) / 17)))
    age_bonus = np.where(df["age"] <= 24, 1.06, np.where(df["age"] >= 31, 0.95, 1.0))
    role_bonus = np.where(df["role"].str.contains("Alpha|Workhorse|Dual-Threat|Elite Target|Upside", regex=True), 1.05, 1.0)
    df["upside_score"] = _minmax(df["projection"] * age_bonus * role_bonus)

    market_rank = df["adp"].copy()
    market_rank = market_rank.where(market_rank.notna(), df["ecr"])
    if market_rank.isna().all():
        market_rank = df["projection"].rank(method="first", ascending=False)
    else:
        market_rank = market_rank.fillna(df["projection"].rank(method="first", ascending=False))
    df["market_score"] = _minmax(-market_rank)

    depth = pd.to_numeric(df["depth_chart_order"], errors="coerce")
    depth_score = 100 - (depth.fillna(2.5) - 1).clip(lower=0) * 18
    df["depth_score"] = depth_score.clip(lower=20, upper=100)

    base = (
        0.40 * _minmax(df["projection"])
        + 0.25 * _minmax(df["vor"])
        + 0.12 * df["usage_index"]
        + 0.13 * df["market_score"]
        + 0.05 * df["depth_score"]
        + 0.05 * df["health_score"]
    )
    df["draft_value"] = base.round(1)
    df["overall_rank"] = df["draft_value"].rank(method="first", ascending=False).astype(int)
    df["position_rank"] = df.groupby("position")["draft_value"].rank(method="first", ascending=False).astype(int)

    tiers = pd.Series(index=df.index, dtype=int)
    for pos, grp in df.groupby("position"):
        g2 = grp.sort_values("draft_value", ascending=False)
        tier = 1
        anchor = None
        count_in_tier = 0
        for idx, row in g2.iterrows():
            score = float(row["draft_value"])
            if anchor is not None and count_in_tier >= 3 and anchor - score >= 4.5:
                tier += 1
                anchor = score
                count_in_tier = 0
            elif anchor is None:
                anchor = score
            tiers.loc[idx] = tier
            count_in_tier += 1
    df["tier"] = tiers.astype(int)

    df["adp"] = df["adp"].where(df["adp"].notna(), df["ecr"])
    df["adp"] = df["adp"].where(df["adp"].notna(), df["overall_rank"].astype(float))
    df["ecr"] = df["ecr"].where(df["ecr"].notna(), df["adp"])

    return df.sort_values(["draft_value", "projection"], ascending=False).reset_index(drop=True)


def snake_pick_metadata(teams: int, rounds: int) -> pd.DataFrame:
    rows = []
    overall = 1
    for rnd in range(1, rounds + 1):
        slots = range(1, teams + 1) if rnd % 2 == 1 else range(teams, 0, -1)
        for slot in slots:
            rows.append({"pick": overall, "round": rnd, "slot": slot, "team": f"Team {slot}"})
            overall += 1
    return pd.DataFrame(rows)


def next_pick_for_slot(current_pick: int, teams: int, rounds: int, user_slot: int) -> Optional[int]:
    meta = snake_pick_metadata(teams, rounds)
    future = meta[(meta["pick"] >= current_pick) & (meta["slot"] == user_slot)]
    if future.empty:
        return None
    return int(future.iloc[0]["pick"])


def roster_counts(draft_log: List[dict], slot: int) -> Dict[str, int]:
    counts = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
    for pick in draft_log:
        if int(pick.get("slot", -1)) == int(slot):
            pos = pick.get("position")
            if pos in counts:
                counts[pos] += 1
    return counts


def roster_need_factor(position: str, counts: Dict[str, int], config: LeagueConfig) -> float:
    targets = {"QB": config.qb, "RB": config.rb, "WR": config.wr, "TE": config.te}
    missing = max(targets.get(position, 0) - counts.get(position, 0), 0)
    if missing > 0:
        return 1.13 + min(0.12, 0.04 * missing)

    if position == "QB" and config.superflex > 0:
        qb_sf_target = config.qb + config.superflex
        if counts.get("QB", 0) < qb_sf_target:
            return 1.12

    flex_eligible = position in {"RB", "WR", "TE"}
    base_skill_starters = config.rb + config.wr + config.te
    skill_owned = counts["RB"] + counts["WR"] + counts["TE"]
    if flex_eligible and skill_owned < base_skill_starters + config.flex:
        return 1.06

    if config.superflex > 0:
        total_sf_eligible = counts["QB"] + counts["RB"] + counts["WR"] + counts["TE"]
        primary = config.qb + config.rb + config.wr + config.te + config.flex
        if total_sf_eligible < primary + config.superflex:
            return 1.05 if position == "QB" else 1.01

    return 0.92 if position in {"QB", "TE"} else 0.98


def availability_probability(adp: float, next_pick: Optional[int], scale: float = 5.5) -> float:
    if next_pick is None or pd.isna(adp):
        return 0.5
    x = (float(adp) - float(next_pick)) / max(scale, 0.1)
    return float(1.0 / (1.0 + exp(-x)))


def recommend_players(
    ranked: pd.DataFrame,
    draft_log: List[dict],
    config: LeagueConfig,
    user_slot: int,
    current_pick: int,
    top_n: int = 50,
    monte_carlo: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    drafted_ids = {str(p.get("player_id")) for p in draft_log}
    avail = ranked[~ranked["player_id"].astype(str).isin(drafted_ids)].copy()
    if avail.empty:
        return avail

    counts = roster_counts(draft_log, user_slot)
    next_user_pick = next_pick_for_slot(current_pick + 1, config.teams, config.rounds, user_slot)
    avail["roster_fit"] = avail["position"].map(lambda p: roster_need_factor(p, counts, config))
    avail["p_available_next"] = avail["adp"].map(lambda a: availability_probability(a, next_user_pick))

    if monte_carlo is not None and not monte_carlo.empty:
        mc_cols = ["player_id", "mc_p_available_next", "wait_value", "take_now_edge", "fallback_if_gone"]
        avail = avail.merge(monte_carlo[mc_cols], on="player_id", how="left")
        avail["p_available_next"] = avail["mc_p_available_next"].where(
            avail["mc_p_available_next"].notna(), avail["p_available_next"]
        )
    else:
        avail["mc_p_available_next"] = np.nan
        avail["wait_value"] = np.nan
        avail["take_now_edge"] = np.nan
        avail["fallback_if_gone"] = ""

    avail["urgency"] = 1.0 - avail["p_available_next"]

    pos_remaining = avail.groupby("position")["draft_value"].transform("count")
    pos_top = avail.groupby("position")["draft_value"].transform("max")
    scarcity_raw = (pos_top - avail["draft_value"]).abs() + 100 / pos_remaining.clip(lower=1)
    sf_qb_bonus = avail["position"].eq("QB").astype(float) * config.superflex * 8.0
    avail["scarcity_score"] = _minmax(avail["vor"] + scarcity_raw + sf_qb_bonus)

    injury_penalty = (100 - avail["health_score"]) * 0.025
    avail["recommendation_score"] = (
        avail["draft_value"] * avail["roster_fit"]
        + 7.0 * avail["urgency"]
        + 0.06 * avail["scarcity_score"]
        - injury_penalty
    ).round(2)

    if "take_now_edge" in avail.columns:
        avail["recommendation_score"] += avail["take_now_edge"].fillna(0).clip(-5, 8) * 0.20

    avail["why"] = avail.apply(_recommendation_reason, axis=1)
    return avail.sort_values(["recommendation_score", "draft_value"], ascending=False).head(top_n).reset_index(drop=True)


def _recommendation_reason(row: pd.Series) -> str:
    reasons = []
    if float(row.get("roster_fit", 1)) >= 1.1:
        reasons.append("fills a starter/SF need")
    if float(row.get("urgency", 0)) >= 0.70:
        reasons.append("unlikely to reach your next pick")
    if _safe_num(row.get("take_now_edge"), 0) >= 3:
        reasons.append("Monte Carlo favors taking now")
    if float(row.get("vor", 0)) > 20:
        reasons.append("strong value over replacement")
    if float(row.get("upside_score", 0)) >= 78:
        reasons.append("high-upside profile")
    if float(row.get("health_score", 100)) < 60:
        reasons.append("meaningful injury risk")
    if not reasons:
        reasons.append("solid board value")
    return "; ".join(reasons[:2])


def simulate_opponent_pick(
    ranked: pd.DataFrame,
    draft_log: List[dict],
    config: LeagueConfig,
    slot: int,
    current_pick: int,
) -> Optional[pd.Series]:
    drafted_ids = {str(p.get("player_id")) for p in draft_log}
    avail = ranked[~ranked["player_id"].astype(str).isin(drafted_ids)].copy()
    if avail.empty:
        return None
    counts = roster_counts(draft_log, slot)
    avail["fit"] = avail["position"].map(lambda p: roster_need_factor(p, counts, config))
    avail["adp_pull"] = np.exp(-np.abs(avail["adp"] - current_pick) / 18.0)
    avail["sim_score"] = avail["draft_value"] * avail["fit"] + 8 * avail["adp_pull"]
    return avail.sort_values("sim_score", ascending=False).iloc[0]


def monte_carlo_wait_analysis(
    ranked: pd.DataFrame,
    draft_log: List[dict],
    config: LeagueConfig,
    user_slot: int,
    current_pick: int,
    simulations: int = 300,
    candidate_count: int = 30,
    seed: int = 2026,
) -> pd.DataFrame:
    """Estimate survival to the user's next pick and the value of waiting.

    This is a draft-state model, not a claim about the true probability of any
    individual platform pick. Opponent choices are sampled from ADP, board value,
    and their inferred positional needs.
    """
    next_user_pick = next_pick_for_slot(current_pick + 1, config.teams, config.rounds, user_slot)
    if next_user_pick is None or next_user_pick <= current_pick + 1:
        return pd.DataFrame(columns=["player_id", "mc_p_available_next", "wait_value", "take_now_edge", "fallback_if_gone"])

    drafted_ids = {str(p.get("player_id")) for p in draft_log}
    avail = ranked[~ranked["player_id"].astype(str).isin(drafted_ids)].copy()
    if avail.empty:
        return pd.DataFrame()

    user_counts = roster_counts(draft_log, user_slot)
    avail["user_fit"] = avail["position"].map(lambda p: roster_need_factor(p, user_counts, config))
    pos_remaining = avail.groupby("position")["draft_value"].transform("count")
    avail["base_user_score"] = avail["draft_value"] * avail["user_fit"] + 4.0 / pos_remaining.clip(lower=1)

    candidates = avail.sort_values("base_user_score", ascending=False).head(candidate_count).copy()
    candidate_ids = candidates["player_id"].astype(str).tolist()
    candidate_score = dict(zip(candidates["player_id"].astype(str), candidates["base_user_score"]))
    candidate_name = dict(zip(candidates["player_id"].astype(str), candidates["player"]))

    alive_counts = Counter()
    wait_sum = Counter()
    fallback_counters = {pid: Counter() for pid in candidate_ids}

    meta = snake_pick_metadata(config.teams, config.rounds).set_index("pick")
    ranked_index = avail.set_index(avail["player_id"].astype(str), drop=False)
    all_ids = ranked_index.index.tolist()
    rng = np.random.default_rng(seed + current_pick + len(draft_log) * 17)

    for _ in range(int(simulations)):
        alive = set(all_ids)
        sim_log = [dict(p) for p in draft_log]

        for pick_no in range(current_pick + 1, next_user_pick):
            if pick_no not in meta.index or not alive:
                break
            slot = int(meta.loc[pick_no, "slot"])
            counts = roster_counts(sim_log, slot)
            pool = ranked_index.loc[list(alive)].copy()
            pool = pool.sort_values("draft_value", ascending=False).head(70)
            fit = pool["position"].map(lambda p: roster_need_factor(p, counts, config)).astype(float)
            adp = pd.to_numeric(pool["adp"], errors="coerce").fillna(pool["overall_rank"])
            utility = (
                (pool["draft_value"].astype(float) - 50.0) / 12.0
                + 1.8 * np.log(fit.clip(lower=0.5))
                - np.abs(adp - pick_no) / 22.0
            )
            utility = utility - utility.max()
            weights = np.exp(utility.clip(lower=-20, upper=0)).to_numpy(dtype=float)
            if not np.isfinite(weights).all() or weights.sum() <= 0:
                chosen = str(pool.iloc[0]["player_id"])
            else:
                weights = weights / weights.sum()
                chosen = str(rng.choice(pool["player_id"].astype(str).to_numpy(), p=weights))
            alive.discard(chosen)
            row = ranked_index.loc[chosen]
            sim_log.append({
                "slot": slot,
                "player_id": chosen,
                "position": str(row["position"]),
                "player": str(row["player"]),
            })

        alive_pool = ranked_index.loc[list(alive)].copy() if alive else ranked_index.iloc[0:0].copy()
        if not alive_pool.empty:
            alive_pool["next_user_score"] = alive_pool["player_id"].astype(str).map(
                dict(zip(avail["player_id"].astype(str), avail["base_user_score"]))
            ).fillna(alive_pool["draft_value"])
            best_next = alive_pool.sort_values("next_user_score", ascending=False).iloc[0]
            best_next_id = str(best_next["player_id"])
            best_next_value = float(best_next["next_user_score"])
        else:
            best_next_id = ""
            best_next_value = 0.0

        for pid in candidate_ids:
            if pid in alive:
                alive_counts[pid] += 1
                wait_sum[pid] += float(candidate_score[pid])
            else:
                wait_sum[pid] += best_next_value
                if best_next_id:
                    fallback_counters[pid][str(ranked_index.loc[best_next_id, "player"])] += 1

    rows = []
    sims = max(int(simulations), 1)
    for pid in candidate_ids:
        wait_value = float(wait_sum[pid]) / sims
        take_value = float(candidate_score[pid])
        fallback = fallback_counters[pid].most_common(1)[0][0] if fallback_counters[pid] else ""
        rows.append({
            "player_id": pid,
            "player": candidate_name[pid],
            "mc_p_available_next": alive_counts[pid] / sims,
            "wait_value": round(wait_value, 2),
            "take_now_edge": round(take_value - wait_value, 2),
            "fallback_if_gone": fallback,
        })
    return pd.DataFrame(rows)


def draft_board(draft_log: List[dict], teams: int, rounds: int) -> pd.DataFrame:
    board = pd.DataFrame("", index=range(1, rounds + 1), columns=[f"Team {i}" for i in range(1, teams + 1)])
    board.index.name = "Round"
    for p in draft_log:
        try:
            rnd = int(p["round"])
            team = f"Team {int(p['slot'])}"
            if rnd in board.index and team in board.columns:
                board.loc[rnd, team] = f"{p['player']} ({p['position']})"
        except (KeyError, TypeError, ValueError):
            continue
    return board


def team_roster(draft_log: List[dict], slot: int) -> pd.DataFrame:
    rows = [p for p in draft_log if int(p.get("slot", -1)) == int(slot)]
    if not rows:
        return pd.DataFrame(columns=["round", "pick", "player", "position", "nfl_team"])
    df = pd.DataFrame(rows)
    for col in ["round", "pick", "player", "position", "nfl_team"]:
        if col not in df.columns:
            df[col] = ""
    return df[["round", "pick", "player", "position", "nfl_team"]].sort_values("pick")
