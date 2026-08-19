from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="DraftEdge Decision Center", page_icon="🧭", layout="wide")

import fantasy_engine as _fantasy_engine  # noqa: E402
from special_teams_support import apply_special_teams_support  # noqa: E402

# Multipage Streamlit pages execute independently, so install the K/DST engine
# extensions here as well as in the main app entry point.
apply_special_teams_support(_fantasy_engine)

from decision_center_v3 import render_decision_center  # noqa: E402

render_decision_center()
