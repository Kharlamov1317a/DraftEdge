from __future__ import annotations

from typing import Any
import re

import numpy as np
import pandas as pd
import requests

from fantasy_engine import normalize_name


SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl?active=true"
TEAM_ALIASES = {"JAC": "JAX", "WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR"}


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


def _norm_team(team: Any) -> str:
    text = str(team or "").upper().strip()
    return TEAM_ALIASES.get(text, text)


def fetch_sleeper_player_context(timeout: int = 45) -> pd.DataFrame:
    """Load current Sleeper metadata for draft-day injury context."""
    response = requests.get(
        SLEEPER_PLAYERS_URL,
        timeout=timeout,
        headers={"User-Agent": "DraftEdge/3.3"},
    )
    response.raise_for_status()
    data = response.json()
    rows: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return pd.DataFrame()

    for pid, p in data.items():
        pos = str(p.get("position") or "").upper().strip()
        if pos not in {"QB", "RB", "WR", "TE"}:
            continue
        name = p.get("full_name") or " ".join(
            [str(p.get("first_name") or "").strip(), str(p.get("last_name") or "").strip()]
        ).strip()
        if not name:
            continue
        rows.append({
            "sleeper_id": str(pid),
            "player": name,
            "name_key": normalize_name(name),
            "position": pos,
            "pos_key": pos,
            "team": _norm_team(p.get("team")),
            "live_roster_status": str(p.get("status") or "").strip(),
            "live_injury_status": str(p.get("injury_status") or "").strip(),
            "live_practice_status": str(p.get("practice_participation") or "").strip(),
            "injury_start_date": str(p.get("injury_start_date") or "").strip(),
            "injury_body_part": str(p.get("injury_body_part") or p.get("injury_bodypart") or "").strip(),
            "injury_notes": str(p.get("injury_notes") or p.get("injury_note") or "").strip(),
            "news_updated": p.get("news_updated"),
        })
    return pd.DataFrame(rows)


def load_team_bye_weeks(season: int) -> pd.DataFrame:
    """Derive each team's regular-season bye week from nflverse schedules."""
    import nflreadpy as nfl

    loader = getattr(nfl, "load_schedules", None)
    if loader is None:
        return pd.DataFrame(columns=["team", "bye_week"])

    attempts = [
        lambda: loader([int(season)]),
        lambda: loader(seasons=[int(season)]),
        lambda: loader(seasons=int(season)),
        lambda: loader(int(season)),
    ]
    schedule = pd.DataFrame()
    for attempt in attempts:
        try:
            schedule = _to_pandas(attempt())
            if not schedule.empty:
                break
        except Exception:
            continue
    if schedule.empty:
        return pd.DataFrame(columns=["team", "bye_week"])

    season_col = _find_col(schedule, ["season", "year"])
    if season_col is not None:
        season_vals = pd.to_numeric(schedule[season_col], errors="coerce")
        subset = schedule[season_vals.eq(int(season))]
        if not subset.empty:
            schedule = subset

    type_col = _find_col(schedule, ["game_type", "season_type"])
    if type_col is not None:
        reg = schedule[schedule[type_col].fillna("").astype(str).str.upper().isin(["REG", "REGULAR"])]
        if not reg.empty:
            schedule = reg

    week_col = _find_col(schedule, ["week"])
    home_col = _find_col(schedule, ["home_team", "home"])
    away_col = _find_col(schedule, ["away_team", "away"])
    if week_col is None or home_col is None or away_col is None:
        return pd.DataFrame(columns=["team", "bye_week"])

    weeks = pd.to_numeric(schedule[week_col], errors="coerce")
    schedule = schedule[weeks.between(1, 18)].copy()
    schedule["__week"] = pd.to_numeric(schedule[week_col], errors="coerce").astype("Int64")
    schedule["__home"] = schedule[home_col].map(_norm_team)
    schedule["__away"] = schedule[away_col].map(_norm_team)

    teams = sorted(set(schedule["__home"].dropna().astype(str)) | set(schedule["__away"].dropna().astype(str)))
    rows: list[dict[str, Any]] = []
    all_weeks = set(range(1, 19))
    for team in teams:
        played = set(
            schedule.loc[(schedule["__home"].eq(team) | schedule["__away"].eq(team)), "__week"]
            .dropna().astype(int).tolist()
        )
        missing = sorted(all_weeks - played)
        bye = missing[0] if len(missing) == 1 else np.nan
        rows.append({"team": team, "bye_week": bye})
    return pd.DataFrame(rows)


