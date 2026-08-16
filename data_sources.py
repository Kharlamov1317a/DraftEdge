from __future__ import annotations

"""DraftEdge data-source compatibility layer.

The v3.2 UI already supports player images, but the nflverse loader did not
populate ``image_url`` reliably. This module preserves the v3.2 loader and adds
headshots from nflverse's canonical ``load_players()`` dataset.
"""

import re

import pandas as pd

import data_sources_legacy as _legacy
from data_sources_legacy import *  # noqa: F401,F403
from fantasy_engine import normalize_name, normalize_player_data


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


def _find_col(df: pd.DataFrame, candidates: list[str]):
    lookup = {re.sub(r"[^a-z0-9]+", "", str(c).lower()): c for c in df.columns}
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        if key in lookup:
            return lookup[key]
    return None


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
