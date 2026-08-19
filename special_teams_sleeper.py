from __future__ import annotations

"""Sleeper compatibility for kickers and team defenses."""

from dataclasses import replace
from typing import Any

import pandas as pd

from special_teams_support import normalize_position


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def install_sleeper_support(sleeper_module, engine_module) -> None:
    if getattr(sleeper_module, "_draftedge_special_sleeper_enabled", False):
        return

    original_enrich = sleeper_module.enrich_players_from_sleeper
    original_config = sleeper_module.config_from_sleeper
    original_log = sleeper_module.draft_log_from_sleeper

    def fetch_sleeper_players(active_only: bool = True) -> pd.DataFrame:
        suffix = "players/nfl?active=true" if active_only else "players/nfl"
        data = sleeper_module._get_json(suffix, timeout=45)
        rows = []
        if not isinstance(data, dict):
            return pd.DataFrame()
        for pid, p in data.items():
            pos = normalize_position(p.get("position") or "")
            if pos not in {"QB", "RB", "WR", "TE", "K", "DST"}:
                continue
            team = str(p.get("team") or "").upper().strip()
            full_name = p.get("full_name") or " ".join(
                [str(p.get("first_name") or "").strip(), str(p.get("last_name") or "").strip()]
            ).strip()
            if pos == "DST" and not full_name:
                full_name = f"{team or str(pid).upper()} D/ST"
            if not full_name:
                continue
            rows.append({
                "player_id": str(pid),
                "sleeper_id": str(pid),
                "player": full_name,
                "team": team or (str(pid).upper() if pos == "DST" else "FA"),
                "position": pos,
                "age": p.get("age"),
                "years_exp": p.get("years_exp"),
                "injury_status": p.get("injury_status") or "",
                "practice_status": p.get("practice_participation") or "",
                "depth_chart_order": p.get("depth_chart_order"),
                "depth_chart_position": p.get("depth_chart_position") or "",
                "image_url": sleeper_module.sleeper_player_image_url(pid, thumb=False),
                "data_source": "Sleeper player metadata",
            })
        return engine_module.normalize_player_data(pd.DataFrame(rows))

    def enrich_players_from_sleeper(master: pd.DataFrame, sleeper_players: pd.DataFrame) -> pd.DataFrame:
        sleeper = engine_module.normalize_player_data(sleeper_players)
        if sleeper.empty:
            return engine_module.normalize_player_data(master)
        base = engine_module.normalize_player_data(master)

        existing = {(engine_module.normalize_name(r.player), str(r.position)) for r in base.itertuples()}
        specials = sleeper[sleeper["position"].isin(["K", "DST"])].copy()
        missing_rows = []
        for _, row in specials.iterrows():
            key = (engine_module.normalize_name(row["player"]), str(row["position"]))
            if key not in existing:
                existing.add(key)
                missing_rows.append(row)
        if missing_rows:
            base = pd.concat([base, pd.DataFrame(missing_rows)], ignore_index=True, sort=False)
            base = engine_module.normalize_player_data(base)
        return original_enrich(base, sleeper)

    def config_from_sleeper(draft: dict, league: dict | None, current, user_id: str | None = None):
        cfg = original_config(draft, league, current, user_id=user_id)
        settings = draft.get("settings") or {}
        updates = {
            "k": int(settings.get("slots_k") or settings.get("slots_pk") or getattr(current, "k", 1)),
            "dst": int(settings.get("slots_def") or settings.get("slots_dst") or getattr(current, "dst", 1)),
        }

        if league:
            scoring = league.get("scoring_settings") or {}
            simple_map = {
                "kicker_xp_made": "xpm",
                "kicker_xp_missed": "xpmiss",
                "kicker_fg_made": "fgm",
                "kicker_fg_missed": "fgmiss",
                "dst_sack": "sack",
                "dst_interception": "int",
                "dst_fumble_recovery": "fum_rec",
                "dst_td": "def_td",
                "dst_safety": "safe",
                "dst_blocked_kick": "blk_kick",
                "dst_pa_0": "pts_allow_0",
                "dst_pa_1_6": "pts_allow_1_6",
                "dst_pa_7_13": "pts_allow_7_13",
                "dst_pa_14_20": "pts_allow_14_20",
                "dst_pa_21_27": "pts_allow_21_27",
                "dst_pa_28_34": "pts_allow_28_34",
                "dst_pa_35_plus": "pts_allow_35p",
            }
            for attr, key in simple_map.items():
                if key in scoring:
                    updates[attr] = _safe_float(scoring.get(key), getattr(cfg, attr))

        cfg = replace(cfg, **updates)
        return cfg

    def draft_log_from_sleeper(picks, ranked_players, sleeper_players=None):
        log = original_log(picks, ranked_players, sleeper_players)
        for item in log:
            item["position"] = normalize_position(item.get("position") or "")
            if item["position"] == "DST":
                team = str(item.get("nfl_team") or "").upper().strip()
                if not str(item.get("player") or "").strip() or str(item.get("player") or "").startswith("Sleeper player"):
                    item["player"] = f"{team or str(item.get('sleeper_id') or '').upper()} D/ST"
        return log

    sleeper_module.fetch_sleeper_players = fetch_sleeper_players
    sleeper_module.enrich_players_from_sleeper = enrich_players_from_sleeper
    sleeper_module.config_from_sleeper = config_from_sleeper
    sleeper_module.draft_log_from_sleeper = draft_log_from_sleeper
    sleeper_module._draftedge_special_sleeper_enabled = True
