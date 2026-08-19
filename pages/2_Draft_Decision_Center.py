from __future__ import annotations

import streamlit as st

import fantasy_engine as _fantasy_engine
from special_teams_support import apply_special_teams_support

# Multipage Streamlit pages execute independently, so install the K/DST engine
# extensions here as well as in the main app entry point.
apply_special_teams_support(_fantasy_engine)

from decision_center_v3 import render_decision_center  # noqa: E402

st.set_page_config(page_title="DraftEdge Decision Center", page_icon="🧭", layout="wide")
render_decision_center()
