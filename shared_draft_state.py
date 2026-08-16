from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_STATE_DIR = Path(
    os.environ.get(
        "DRAFTEDGE_RUNTIME_DIR",
        str(Path(__file__).resolve().parent / ".draftedge_runtime"),
    )
)
_STATE_FILE = _STATE_DIR / "public_board_state.json"


def _config_to_dict(config: Any) -> dict:
    if config is None:
        return {}
    if is_dataclass(config):
        return asdict(config)
    if isinstance(config, dict):
        return dict(config)
    fields = [
        "teams", "rounds", "user_slot", "qb", "rb", "wr", "te", "flex",
        "superflex", "bench", "ppr", "te_premium",
    ]
    return {name: getattr(config, name) for name in fields if hasattr(config, name)}


def write_public_board_state(
    config: Any,
    draft_log: list[dict] | None,
    extras: dict[str, Any] | None = None,
) -> None:
    """Atomically publish the active draft for board-only viewer sessions."""
    cfg = _config_to_dict(config)
    if extras:
        cfg.update({k: v for k, v in extras.items() if v is not None})
    if not cfg:
        return

    picks = [dict(p) for p in (draft_log or [])]
    teams = int(cfg.get("teams") or 12)
    rounds = int(cfg.get("rounds") or 16)
    total_picks = teams * rounds
    next_pick = min(len(picks) + 1, total_picks + 1)

    payload = {
        "version": 2,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "config": cfg,
        "draft_log": picks,
        "pick_count": len(picks),
        "next_pick": next_pick,
        "total_picks": total_picks,
    }

    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = _STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, _STATE_FILE)


def publish_board_state_from_session(session_state: Any) -> None:
    try:
        config = session_state.get("config")
        draft_log = session_state.get("draft_log", [])
        extras = {
            "owner_names": session_state.get("owner_names"),
            "public_reactions_enabled": session_state.get("public_reactions_enabled"),
            "public_gifs_enabled": session_state.get("public_gifs_enabled"),
            "public_owner_banter_enabled": session_state.get("public_owner_banter_enabled"),
            "public_pick_quality_mode": session_state.get("public_pick_quality_mode"),
            "public_gif_frequency": session_state.get("public_gif_frequency"),
            "public_reaction_seconds": session_state.get("public_reaction_seconds"),
        }
        write_public_board_state(config, draft_log, extras=extras)
    except Exception:
        # Public display synchronization must never interrupt a live draft.
        return


def read_public_board_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