def _clean_date(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        dt = pd.to_datetime(text, errors="raise")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return text


def _notes_timeline(notes: str) -> str:
    text = re.sub(r"\s+", " ", str(notes or "")).strip()
    if not text:
        return ""
    patterns = [
        r"\b\d+\s*[-–]\s*\d+\s*(?:weeks?|games?)\b",
        r"\b\d+\+?\s*(?:weeks?|games?)\b",
        r"\bday[- ]to[- ]day\b",
        r"\bweek[- ]to[- ]week\b",
        r"\bseason[- ]ending\b",
        r"\bexpected to (?:miss|return)[^.]{0,80}",
        r"\btargeting (?:a )?return[^.]{0,80}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(0).strip().capitalize()
    return ""


def injury_interpretation(row: pd.Series | dict[str, Any]) -> dict[str, str]:
    getter = row.get if hasattr(row, "get") else lambda key, default="": default
    injury = str(getter("live_injury_status", "") or "").strip()
    practice = str(getter("live_practice_status", "") or "").strip()
    roster = str(getter("live_roster_status", "") or "").strip()
    body = str(getter("injury_body_part", "") or "").strip()
    notes = str(getter("injury_notes", "") or "").strip()
    started = _clean_date(str(getter("injury_start_date", "") or ""))

    combined = " ".join([injury, practice, roster]).lower()
    note_timeline = _notes_timeline(notes)

    if not injury and not body and not notes and not any(x in combined for x in ["injured reserve", "pup", "nfi"]):
        return {
            "injury_display": "🟢 No current injury flag",
            "absence_estimate": "No current absence indicated",
            "injury_detail": "",
            "injury_since": started,
        }

    label_bits = [x for x in [injury, body] if x]
    label = " · ".join(label_bits) if label_bits else (roster or "Injury flag")
    severity = "🟡"
    estimate = "Return timetable not supplied"

    if "injured reserve" in combined or re.search(r"\bir\b", roster.lower()):
        severity = "🔴"
        estimate = "Multi-week absence; exact return date not supplied"
    elif "pup" in combined or "nfi" in combined:
        severity = "🔴"
        estimate = "Unavailable while on reserve list; exact return date not supplied"
    elif "out" in injury.lower():
        severity = "🔴"
        estimate = "Near-term absence; exact return date not supplied"
    elif "doubt" in injury.lower():
        severity = "🔴"
        estimate = "Likely to miss the upcoming game"
    elif "question" in injury.lower():
        severity = "🟡"
        estimate = "Short-term / game-time uncertainty"
    elif "prob" in injury.lower():
        severity = "🟢"
        estimate = "Likely available"
    elif "full" in practice.lower():
        severity = "🟢"
        estimate = "Trending toward availability"
    elif "limited" in practice.lower():
        estimate = "Short-term uncertainty; monitor practice participation"
    elif any(x in practice.lower() for x in ["did not", "dnp"]):
        severity = "🔴"
        estimate = "Elevated short-term absence risk"

    if note_timeline:
        estimate = note_timeline

    detail_parts = []
    if practice:
        detail_parts.append(f"Practice: {practice}")
    if roster and roster.lower() != "active":
        detail_parts.append(f"Roster: {roster}")
    if notes:
        detail_parts.append(notes[:220])

    return {
        "injury_display": f"{severity} {label}",
        "absence_estimate": estimate,
        "injury_detail": " · ".join(detail_parts),
        "injury_since": started,
    }


def merge_live_context(players: pd.DataFrame, sleeper_context: pd.DataFrame, bye_weeks: pd.DataFrame) -> pd.DataFrame:
    out = players.copy()
    out["name_key"] = out["player"].fillna("").map(normalize_name)
    out["pos_key"] = out["position"].fillna("").astype(str).str.upper()
    out["team_key"] = out["team"].map(_norm_team)
    out["sid_key"] = out["sleeper_id"].fillna("").astype(str) if "sleeper_id" in out else ""

    ctx = sleeper_context.copy() if sleeper_context is not None else pd.DataFrame()
    if not ctx.empty:
        by_sid = ctx[ctx["sleeper_id"].fillna("").astype(str).ne("")].drop_duplicates("sleeper_id", keep="last")
        context_cols = [
            "sleeper_id", "live_roster_status", "live_injury_status", "live_practice_status",
            "injury_start_date", "injury_body_part", "injury_notes", "news_updated",
        ]
        out = out.merge(
            by_sid[[c for c in context_cols if c in by_sid.columns]].rename(columns={"sleeper_id": "sid_key"}),
            on="sid_key", how="left",
        )

        name_ctx = ctx.sort_values("sleeper_id").drop_duplicates(["name_key", "pos_key"], keep="last")
        fallback_cols = [
            "name_key", "pos_key", "live_roster_status", "live_injury_status", "live_practice_status",
            "injury_start_date", "injury_body_part", "injury_notes", "news_updated",
        ]
        fallback = name_ctx[[c for c in fallback_cols if c in name_ctx.columns]].copy()
        fallback = fallback.rename(columns={c: f"{c}_name" for c in fallback.columns if c not in {"name_key", "pos_key"}})
        out = out.merge(fallback, on=["name_key", "pos_key"], how="left")
        for col in ["live_roster_status", "live_injury_status", "live_practice_status", "injury_start_date", "injury_body_part", "injury_notes", "news_updated"]:
            name_col = f"{col}_name"
            if col not in out:
                out[col] = np.nan
            if name_col in out:
                current = out[col].fillna("").astype(str)
                incoming = out[name_col].fillna("").astype(str)
                out[col] = current.where(current.ne(""), incoming)

    if bye_weeks is not None and not bye_weeks.empty:
        bye = bye_weeks.copy()
        bye["team_key"] = bye["team"].map(_norm_team)
        out = out.merge(bye[["team_key", "bye_week"]].drop_duplicates("team_key"), on="team_key", how="left")
    else:
        out["bye_week"] = np.nan

    interpretations = out.apply(injury_interpretation, axis=1, result_type="expand")
    for col in interpretations.columns:
        out[col] = interpretations[col]

    drop = [c for c in out.columns if c.endswith("_name")] + ["name_key", "pos_key", "team_key", "sid_key"]
    return out.drop(columns=drop, errors="ignore")


def apply_bye_overlap_context(
    recs: pd.DataFrame,
    draft_log: list[dict[str, Any]],
    user_slot: int,
    bye_weeks: pd.DataFrame,
    penalty_strength: float = 1.5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Warn on bye overlap and softly adjust current Pick Rank only."""
    out = recs.copy()
    bye_map = {}
    if bye_weeks is not None and not bye_weeks.empty:
        bye_map = {
            _norm_team(row["team"]): int(row["bye_week"])
            for _, row in bye_weeks.dropna(subset=["bye_week"]).iterrows()
        }

    roster_rows = []
    for pick in draft_log or []:
        try:
            if int(pick.get("slot", -1)) != int(user_slot):
                continue
        except Exception:
            continue
        team = _norm_team(pick.get("nfl_team") or pick.get("team"))
        bye = bye_map.get(team)
        if bye is None:
            continue
        roster_rows.append({
            "player": str(pick.get("player") or ""),
            "position": str(pick.get("position") or ""),
            "team": team,
            "bye_week": bye,
        })
    roster_byes = pd.DataFrame(roster_rows)

    if "bye_week" not in out.columns:
        out["bye_week"] = out["team"].map(lambda team: bye_map.get(_norm_team(team)))

    week_to_players: dict[int, list[str]] = {}
    week_pos_counts: dict[tuple[int, str], int] = {}
    if not roster_byes.empty:
        for _, row in roster_byes.iterrows():
            week = int(row["bye_week"])
            week_to_players.setdefault(week, []).append(str(row["player"]))
            key = (week, str(row["position"]).upper())
            week_pos_counts[key] = week_pos_counts.get(key, 0) + 1

    overlaps = []
    same_pos = []
    conflict_names = []
    for _, row in out.iterrows():
        if pd.isna(row.get("bye_week")):
            overlaps.append(0)
            same_pos.append(0)
            conflict_names.append("")
            continue
        week = int(row["bye_week"])
        names = week_to_players.get(week, [])
        overlaps.append(len(names))
        same_pos.append(week_pos_counts.get((week, str(row.get("position") or "").upper()), 0))
        conflict_names.append(", ".join(names))

    out["bye_overlap_count"] = overlaps
    out["bye_same_position_overlap"] = same_pos
    out["bye_conflict_players"] = conflict_names
    out["bye_penalty"] = (
        out["bye_overlap_count"].astype(float) * float(penalty_strength)
        + out["bye_same_position_overlap"].astype(float) * float(penalty_strength) * 0.5
    )
    base_score = pd.to_numeric(out.get("recommendation_score"), errors="coerce").fillna(0)
    out["contextual_pick_score"] = (base_score - out["bye_penalty"]).round(2)
    out = out.sort_values(["contextual_pick_score", "model_score"], ascending=False).reset_index(drop=True)
    out["pick_rank"] = np.arange(1, len(out) + 1)
    return out, roster_byes
