from __future__ import annotations

"""DraftEdge entry point.

The original application lives in ``app_legacy.py``. This lightweight wrapper
publishes draft changes to a shared runtime file so the board-only Streamlit
page can run in a separate browser session without exposing rankings or pick
suggestions.
"""

from pathlib import Path

import streamlit as st

from shared_draft_state import publish_board_state_from_session


# Keep a stable reference across Streamlit reruns so wrappers do not nest.
if not hasattr(st, "_draftedge_original_rerun"):
    st._draftedge_original_rerun = st.rerun

_original_rerun = st._draftedge_original_rerun


def _rerun_with_board_publish(*args, **kwargs):
    publish_board_state_from_session(st.session_state)
    return _original_rerun(*args, **kwargs)


st.rerun = _rerun_with_board_publish

_legacy = Path(__file__).resolve().with_name("app_legacy.py")

try:
    # Execute instead of importing so the Streamlit script runs on every rerun.
    exec(compile(_legacy.read_text(encoding="utf-8"), str(_legacy), "exec"), globals(), globals())
finally:
    # Also publish changes that do not explicitly call st.rerun (for example,
    # Sleeper polling during a normal Streamlit rerun).
    publish_board_state_from_session(st.session_state)
