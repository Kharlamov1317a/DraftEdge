from __future__ import annotations

from dataclasses import replace
from typing import Optional

import numpy as np
import pandas as pd
import requests

from fantasy_engine import LeagueConfig, normalize_name, normalize_player_data


BASE_URL = "https://api.sleeper.app/v1"
SLEEPER_CDN = "https://sleepercdn.com/content/nfl/players"


def sleeper_player_image_url(player_id: str | int | None, thumb: bool = False) -> str:
    pid = str(player_id or "").strip()
    if not pid:
        return ""
    prefix = "thumb/" if thumb else ""
    return f"{SLEEPER_CDN}/{prefix}{pid}.jpg"


def _get_json(path: str, timeout: int = 20):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "DraftEdge/2.0"})
    response.raise_for_status()
    return response.json()


def fetch_user(username_or_id: str) -> dict:
    return _get_json(f"user/{username_or_id}")


def fetch_draft(draft_id: str) -> dict:
    return _get_json(f"draft/{draft_id}")


def fetch_draft_picks(draft_id: str) -> list[dict]:
    data = _get_json(f"draft/{draft_id}/picks")
    return data if isinstance(data, list) else []


def fetch_league(league_id: str) -> dict:
    return _get_json(f"league/{league_id}")


def fetch_sleeper_players(active_only: bool = True) -> pd.DataFrame:
    suffix = "players/nfl?active=true" if active_only else "players/nfl"
    data = _get_json(suffix, timeout=45)
    rows = []
    if not isinstance(data, dict):
        return pd.DataFrame()
    for pid, p in data.items():
        pos = str(p.get("position") or "").upper()
        if pos not in {"QB", "RB", "WR", "TE"}:
            continue
        full_name = p.get("full_name") or " ".join(
            [str(p.get("first_name") or "").strip(), str(p.get("last_name") or "").strip()]
        ).strip()
        if not full_name:
            continue
        rows.append({
            "player_id": str(pid),
            "sleeper_id": str(pid),
            "player": full_name,
            "team": p.get("team") or "FA",
            "position": pos,
            "age": p.get("age"),
            "years_exp": p.get("years_exp"),
            "injury_status": p.get("injury_status") or "",
            "practice_status": p.get("practice_participation") or "",
            "depth_chart_order": p.get("depth_chart_order"),
            "depth_chart_position": p.get("depth_chart_position") or "",
            "image_url": sleeper_player_image_url(pid, thumb=False),
            "data_source": "Sleeper player metadata",
        })
    return normalize_player_data(pd.DataFrame(rows))


def enrich_players_from_sleeper(master: pd.DataFrame, sleeper_players: pd.DataFrame) -> pd.DataFrame:
    sleeper = normalize_player_data(sleeper_players)
    if sleeper.empty:
        return normalize_player_data(master)
    if master is None or len(master) == 0:
        return sleeper

    out = normalize_player_data(master).copy()
    out["name_key"] = out["player"].map(normalize_name)
    out["pos_key"] = out["position"].astype(str).str.upper()
    sleeper["name_key"] = sleeper["player"].map(normalize_name)
    sleeper["pos_key"] = sleeper["position"].astype(str).str.upper()

    metadata_cols = [
        "name_key", "pos_key", "sleeper_id", "team", "age", "years_exp", "injury_status", "practice_status",
        "depth_chart_order", "depth_chart_position", "image_url"
    ]
    s = sleeper[metadata_cols].drop_duplicates(["name_key", "pos_key"], keep="first").copy()
    s = s.rename(columns={c: f"sl_{c}" for c in metadata_cols if c not in {"name_key", "pos_key"}})
    out = out.merge(s, on=["name_key", "pos_key"], how="left")

    def fill(base: str, incoming: str):
        if incoming not in out.columns:
            return
        if base in {"team", "injury_status", "practice_status", "depth_chart_position", "sleeper_id", "image_url"}:
            current = out[base].fillna("").astype(str)
            inc = out[incoming].fillna("").astype(str)
            out[base] = np.where(inc.ne(""), inc, current)
        else:
            out[base] = pd.to_numeric(out[incoming], errors="coerce").where(
                pd.to_numeric(out[incoming], errors="coerce").notna(), pd.to_numeric(out[base], errors="coerce")
            )

    for base in [
        "sleeper_id", "team", "age", "years_exp", "injury_status", "practice_status", "depth_chart_order",
        "depth_chart_position", "image_url"
    ]:
        fill(base, f"sl_{base}")
    source = out["data_source"].fillna("").astype(str).str.strip()
    out["data_source"] = np.where(source.eq(""), "Sleeper metadata", source + " + Sleeper metadata")
    drop_cols = [c for c in out.columns if c.startswith("sl_")] + ["name_key", "pos_key"]
    return normalize_player_data(out.drop(columns=drop_cols, errors="ignore"))


