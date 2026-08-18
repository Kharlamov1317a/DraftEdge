from __future__ import annotations

"""DraftEdge data-source compatibility layer.

This module preserves the legacy nflverse/projection loaders, adds nflverse
headshots, and normalizes Footballguys projection exports before blending them
into the DraftEdge player pool.
"""

import re
from typing import Iterable

import numpy as np
import pandas as pd

import data_sources_legacy as _legacy
from data_sources_legacy import *  # noqa: F401,F403
from fantasy_engine import LeagueConfig, normalize_name, normalize_player_data


_CURRENT_NFL_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
}
_TEAM_ALIASES = {"JAC": "JAX", "WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR"}
_FANTASY_POSITIONS = {"QB", "RB", "WR", "TE"}


def _to_pandas(obj) -> pd.DataFrame:
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.DataFrame):
        return obj.copy()
    if hasattr(obj, "to_pandas"):
        return obj.to_pandas()
    try:
        return pd.DataFrame(obj)
    except Exception:
        return pd.DataFrame()


def _clean(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _find_col(df: pd.DataFrame, candidates: Iterable[str]):
    lookup = {_clean(c): c for c in df.columns}
    for candidate in candidates:
        key = _clean(candidate)
        if key in lookup:
            return lookup[key]
    return None


def _active_scoring_config(explicit: LeagueConfig | None = None) -> LeagueConfig:
    """Use the active DraftEdge league scoring when running inside Streamlit."""
    if isinstance(explicit, LeagueConfig):
        return explicit
    try:
        import streamlit as st

        cfg = st.session_state.get("config")
        if isinstance(cfg, LeagueConfig):
            return cfg
    except Exception:
        pass
    return LeagueConfig()


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _footballguys_raw_signature(frame: pd.DataFrame, source_name: str = "") -> bool:
    """Detect the raw Footballguys `projection-set-...csv` export.

    The real export contains multiple expert/consensus projection sets and raw
    stat columns such as pass-yds, rush-car, rec-tgt, and rec-yds. It does not
    contain a pre-computed fantasy-points column.
    """
    if frame is None or len(frame) == 0:
        return False
    keys = {str(c).strip().lower() for c in frame.columns}
    required = {"id", "name", "pos", "team", "set-id", "set-name", "ssn-gms"}
    stat_fields = {
        "pass-yds", "pass-td", "pass-int", "rush-car", "rush-yds", "rush-td",
        "rec-rec", "rec-tgt", "rec-yds", "rec-td", "fum-lost",
    }
    return required.issubset(keys) and len(keys & stat_fields) >= 6


def _footballguys_points_signature(frame: pd.DataFrame, source_name: str = "") -> bool:
    """Keep compatibility with simpler Footballguys table-style CSV exports."""
    if frame is None or len(frame) == 0:
        return False
    keys = {_clean(c) for c in frame.columns}
    has_player = any(k in keys for k in {"player", "name", "playername"})
    has_pos = any(k in keys for k in {"pos", "position"})
    has_points = any(k in keys for k in {"points", "fpts", "fantasypoints", "projectedpoints"})
    return has_player and has_pos and has_points and (
        "footballguys" in str(source_name).lower() or "gms" in keys or "ppg" in keys
    )


def _select_footballguys_offensive_consensus(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    work = frame.copy()
    work["__pos"] = work["pos"].fillna("").astype(str).str.upper().str.strip()
    work = work[work["__pos"].isin(_FANTASY_POSITIONS)].copy()
    if work.empty:
        raise ValueError("Footballguys export contained no QB/RB/WR/TE rows.")

    consensus = work[work["set-name"].fillna("").astype(str).str.strip().str.lower().eq("consensus")].copy()
    if not consensus.empty:
        grouped = (
            consensus.groupby("set-id", dropna=False)
            .agg(rows=("name", "size"), positions=("__pos", "nunique"))
            .reset_index()
            .sort_values(["positions", "rows"], ascending=False)
        )
        selected_id = grouped.iloc[0]["set-id"]
        selected = consensus[consensus["set-id"].eq(selected_id)].copy()
        return selected, str(selected_id)

    # Defensive fallback: if a future export omits the explicit Consensus set,
    # build a median consensus across the offensive projection sets.
    stat_cols = [
        c for c in work.columns
        if c.startswith(("pass-", "rush-", "rec-", "fum-")) or c == "ssn-gms"
    ]
    key_cols = ["id", "name", "pos", "team"]
    agg = {c: "median" for c in stat_cols}
    selected = work.groupby(key_cols, as_index=False, dropna=False).agg(agg)
    selected["__pos"] = selected["pos"].fillna("").astype(str).str.upper().str.strip()
    return selected, "median-of-experts"


def _score_footballguys_raw(frame: pd.DataFrame, config: LeagueConfig) -> pd.Series:
    """Score Footballguys raw stat projections with the active league settings."""
    pos = frame["pos"].fillna("").astype(str).str.upper().str.strip()
    points = (
        _num(frame, "pass-yds") / float(config.pass_yd_per_point)
        + _num(frame, "pass-td") * float(config.pass_td)
        + _num(frame, "pass-int") * float(config.interception)
        + _num(frame, "rush-yds") / float(config.rush_yd_per_point)
        + _num(frame, "rush-td") * float(config.rush_td)
        + _num(frame, "rec-rec") * float(config.ppr)
        + _num(frame, "rec-rec") * pos.eq("TE").astype(float) * float(config.te_premium)
        + _num(frame, "rec-yds") / float(config.rec_yd_per_point)
        + _num(frame, "rec-td") * float(config.rec_td)
        + _num(frame, "fum-lost") * float(config.fumble)
    )
    # Successful two-point conversions are worth two fantasy points in standard
    # NFL fantasy scoring. DraftEdge currently has no custom 2PT setting.
    points += 2.0 * (
        _num(frame, "pass-2pt") + _num(frame, "rush-2pt") + _num(frame, "rec-2pt")
    )
    return points


def normalize_footballguys_projection_csv(
    frame: pd.DataFrame,
    scoring_config: LeagueConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Normalize either Footballguys projection export format.

    For the raw `projection-set-preseason-all-YYYY.csv` format, DraftEdge selects
    the offensive Consensus projection set and calculates fantasy points from the
    raw projected stats using the *active DraftEdge league scoring*. This is more
    faithful than assuming a fixed PPR scoring system because the raw CSV itself
    does not store the scoring parameters used on the Footballguys web page.
    """
    if frame is None or len(frame) == 0:
        return pd.DataFrame(columns=["player", "team", "position", "projection"]), {}

    config = _active_scoring_config(scoring_config)
    work = pd.DataFrame(frame).copy()

    if _footballguys_raw_signature(work):
        selected, set_id = _select_footballguys_offensive_consensus(work)
        out = pd.DataFrame(index=selected.index)
        out["player"] = selected["name"].fillna("").astype(str).str.strip()
        out["team"] = (
            selected["team"].fillna("").astype(str).str.upper().str.strip().replace(_TEAM_ALIASES)
        )
        out["position"] = selected["pos"].fillna("").astype(str).str.upper().str.strip()
        out["projection"] = _score_footballguys_raw(selected, config).round(3)
        out["projected_games"] = pd.to_numeric(selected["ssn-gms"], errors="coerce")
        out["footballguys_id"] = selected["id"].fillna("").astype(str)
        out = out[out["position"].isin(_FANTASY_POSITIONS)].copy()
        out = out[out["player"].ne("") & out["projection"].notna()].reset_index(drop=True)

        scoring_text = (
            f"PPR={config.ppr:g}; pass {config.pass_yd_per_point:g} yds/pt; pass TD={config.pass_td:g}; "
            f"INT={config.interception:g}; rush/rec TD={config.rush_td:g}/{config.rec_td:g}; "
            f"TE premium={config.te_premium:g}"
        )
        meta = {
            "format": "Footballguys raw projection-set CSV",
            "detail": f"offensive Consensus set {set_id}; {len(out)} QB/RB/WR/TE rows; scored with active DraftEdge settings ({scoring_text})",
        }
        return out, meta

    # Simpler table-style Footballguys exports with a precomputed Points column.
    player_col = _find_col(work, ["player", "name", "player_name", "playername"])
    pos_col = _find_col(work, ["pos", "position", "fantasy_position"])
    team_col = _find_col(work, ["team", "tm", "nfl_team", "nflteam"])
    points_col = _find_col(work, ["points", "fpts", "fantasy_points", "projected_points"])
    if player_col is None or pos_col is None or points_col is None:
        raise ValueError(
            "Footballguys projection CSV could not be recognized. Expected either the raw projection-set export "
            "or a table with player/name, position, and Points/fpts."
        )

    out = pd.DataFrame(index=work.index)
    out["player"] = work[player_col].fillna("").astype(str).str.strip()
    out["team"] = work[team_col].fillna("").astype(str).str.upper().str.strip() if team_col else ""
    out["position"] = work[pos_col].fillna("").astype(str).str.upper().str.strip()
    out["projection"] = pd.to_numeric(work[points_col], errors="coerce")
    out = out[out["position"].isin(_FANTASY_POSITIONS) & out["projection"].notna()].reset_index(drop=True)
    return out, {
        "format": "Footballguys table projection CSV",
        "detail": f"{len(out)} QB/RB/WR/TE rows; precomputed Points imported",
    }


def _attach_nflverse_headshots(players: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if players is None or len(players) == 0:
        return normalize_player_data(players), 0

    try:
        import nflreadpy as nfl
        loader = getattr(nfl, "load_players", None)
        if loader is None:
            return normalize_player_data(players), 0
        info = _to_pandas(loader())
    except Exception:
        return normalize_player_data(players), 0

    if info.empty:
        return normalize_player_data(players), 0

    gsis_col = _find_col(info, ["gsis_id", "player_id", "gsisid"])
    name_col = _find_col(info, ["display_name", "full_name", "player_name", "player_display_name", "name"])
    pos_col = _find_col(info, ["position", "pos"])
    image_col = _find_col(info, ["headshot", "headshot_url", "image_url", "photo_url"])
    if image_col is None:
        return normalize_player_data(players), len(info)

    meta = pd.DataFrame(index=info.index)
    meta["id_key"] = info[gsis_col].fillna("").astype(str) if gsis_col else ""
    meta["name_key"] = info[name_col].fillna("").map(normalize_name) if name_col else ""
    meta["pos_key"] = info[pos_col].fillna("").astype(str).str.upper() if pos_col else ""
    meta["_image"] = info[image_col].fillna("").astype(str).str.strip()
    meta = meta[meta["_image"].ne("")].copy()
    if meta.empty:
        return normalize_player_data(players), len(info)

    out = normalize_player_data(players).copy()
    out["id_key"] = out["gsis_id"].fillna("").astype(str)
    out["name_key"] = out["player"].map(normalize_name)
    out["pos_key"] = out["position"].astype(str).str.upper()

    by_id = meta[meta["id_key"].ne("")][["id_key", "_image"]].drop_duplicates("id_key", keep="last")
    out = out.merge(by_id.rename(columns={"_image": "_img_id"}), on="id_key", how="left")

    by_name = meta[meta["name_key"].ne("")][["name_key", "pos_key", "_image"]].drop_duplicates(
        ["name_key", "pos_key"], keep="last"
    )
    out = out.merge(by_name.rename(columns={"_image": "_img_name"}), on=["name_key", "pos_key"], how="left")

    existing = out["image_url"].fillna("").astype(str).str.strip()
    by_id_image = out["_img_id"].fillna("").astype(str).str.strip()
    by_name_image = out["_img_name"].fillna("").astype(str).str.strip()
    out["image_url"] = existing.where(existing.ne(""), by_id_image)
    out["image_url"] = out["image_url"].where(out["image_url"].ne(""), by_name_image)

    out = out.drop(columns=["id_key", "name_key", "pos_key", "_img_id", "_img_name"], errors="ignore")
    return normalize_player_data(out), len(info)


def load_nflverse_bundle(season: int, historical_season=None):
    result = _legacy.load_nflverse_bundle(season, historical_season)
    players, player_info_rows = _attach_nflverse_headshots(result.players)
    result.players = players
    if player_info_rows:
        result.loaded["player info / headshots"] = player_info_rows
    image_count = int(players["image_url"].fillna("").astype(str).ne("").sum()) if not players.empty else 0
    if image_count == 0:
        result.messages.append("Player headshots: no image URLs matched; Sleeper metadata remains available as a fallback.")
    return result


def blend_projection_sources(
    master: pd.DataFrame,
    sources: list[tuple[str, pd.DataFrame, float]],
    baseline_projection: pd.Series | None = None,
    baseline_weight: float = 1.0,
):
    """Blend projection sources, auto-normalizing Footballguys exports."""
    prepared: list[tuple[str, pd.DataFrame, float]] = []
    source_meta: dict[str, dict[str, str]] = {}

    for source_name, frame, weight in sources:
        f = pd.DataFrame(frame).copy() if frame is not None else pd.DataFrame()
        if _footballguys_raw_signature(f, source_name) or _footballguys_points_signature(f, source_name):
            f, meta = normalize_footballguys_projection_csv(f)
            source_meta[str(source_name)] = meta
        prepared.append((source_name, f, weight))

    updated, audit = _legacy.blend_projection_sources(
        master,
        prepared,
        baseline_projection=baseline_projection,
        baseline_weight=baseline_weight,
    )
    if audit is not None and not audit.empty:
        audit = audit.copy()
        audit["format"] = audit["source"].astype(str).map(
            lambda name: source_meta.get(name, {}).get("format", "Generic projection CSV")
        )
        audit["details"] = audit["source"].astype(str).map(
            lambda name: source_meta.get(name, {}).get("detail", "")
        )
        recognized = audit["source"].astype(str).isin(source_meta)
        audit.loc[recognized & audit["note"].eq("ok"), "note"] = "ok; Footballguys projections normalized before blending"
    return updated, audit
