from __future__ import annotations

"""K/DST-aware Decision Center context layered over decision_context.py."""

import pandas as pd
import requests

import decision_context as _base
from special_teams_support import normalize_position
from special_teams_data import TEAM_NAMES


apply_bye_overlap_context = _base.apply_bye_overlap_context
load_team_bye_weeks = _base.load_team_bye_weeks
merge_live_context = _base.merge_live_context


def fetch_sleeper_player_context(timeout: int = 45) -> pd.DataFrame:
    """Load current Sleeper context for QB/RB/WR/TE/K/DST.

    Individual injury fields are meaningful for kickers. D/ST is a team unit, so
    DraftEdge does not pretend it has one injury designation for the entire unit.
    """
    response = requests.get(
        _base.SLEEPER_PLAYERS_URL,
        timeout=timeout,
        headers={"User-Agent": "DraftEdge/3.4"},
    )
    response.raise_for_status()
    data = response.json()
    rows = []
    if not isinstance(data, dict):
        return pd.DataFrame()

    for pid, p in data.items():
        pos = normalize_position(p.get("position") or "")
        if pos not in {"QB", "RB", "WR", "TE", "K", "DST"}:
            continue
        team = _base._norm_team(p.get("team") or (pid if pos == "DST" else ""))
        name = p.get("full_name") or " ".join(
            [str(p.get("first_name") or "").strip(), str(p.get("last_name") or "").strip()]
        ).strip()
        if pos == "DST":
            name = f"{TEAM_NAMES.get(team, team)} D/ST"
        if not name:
            continue
        rows.append({
            "sleeper_id": str(pid),
            "player": name,
            "name_key": _base.normalize_name(name),
            "position": pos,
            "pos_key": pos,
            "team": team,
            "live_roster_status": str(p.get("status") or "").strip(),
            "live_injury_status": "" if pos == "DST" else str(p.get("injury_status") or "").strip(),
            "live_practice_status": "" if pos == "DST" else str(p.get("practice_participation") or "").strip(),
            "injury_start_date": "" if pos == "DST" else str(p.get("injury_start_date") or "").strip(),
            "injury_body_part": "" if pos == "DST" else str(p.get("injury_body_part") or p.get("injury_bodypart") or "").strip(),
            "injury_notes": "" if pos == "DST" else str(p.get("injury_notes") or p.get("injury_note") or "").strip(),
            "news_updated": p.get("news_updated"),
        })
    return pd.DataFrame(rows)
