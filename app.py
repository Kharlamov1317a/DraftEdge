from __future__ import annotations

"""DraftEdge entry point.

The full draft assistant lives in ``app_legacy.py``. This wrapper adds public-
board controls and publishes draft changes to a shared runtime file so a TV or
projector can display only the public draft board.
"""

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from shared_draft_state import publish_board_state_from_session


# Keep a stable reference across Streamlit reruns so wrappers do not nest.
if not hasattr(st, "_draftedge_original_rerun"):
    st._draftedge_original_rerun = st.rerun

_original_rerun = st._draftedge_original_rerun


def _rerun_with_board_publish(*args, **kwargs):
    publish_board_state_from_session(st.session_state)
    return _original_rerun(*args, **kwargs)


def _init_public_board_settings() -> None:
    defaults = {
        "owner_names": {},
        "public_reactions_enabled": True,
        "public_gifs_enabled": True,
        "public_owner_banter_enabled": True,
        "public_pick_quality_mode": True,
        "public_gif_frequency": 55,
        "public_reaction_seconds": 7,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _giphy_key_configured() -> bool:
    if str(os.environ.get("GIPHY_API_KEY", "")).strip():
        return True
    try:
        return bool(str(st.secrets.get("GIPHY_API_KEY", "")).strip())
    except Exception:
        return False


def _enrich_public_pick_metadata() -> None:
    """Attach private ranking context used only to select a public reaction.

    The extra fields are never shown numerically on the public board. They only
    let the reaction system distinguish likely values, reaches, early-QB picks,
    rookie swings, and late-round darts.
    """
    ranked = globals().get("ranked")
    log = st.session_state.get("draft_log", [])
    if not isinstance(ranked, pd.DataFrame) or ranked.empty or not log:
        return

    work = ranked.copy()
    if "player_id" in work:
        work["_player_id"] = work["player_id"].fillna("").astype(str)
    else:
        work["_player_id"] = ""
    if "sleeper_id" in work:
        work["_sleeper_id"] = work["sleeper_id"].fillna("").astype(str)
    else:
        work["_sleeper_id"] = ""

    by_player = {row["_player_id"]: row for _, row in work.iterrows() if row["_player_id"]}
    by_sleeper = {row["_sleeper_id"]: row for _, row in work.iterrows() if row["_sleeper_id"]}

    for pick in log:
        row = by_player.get(str(pick.get("player_id") or ""))
        if row is None:
            row = by_sleeper.get(str(pick.get("sleeper_id") or ""))
        if row is None:
            continue

        def _number(name: str):
            value = row.get(name)
            try:
                if pd.isna(value):
                    return None
                return float(value)
            except Exception:
                return None

        overall_rank = _number("overall_rank")
        adp = _number("adp")
        ecr = _number("ecr")
        years_exp = _number("years_exp")
        pick_no = float(pick.get("pick") or 0)

        if overall_rank is not None:
            pick["overall_rank"] = overall_rank
            pick["rank_delta"] = pick_no - overall_rank
        if adp is not None:
            pick["adp"] = adp
            pick["adp_delta"] = pick_no - adp
        if ecr is not None:
            pick["ecr"] = ecr
        if years_exp is not None:
            pick["years_exp"] = years_exp
            pick["is_rookie"] = years_exp <= 0


_init_public_board_settings()
st.rerun = _rerun_with_board_publish

_legacy = Path(__file__).resolve().with_name("app_legacy.py")

try:
    # Execute instead of importing so the Streamlit script runs on every rerun.
    exec(compile(_legacy.read_text(encoding="utf-8"), str(_legacy), "exec"), globals(), globals())
finally:
    _enrich_public_pick_metadata()
    publish_board_state_from_session(st.session_state)


with st.sidebar:
    st.divider()
    st.subheader("Public draft board")
    st.page_link(
        "pages/1_Public_Draft_Board.py",
        label="Open public draft board",
        icon="🖥️",
        use_container_width=True,
    )

    with st.expander("Board reactions & owner names", expanded=False):
        st.session_state.public_reactions_enabled = st.toggle(
            "Pick reactions",
            value=bool(st.session_state.public_reactions_enabled),
            help="Show a joke, roast, or congratulations message after each new pick.",
        )
        st.session_state.public_gifs_enabled = st.toggle(
            "Reaction GIFs",
            value=bool(st.session_state.public_gifs_enabled),
            disabled=not st.session_state.public_reactions_enabled,
            help="Show a relevant popular reaction GIF when GIPHY is configured.",
        )
        st.session_state.public_gif_frequency = st.slider(
            "GIF frequency",
            0,
            100,
            int(st.session_state.public_gif_frequency),
            5,
            format="%d%%",
            disabled=(not st.session_state.public_reactions_enabled or not st.session_state.public_gifs_enabled),
            help="Not every pick needs a GIF. Text/emoji reactions still appear on the other picks.",
        )
        st.session_state.public_owner_banter_enabled = st.toggle(
            "Owner-specific banter",
            value=bool(st.session_state.public_owner_banter_enabled),
            disabled=not st.session_state.public_reactions_enabled,
        )
        st.session_state.public_pick_quality_mode = st.toggle(
            "Use pick context for reactions",
            value=bool(st.session_state.public_pick_quality_mode),
            disabled=not st.session_state.public_reactions_enabled,
            help=(
                "Uses DraftEdge rank/ADP plus round and position context to choose reactions such as "
                "value, reach, early QB, rookie hype, or late-round dart. The numerical rankings stay private."
            ),
        )
        st.session_state.public_reaction_seconds = st.slider(
            "Reaction display time",
            3,
            12,
            int(st.session_state.public_reaction_seconds),
            1,
            format="%d sec",
            disabled=not st.session_state.public_reactions_enabled,
        )

        if st.session_state.public_gifs_enabled:
            if _giphy_key_configured():
                st.success("GIPHY GIF provider configured.")
            else:
                st.warning(
                    "Reaction GIFs need a GIPHY_API_KEY in Streamlit Cloud secrets. "
                    "Until then, the public board automatically falls back to text + emoji reactions."
                )

        st.markdown("**Owner names**")
        try:
            team_count = int(st.session_state.config.teams)
        except Exception:
            team_count = 12

        current_names = dict(st.session_state.get("owner_names", {}) or {})
        updated_names: dict[int, str] = {}
        for slot in range(1, team_count + 1):
            existing = str(current_names.get(slot, current_names.get(str(slot), "")) or "")
            name = st.text_input(
                f"Pick slot {slot}",
                value=existing,
                placeholder=f"Team {slot}",
                key=f"public_owner_name_{slot}",
            ).strip()
            if name:
                updated_names[slot] = name
        st.session_state.owner_names = updated_names

        st.caption(
            "Owner names appear on the public board and in reactions. Leave a slot blank to keep Team #."
        )

    # Publish sidebar changes immediately rather than waiting for another pick.
    publish_board_state_from_session(st.session_state)
