from __future__ import annotations

"""DraftEdge data-source compatibility layer.

Adds nflverse headshots and normalizes projection exports from common providers,
including Footballguys Draft Projections, before the legacy projection blender
matches them to the DraftEdge player pool.
"""

import re
from typing import Iterable

import numpy as np
import pandas as pd

import data_sources_legacy as _legacy
from data_sources_legacy import *  # noqa: F401,F403
from fantasy_engine import normalize_name, normalize_player_data


_CURRENT_NFL_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
}
_TEAM_ALIASES = {"JAC": "JAX", "WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR"}


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


def _dedupe_headers(values: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    out: list[str] = []
    for i, raw in enumerate(values):
        base = str(raw).strip()
        if not base or base.lower() == "nan":
            base = f"column_{i + 1}"
        n = counts.get(base, 0)
        counts[base] = n + 1
        out.append(base if n == 0 else f"{base}.{n}")
    return out


def _recover_multiline_header(frame: pd.DataFrame) -> pd.DataFrame:
    """Recover exports where a category row was read as the CSV header."""
    if frame.empty:
        return frame.copy()
    if _find_col(frame, ["player", "name", "player_name"]) is not None:
        return frame.copy()

    for idx in frame.head(6).index:
        values = [str(v).strip() for v in frame.loc[idx].tolist()]
        cleaned = {_clean(v) for v in values}
        if "player" in cleaned and ("pos" in cleaned or "position" in cleaned) and (
            "points" in cleaned or "fpts" in cleaned or "fantasypoints" in cleaned
        ):
            out = frame.loc[frame.index > idx].copy()
            out.columns = _dedupe_headers(values)
            return out.reset_index(drop=True)
    return frame.copy()


def _footballguys_signature(frame: pd.DataFrame, source_name: str = "") -> bool:
    if "footballguys" in str(source_name).lower() or re.search(r"\bfbg\b", str(source_name).lower()):
        return True
    test = _recover_multiline_header(frame)
    keys = {_clean(c) for c in test.columns}
    has_player = any(k in keys for k in {"player", "name", "playername"})
    has_pos = any(k in keys for k in {"pos", "position"})
    has_games = any(k in keys for k in {"gms", "games", "projectedgames"})
    has_points = any(k == "points" or k.startswith("points") or k in {"fpts", "fantasypoints"} for k in keys)
    return has_player and has_pos and has_games and has_points


def _projection_points_col(frame: pd.DataFrame):
    preferred = ["fantasy_points", "fantasypoints", "fpts", "projected_points", "projectedpoints", "points"]
    for candidate in preferred:
        col = _find_col(frame, [candidate])
        if col is not None:
            return col

    candidates = []
    for idx, col in enumerate(frame.columns):
        key = _clean(col)
        if "ppg" in key or "pergame" in key:
            continue
        if key.startswith("points") or key.startswith("fpts"):
            numeric = pd.to_numeric(frame[col], errors="coerce")
            candidates.append((int(numeric.notna().sum()), idx, col))
    if candidates:
        candidates.sort()
        return candidates[-1][2]
    return None


def _parse_player_and_team(value: object) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return "", ""
    match = re.search(r"\s+([A-Za-z]{2,3})$", text)
    if match:
        token = match.group(1).upper()
        token = _TEAM_ALIASES.get(token, token)
        if token in _CURRENT_NFL_TEAMS:
            return text[: match.start()].strip(), token
    return text, ""


def normalize_footballguys_projection_csv(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize a Footballguys Draft Projections CSV for DraftEdge blending.

    Footballguys' projection table uses fields such as Player, Pos, GMS, PPG and
    Points. ``Points`` is treated as the season fantasy-point projection. The
    table's ``Rank`` is deliberately *not* treated as ECR because it is a rank of
    the projection output, not an independent market-consensus rank.
    """
    if frame is None or len(frame) == 0:
        return pd.DataFrame(columns=["player", "team", "position", "projection"])

    work = _recover_multiline_header(pd.DataFrame(frame).copy())
    player_col = _find_col(work, ["player", "player_name", "name", "playername"])
    pos_col = _find_col(work, ["pos", "position", "fantasy_position"])
    team_col = _find_col(work, ["team", "tm", "nfl_team", "nflteam"])
    points_col = _projection_points_col(work)
    gms_col = _find_col(work, ["gms", "games", "projected_games", "projectedgames"])
    ppg_col = _find_col(work, ["ppg", "points_per_game", "pointspergame"])
    adp_col = _find_col(work, ["adp", "average_draft_position", "avg_pick"])
    ecr_col = _find_col(work, ["ecr", "expert_consensus_rank", "expertconsensusrank"])

    if player_col is None or pos_col is None:
        raise ValueError("Footballguys projection CSV could not be recognized: Player and Pos columns are required.")
    if points_col is None and not (gms_col is not None and ppg_col is not None):
        raise ValueError("Footballguys projection CSV could not be recognized: expected Points, or both GMS and PPG.")

    parsed = work[player_col].map(_parse_player_and_team)
    out = pd.DataFrame(index=work.index)
    out["player"] = parsed.map(lambda x: x[0])
    parsed_team = parsed.map(lambda x: x[1])
    if team_col is not None:
        explicit_team = work[team_col].fillna("").astype(str).str.upper().str.strip().replace(_TEAM_ALIASES)
        out["team"] = explicit_team.where(explicit_team.ne(""), parsed_team)
    else:
        out["team"] = parsed_team
    out["position"] = work[pos_col].fillna("").astype(str).str.upper().str.strip().replace({"PK": "K"})

    if points_col is not None:
        out["projection"] = pd.to_numeric(work[points_col], errors="coerce")
    else:
        out["projection"] = pd.to_numeric(work[gms_col], errors="coerce") * pd.to_numeric(work[ppg_col], errors="coerce")

    if gms_col is not None:
        out["projected_games"] = pd.to_numeric(work[gms_col], errors="coerce")
    if ppg_col is not None:
        out["projected_ppg"] = pd.to_numeric(work[ppg_col], errors="coerce")
    if adp_col is not None:
        out["adp"] = pd.to_numeric(work[adp_col], errors="coerce")
    if ecr_col is not None:
        out["ecr"] = pd.to_numeric(work[ecr_col], errors="coerce")

    out = out[out["position"].isin(["QB", "RB", "WR", "TE"])].copy()
    out = out[out["player"].astype(str).str.strip().ne("") & out["projection"].notna()].copy()
    out["source_format"] = "Footballguys Draft Projections"
    return out.reset_index(drop=True)


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
    """Blend projection sources, auto-normalizing Footballguys CSV exports."""
    prepared: list[tuple[str, pd.DataFrame, float]] = []
    footballguys_sources: set[str] = set()

    for source_name, frame, weight in sources:
        f = pd.DataFrame(frame).copy() if frame is not None else pd.DataFrame()
        if _footballguys_signature(f, source_name):
            f = normalize_footballguys_projection_csv(f)
            footballguys_sources.add(str(source_name))
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
            lambda name: "Footballguys Draft Projections" if name in footballguys_sources else "Generic projection CSV"
        )
        is_fbg = audit["source"].astype(str).isin(footballguys_sources)
        audit.loc[is_fbg & audit["note"].eq("ok"), "note"] = "ok; Footballguys Points imported as season projection"
    return updated, audit
