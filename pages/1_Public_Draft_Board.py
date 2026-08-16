from __future__ import annotations

from datetime import datetime, timezone
from html import escape

import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

from shared_draft_state import read_public_board_state
from sleeper_client import sleeper_player_image_url


st.set_page_config(
    page_title="DraftEdge Live Draft Board",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stHeaderActionElements"],
    #MainMenu,
    footer {display: none !important; visibility: hidden !important;}

    header[data-testid="stHeader"] {background: transparent; height: 0;}
    .block-container {
        max-width: none;
        padding-top: 0.55rem;
        padding-left: 0.7rem;
        padding-right: 0.7rem;
        padding-bottom: 1rem;
    }
    .board-title {font-size: 1.75rem; font-weight: 800; margin-bottom: 0.1rem;}
    .board-status {font-size: 0.95rem; color: #64748b; margin-bottom: 0.55rem;}
    .current-banner {
        border: 1px solid #d1d5db;
        border-radius: 10px;
        padding: 8px 12px;
        margin: 4px 0 10px 0;
        font-weight: 700;
        font-size: 1.05rem;
    }
    .draft-board-wrap {overflow-x: auto; width: 100%;}
    .draft-board-table {
        border-collapse: collapse;
        table-layout: fixed;
        min-width: 1180px;
        width: 100%;
        font-size: 0.76rem;
    }
    .draft-board-table th,
    .draft-board-table td {
        border: 1px solid #dbe2ea;
        padding: 4px 5px;
        vertical-align: middle;
        min-width: 86px;
        height: 43px;
    }
    .draft-board-table th {
        background: #f8fafc;
        position: sticky;
        top: 0;
        z-index: 2;
        font-size: 0.78rem;
    }
    .round-cell {
        width: 42px !important;
        min-width: 42px !important;
        text-align: center;
        font-weight: 800;
        background: #f8fafc;
    }
    .pick-player {display: flex; align-items: center; gap: 5px; line-height: 1.05;}
    .pick-player img {
        width: 28px;
        height: 28px;
        border-radius: 999px;
        object-fit: cover;
        flex: 0 0 28px;
        background: #f1f5f9;
    }
    .player-name {font-weight: 700; font-size: 0.75rem;}
    .player-meta {font-size: 0.65rem; color: #64748b; margin-top: 2px;}
    .pick-number {font-size: 0.60rem; color: #94a3b8; margin-top: 2px;}

    @media (min-width: 1500px) {
        .draft-board-table {font-size: 0.84rem;}
        .draft-board-table th, .draft-board-table td {height: 49px; padding: 5px 6px;}
        .pick-player img {width: 32px; height: 32px; flex-basis: 32px;}
        .player-name {font-size: 0.82rem;}
        .player-meta {font-size: 0.70rem;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


if st_autorefresh is not None:
    st_autorefresh(interval=1500, key="public_board_refresh")

state = read_public_board_state()

st.markdown('<div class="board-title">🏈 DraftEdge Live Draft Board</div>', unsafe_allow_html=True)

if not state:
    st.info(
        "Waiting for the draft room to publish its board. Open the main DraftEdge page, "
        "configure the league, and make or sync a pick. This display will update automatically."
    )
    st.stop()

cfg = state.get("config") or {}
picks = state.get("draft_log") or []
teams = int(cfg.get("teams") or 12)
rounds = int(cfg.get("rounds") or 16)
total = int(state.get("total_picks") or teams * rounds)
next_pick = int(state.get("next_pick") or (len(picks) + 1))

updated = state.get("updated_at")
updated_text = ""
if updated:
    try:
        dt = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        age = max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
        updated_text = f" · updated {age}s ago"
    except Exception:
        pass

st.markdown(
    f'<div class="board-status">{teams}-team snake draft · {rounds} rounds · '
    f'{len(picks)}/{total} picks complete{updated_text}</div>',
    unsafe_allow_html=True,
)

if len(picks) >= total:
    banner = "Draft complete"
else:
    round_no = ((next_pick - 1) // teams) + 1
    within = ((next_pick - 1) % teams) + 1
    slot = within if round_no % 2 == 1 else teams - within + 1
    banner = f"On the clock: Pick {next_pick} · Round {round_no} · Team {slot}"

st.markdown(f'<div class="current-banner">{escape(banner)}</div>', unsafe_allow_html=True)

pick_by_cell = {}
for pick in picks:
    try:
        pick_by_cell[(int(pick.get("round")), int(pick.get("slot")))] = pick
    except (TypeError, ValueError):
        continue

html = ['<div class="draft-board-wrap"><table class="draft-board-table">']
html.append('<thead><tr><th class="round-cell">Rd</th>')
for slot in range(1, teams + 1):
    html.append(f'<th>Team {slot}</th>')
html.append('</tr></thead><tbody>')

for rnd in range(1, rounds + 1):
    html.append(f'<tr><td class="round-cell">{rnd}</td>')
    for slot in range(1, teams + 1):
        p = pick_by_cell.get((rnd, slot))
        if not p:
            html.append('<td>&nbsp;</td>')
            continue

        name = escape(str(p.get("player") or ""))
        pos = escape(str(p.get("position") or ""))
        nfl_team = escape(str(p.get("nfl_team") or ""))
        pick_no = escape(str(p.get("pick") or ""))
        image = str(p.get("image_url") or "").strip()
        if not image and p.get("sleeper_id"):
            image = sleeper_player_image_url(p.get("sleeper_id"), thumb=True)
        img = f'<img src="{escape(image, quote=True)}" alt="">' if image else ""
        meta = " · ".join(x for x in [pos, nfl_team] if x)
        html.append(
            '<td><div class="pick-player">'
            + img
            + '<div>'
            + f'<div class="player-name">{name}</div>'
            + (f'<div class="player-meta">{meta}</div>' if meta else '')
            + (f'<div class="pick-number">Pick {pick_no}</div>' if pick_no else '')
            + '</div></div></td>'
        )
    html.append('</tr>')

html.append('</tbody></table></div>')
st.markdown(''.join(html), unsafe_allow_html=True)

st.caption("Public board display only — no rankings, values, projections, or pick suggestions are shown.")
