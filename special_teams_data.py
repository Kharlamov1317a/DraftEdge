from __future__ import annotations

"""Projection and nflverse extensions for kickers and D/ST."""

from html import unescape
import re
from typing import Any

import numpy as np
import pandas as pd

from special_teams_support import FANTASY_POSITIONS, NFL_TEAMS, normalize_position, _pa_points_per_game


TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "LV": "Las Vegas Raiders", "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}
TEAM_ALIASES = {"JAC": "JAX", "WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR"}


def _team(value: Any) -> str:
    text = str(value or "").upper().strip()
    return TEAM_ALIASES.get(text, text)


def _num(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame:
        return pd.Series(0.0, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(0.0)


def _active_config():
    import fantasy_engine as engine
    try:
        import streamlit as st
        cfg = st.session_state.get("config")
        if isinstance(cfg, engine.LeagueConfig):
            return cfg
    except Exception:
        pass
    return engine.LeagueConfig()


def _is_raw_footballguys(frame: pd.DataFrame) -> bool:
    if frame is None or frame.empty:
        return False
    keys = {str(c).lower().strip() for c in frame.columns}
    required = {"id", "name", "pos", "team", "set-id", "set-name", "ssn-gms"}
    useful = {"pass-yds", "rush-yds", "rec-yds", "kck-fgc", "tmd-sck"}
    return required.issubset(keys) and len(keys & useful) >= 3


def _pick_consensus_for_position(frame: pd.DataFrame, raw_pos: str) -> tuple[pd.DataFrame, str]:
    subset = frame[frame["pos"].fillna("").astype(str).str.lower().eq(raw_pos.lower())].copy()
    if subset.empty:
        return subset, ""
    consensus = subset[subset["set-name"].fillna("").astype(str).str.lower().eq("consensus")].copy()
    if not consensus.empty:
        counts = consensus.groupby("set-id", dropna=False).size().sort_values(ascending=False)
        set_id = counts.index[0]
        return consensus[consensus["set-id"].eq(set_id)].copy(), str(set_id)

    stat_cols = [
        c for c in subset.columns
        if c.startswith(("pass-", "rush-", "rec-", "fum-", "kck-", "tmd-", "pr-", "kr-"))
        or c == "ssn-gms"
    ]
    agg = {c: "median" for c in stat_cols}
    out = subset.groupby(["id", "name", "pos", "team"], as_index=False, dropna=False).agg(agg)
    return out, "median-of-experts"


def _score_rows(frame: pd.DataFrame, config) -> pd.Series:
    pos = frame["pos"].fillna("").astype(str).str.lower().str.strip()
    points = pd.Series(0.0, index=frame.index, dtype=float)

    off = pos.isin(["qb", "rb", "wr", "te"])
    if off.any():
        off_points = (
            _num(frame, "pass-yds") / float(config.pass_yd_per_point)
            + _num(frame, "pass-td") * float(config.pass_td)
            + _num(frame, "pass-int") * float(config.interception)
            + _num(frame, "rush-yds") / float(config.rush_yd_per_point)
            + _num(frame, "rush-td") * float(config.rush_td)
            + _num(frame, "rec-rec") * float(config.ppr)
            + _num(frame, "rec-rec") * pos.eq("te").astype(float) * float(config.te_premium)
            + _num(frame, "rec-yds") / float(config.rec_yd_per_point)
            + _num(frame, "rec-td") * float(config.rec_td)
            + _num(frame, "fum-lost") * float(config.fumble)
            + 2.0 * (_num(frame, "pass-2pt") + _num(frame, "rush-2pt") + _num(frame, "rec-2pt"))
        )
        points.loc[off] = off_points.loc[off]

    k = pos.eq("pk")
    if k.any():
        kicker_points = (
            _num(frame, "kck-xpc") * float(config.kicker_xp_made)
            + _num(frame, "kck-xpm") * float(config.kicker_xp_missed)
            + _num(frame, "kck-fgc") * float(config.kicker_fg_made)
            + _num(frame, "kck-fgm") * float(config.kicker_fg_missed)
        )
        points.loc[k] = kicker_points.loc[k]

    dst = pos.eq("td")
    if dst.any():
        dst_points = (
            _num(frame, "tmd-sck") * float(config.dst_sack)
            + _num(frame, "tmd-int") * float(config.dst_interception)
            + _num(frame, "tmd-fmr") * float(config.dst_fumble_recovery)
            + _num(frame, "tmd-td") * float(config.dst_td)
            + _num(frame, "tmd-saf") * float(config.dst_safety)
            + _num(frame, "tmd-blk") * float(config.dst_blocked_kick)
            + (_num(frame, "pr-td") + _num(frame, "kr-td")) * float(config.dst_return_td)
            + _num(frame, "tmd-2pr") * float(config.dst_two_point_return)
        )
        if bool(config.dst_points_allowed_enabled):
            games = _num(frame, "ssn-gms").replace(0, np.nan)
            avg_pa = _num(frame, "tmd-pa") / games
            dst_points += _pa_points_per_game(avg_pa, config).fillna(0.0) * games.fillna(0.0)
        points.loc[dst] = dst_points.loc[dst]
    return points


def normalize_footballguys_complete(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    config = _active_config()
    work = pd.DataFrame(frame).copy()
    raw_positions = ["qb", "rb", "wr", "te", "pk", "td"]
    chunks = []
    selected_sets = {}
    for raw_pos in raw_positions:
        chunk, set_id = _pick_consensus_for_position(work, raw_pos)
        if chunk.empty:
            continue
        selected_sets[raw_pos] = set_id
        chunks.append(chunk)
    if not chunks:
        raise ValueError("Footballguys projection-set CSV contained no QB/RB/WR/TE/PK/team-defense projections.")

    selected = pd.concat(chunks, ignore_index=True, sort=False)
    out = pd.DataFrame(index=selected.index)
    out["player"] = selected["name"].fillna("").astype(str).map(unescape).str.strip()
    out["team"] = selected["team"].map(_team)
    out["position"] = selected["pos"].map(lambda p: normalize_position(str(p).upper()))
    out["projection"] = _score_rows(selected, config).round(3)
    out["projected_games"] = pd.to_numeric(selected["ssn-gms"], errors="coerce")
    out["footballguys_id"] = selected["id"].fillna("").astype(str)
    out = out[out["position"].isin(FANTASY_POSITIONS) & out["player"].ne("")].reset_index(drop=True)

    set_text = ", ".join(f"{p.upper()}={sid}" for p, sid in selected_sets.items())
    pa_note = "PA tiers approximated from projected average PA/game" if config.dst_points_allowed_enabled else "PA tiers disabled"
    detail = f"{len(out)} QB/RB/WR/TE/K/DST rows; consensus sets {set_text}; scored with active DraftEdge settings; {pa_note}"
    return out, {"format": "Footballguys complete projection-set CSV", "detail": detail}


def _normalize_generic_special_source(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    f = frame.copy()
    lookup = {re.sub(r"[^a-z0-9]+", "", str(c).lower()): c for c in f.columns}
    pos_col = next((lookup[k] for k in ["position", "pos", "fantpos"] if k in lookup), None)
    player_col = next((lookup[k] for k in ["player", "name", "playername", "player_name"] if k in lookup), None)
    team_col = next((lookup[k] for k in ["team", "tm", "nflteam"] if k in lookup), None)
    proj_col = next((lookup[k] for k in ["projection", "projectedpoints", "projectedfantasypoints", "fpts", "points"] if k in lookup), None)
    if not (pos_col and player_col and proj_col):
        return pd.DataFrame()
    out = pd.DataFrame({
        "player": f[player_col].fillna("").astype(str).str.strip(),
        "position": f[pos_col].map(normalize_position),
        "projection": pd.to_numeric(f[proj_col], errors="coerce"),
        "team": f[team_col].map(_team) if team_col else "",
    })
    return out[out["position"].isin(["K", "DST"]) & out["projection"].notna()].copy()


def _append_missing_special(master: pd.DataFrame, prepared_sources: list[tuple[str, pd.DataFrame, float]], engine) -> pd.DataFrame:
    base = engine.normalize_player_data(master).copy()
    existing = {(engine.normalize_name(r.player), str(r.position)) for r in base.itertuples()}
    rows = []
    for source_name, source, _weight in prepared_sources:
        generic = _normalize_generic_special_source(source)
        if generic.empty:
            continue
        for _, row in generic.iterrows():
            key = (engine.normalize_name(row["player"]), str(row["position"]))
            if key in existing:
                continue
            existing.add(key)
            team = _team(row.get("team"))
            pid = f"DST_{team}" if row["position"] == "DST" and team else f"SRC_{row['position']}_{engine.normalize_name(row['player'])[:22]}"
            rows.append({
                "player_id": pid,
                "player": row["player"],
                "team": team or "FA",
                "position": row["position"],
                "projection": np.nan,
                "data_source": f"seeded from {source_name}",
            })
    if rows:
        base = pd.concat([base, engine.normalize_player_data(pd.DataFrame(rows))], ignore_index=True, sort=False)
        base = engine.normalize_player_data(base)
    return base


def _extract_nflverse_kickers(season: int) -> pd.DataFrame:
    try:
        import nflreadpy as nfl
        loader = getattr(nfl, "load_rosters", None)
        if loader is None:
            return pd.DataFrame()
        attempts = [lambda: loader([season]), lambda: loader(seasons=[season]), lambda: loader(season=season), lambda: loader(season)]
        raw = pd.DataFrame()
        for attempt in attempts:
            try:
                obj = attempt()
                raw = obj.to_pandas() if hasattr(obj, "to_pandas") else pd.DataFrame(obj)
                if not raw.empty:
                    break
            except Exception:
                continue
        if raw.empty:
            return pd.DataFrame()
        cols = {re.sub(r"[^a-z0-9]+", "", str(c).lower()): c for c in raw.columns}
        pos_col = next((cols[k] for k in ["position", "pos"] if k in cols), None)
        name_col = next((cols[k] for k in ["fullname", "playername", "playerdisplayname", "displayname"] if k in cols), None)
        team_col = next((cols[k] for k in ["team", "teamabbr", "clubcode", "recentteam"] if k in cols), None)
        id_col = next((cols[k] for k in ["gsisid", "playerid"] if k in cols), None)
        age_col = cols.get("age")
        exp_col = next((cols[k] for k in ["yearsexp", "experience", "exp"] if k in cols), None)
        if not pos_col or not name_col:
            return pd.DataFrame()
        mask = raw[pos_col].fillna("").astype(str).str.upper().isin(["K", "PK"])
        k = raw.loc[mask].copy()
        if k.empty:
            return pd.DataFrame()
        return pd.DataFrame({
            "player_id": k[id_col].fillna("").astype(str) if id_col else "",
            "gsis_id": k[id_col].fillna("").astype(str) if id_col else "",
            "player": k[name_col].fillna("").astype(str),
            "team": k[team_col].map(_team) if team_col else "FA",
            "position": "K",
            "age": pd.to_numeric(k[age_col], errors="coerce") if age_col else np.nan,
            "years_exp": pd.to_numeric(k[exp_col], errors="coerce") if exp_col else np.nan,
            "data_source": "nflverse roster",
        })
    except Exception:
        return pd.DataFrame()


def _dst_placeholders() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "player_id": f"DST_{team}", "player": f"{TEAM_NAMES.get(team, team)} D/ST", "team": team,
            "position": "DST", "age": 0, "years_exp": 0, "data_source": "NFL team defense placeholder",
        }
        for team in NFL_TEAMS
    ])


def install_data_support(data_module, engine_module) -> None:
    if getattr(data_module, "_draftedge_special_data_enabled", False):
        return
    original_load = data_module.load_nflverse_bundle
    original_blend = data_module.blend_projection_sources

    def load_nflverse_bundle(season: int, historical_season=None):
        result = original_load(season, historical_season)
        pieces = [engine_module.normalize_player_data(result.players)]
        kickers = _extract_nflverse_kickers(int(season))
        if not kickers.empty:
            pieces.append(engine_module.normalize_player_data(kickers))
            result.loaded["current kickers"] = len(kickers)
        pieces.append(engine_module.normalize_player_data(_dst_placeholders()))
        result.loaded["team defenses"] = len(NFL_TEAMS)
        result.players = engine_module.normalize_player_data(pd.concat(pieces, ignore_index=True, sort=False))
        return result

    def blend_projection_sources(master, sources, baseline_projection=None, baseline_weight: float = 1.0):
        prepared = []
        metadata: dict[str, dict[str, str]] = {}
        for source_name, frame, weight in sources:
            f = pd.DataFrame(frame).copy() if frame is not None else pd.DataFrame()
            if _is_raw_footballguys(f):
                f, meta = normalize_footballguys_complete(f)
                metadata[str(source_name)] = meta
            prepared.append((source_name, f, weight))

        master_before = engine_module.normalize_player_data(master)
        master_ext = _append_missing_special(master_before, prepared, engine_module)
        baseline_ext = baseline_projection
        if baseline_projection is not None and len(master_ext) != len(master_before):
            base = pd.to_numeric(pd.Series(baseline_projection).reset_index(drop=True), errors="coerce")
            baseline_ext = pd.Series(np.nan, index=range(len(master_ext)), dtype=float)
            baseline_ext.iloc[: min(len(base), len(master_before))] = base.iloc[: min(len(base), len(master_before))].to_numpy()

        updated, audit = original_blend(master_ext, prepared, baseline_projection=baseline_ext, baseline_weight=baseline_weight)
        if audit is not None and not audit.empty:
            audit = audit.copy()
            if "format" not in audit:
                audit["format"] = "Generic projection CSV"
            if "details" not in audit:
                audit["details"] = ""
            for source_name, meta in metadata.items():
                mask = audit["source"].astype(str).eq(source_name)
                audit.loc[mask, "format"] = meta.get("format", "Footballguys complete projection-set CSV")
                audit.loc[mask, "details"] = meta.get("detail", "")
                if "note" in audit:
                    audit.loc[mask & audit["note"].astype(str).str.startswith("ok"), "note"] = "ok; QB/RB/WR/TE/K/DST projections normalized and blended"
        return engine_module.normalize_player_data(updated), audit

    data_module.load_nflverse_bundle = load_nflverse_bundle
    data_module.blend_projection_sources = blend_projection_sources
    data_module.normalize_footballguys_complete = normalize_footballguys_complete
    data_module._draftedge_special_data_enabled = True