def config_from_sleeper(
    draft: dict,
    league: Optional[dict],
    current: LeagueConfig,
    user_id: Optional[str] = None,
) -> LeagueConfig:
    settings = draft.get("settings") or {}
    teams = int(settings.get("teams") or current.teams)
    rounds = int(settings.get("rounds") or current.rounds)
    user_slot = current.user_slot
    draft_order = draft.get("draft_order") or {}
    if user_id and str(user_id) in draft_order:
        try:
            user_slot = int(draft_order[str(user_id)])
        except Exception:
            pass
    user_slot = min(max(1, user_slot), teams)

    ppr = current.ppr
    te_premium = current.te_premium
    if league:
        scoring = league.get("scoring_settings") or {}
        try:
            ppr = float(scoring.get("rec", ppr))
        except Exception:
            pass
        # Sleeper custom leagues commonly use bonus_rec_te for TE reception premium.
        try:
            te_premium = float(scoring.get("bonus_rec_te", te_premium) or te_premium)
        except Exception:
            pass

    superflex = int(
        settings.get("slots_super_flex")
        or settings.get("slots_superflex")
        or settings.get("slots_qb_flex")
        or current.superflex
    )
    return replace(
        current,
        teams=teams,
        rounds=rounds,
        user_slot=user_slot,
        qb=int(settings.get("slots_qb", current.qb)),
        rb=int(settings.get("slots_rb", current.rb)),
        wr=int(settings.get("slots_wr", current.wr)),
        te=int(settings.get("slots_te", current.te)),
        flex=int(settings.get("slots_flex", current.flex)),
        superflex=superflex,
        bench=int(settings.get("slots_bn", current.bench)),
        ppr=ppr,
        te_premium=te_premium,
    )


def draft_log_from_sleeper(
    picks: list[dict],
    ranked_players: pd.DataFrame,
    sleeper_players: Optional[pd.DataFrame] = None,
) -> list[dict]:
    ranked = ranked_players.copy()
    ranked["player_id"] = ranked["player_id"].astype(str)
    ranked["sleeper_id"] = ranked.get("sleeper_id", "").fillna("").astype(str)
    ranked["name_key"] = ranked["player"].map(normalize_name)
    ranked["pos_key"] = ranked["position"].astype(str).str.upper()

    sleeper_lookup = {}
    if sleeper_players is not None and len(sleeper_players):
        sp = normalize_player_data(sleeper_players)
        sleeper_lookup = {str(r["sleeper_id"] or r["player_id"]): r for _, r in sp.iterrows()}

    log = []
    for pick in sorted(picks, key=lambda x: int(x.get("pick_no") or 0)):
        sid = str(pick.get("player_id") or "")
        meta = pick.get("metadata") or {}
        pos = str(meta.get("position") or "").upper()
        name = " ".join([str(meta.get("first_name") or "").strip(), str(meta.get("last_name") or "").strip()]).strip()
        team = str(meta.get("team") or "FA")

        match = ranked[ranked["sleeper_id"].eq(sid)]
        if match.empty and sid in sleeper_lookup:
            sp = sleeper_lookup[sid]
            name = str(sp["player"])
            pos = str(sp["position"])
            team = str(sp["team"])
        if match.empty and name:
            key = normalize_name(name)
            match = ranked[ranked["name_key"].eq(key)]
            if pos and not match.empty:
                pos_match = match[match["pos_key"].eq(pos)]
                if not pos_match.empty:
                    match = pos_match

        if not match.empty:
            row = match.iloc[0]
            internal_id = str(row["player_id"])
            name = str(row["player"])
            pos = str(row["position"])
            team = str(row["team"])
            draft_value = float(row.get("draft_value", 0) or 0)
        else:
            internal_id = f"SL_{sid}"
            draft_value = 0.0
            if not name:
                name = f"Sleeper player {sid}"

        pick_no = int(pick.get("pick_no") or 0)
        round_no = int(pick.get("round") or 0)
        slot = int(pick.get("draft_slot") or 0)
        image_url = ""
        if not match.empty and "image_url" in row:
            image_url = str(row.get("image_url") or "")
        if not image_url and sid:
            image_url = sleeper_player_image_url(sid, thumb=False)
        log.append({
            "pick": pick_no,
            "round": round_no,
            "slot": slot,
            "team": f"Team {slot}",
            "player_id": internal_id,
            "sleeper_id": sid,
            "player": name,
            "position": pos,
            "nfl_team": team,
            "image_url": image_url,
            "draft_value": draft_value,
            "source": "Sleeper sync",
        })
    return log
