from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import os
import time

import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

from public_board_reactions import make_pick_reaction
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
    /* Board-only mode: intentionally hide navigation back to rankings and
       recommendations when this URL is shared with league owners. */
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
    .reaction-pop {
        position: sticky;
        top: 0.35rem;
        z-index: 1000;
        margin: 0 auto 0.8rem auto;
        max-width: 1040px;
        border-radius: 16px;
        padding: 12px 14px;
        background: linear-gradient(135deg, rgba(255,247,237,.98), rgba(254,242,242,.98));
        border: 2px solid #fdba74;
        box-shadow: 0 14px 34px rgba(0,0,0,.14);
        animation: draftedge-pop-in 260ms ease-out;
        display: grid;
        grid-template-columns: minmax(180px, 280px) 1fr;
        gap: 14px;
        align-items: center;
    }
    .reaction-pop.no-gif {grid-template-columns: 1fr;}
    .reaction-media img {
        width: 100%;
        max-height: 190px;
        object-fit: cover;
        border-radius: 12px;
        background: #fff7ed;
    }
    .giphy-credit {font-size: 0.66rem; color: #78716c; margin-top: 3px; text-align: center;}
    .reaction-kicker {font-size: 0.82rem; letter-spacing: .08em; text-transform: uppercase; color: #9a3412; font-weight: 800;}
    .reaction-line {font-size: 1.35rem; line-height: 1.15; font-weight: 800; margin-top: 4px;}
    .reaction-sub {font-size: 0.92rem; color: #57534e; margin-top: 5px;}
    @keyframes draftedge-pop-in {
        from {opacity: 0; transform: translateY(-10px) scale(.98);}
        to {opacity: 1; transform: translateY(0) scale(1);}
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
    .caption-muted {font-size: 0.83rem; color: #64748b; margin-top: 0.45rem;}

    @media (max-width: 900px) {
        .reaction-pop {grid-template-columns: 1fr;}
        .reaction-media img {max-height: 220px;}
    }
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


def _giphy_api_key() -> str:
    env_key = str(os.environ.get("GIPHY_API_KEY", "")).strip()
    if env_key:
        return env_key
    try:
        return str(st.secrets.get("GIPHY_API_KEY", "")).strip()
    except Exception:
        return ""


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
pick_count = int(state.get("pick_count") or len(picks))

reactions_enabled = bool(cfg.get("public_reactions_enabled", True))
gifs_enabled = bool(cfg.get("public_gifs_enabled", True))
owner_banter_enabled = bool(cfg.get("public_owner_banter_enabled", True))
quality_mode = bool(cfg.get("public_pick_quality_mode", True))
gif_frequency = max(0, min(int(cfg.get("public_gif_frequency", 55)), 100))
reaction_seconds = max(3, min(int(cfg.get("public_reaction_seconds", 7)), 12))
giphy_key = _giphy_api_key() if gifs_enabled else ""

updated = state.get("updated_at")
updated_text = ""
if updated:
    try:
        dt = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        age = max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
        updated_text = f" · updated {age}s ago"
    except Exception:
        pass

slot_to_owner: dict[int, str] = {}
custom_owner_names = cfg.get("owner_names") or {}
if isinstance(custom_owner_names, dict):
    for key, value in custom_owner_names.items():
        try:
            slot_to_owner[int(key)] = str(value)
        except Exception:
            continue
for slot in range(1, teams + 1):
    slot_to_owner.setdefault(slot, f"Team {slot}")

# Reactions are session-local to the public display browser. Opening the board
# mid-draft does not replay old picks; only newly observed selections pop up.
if "public_seen_pick_count" not in st.session_state:
    st.session_state.public_seen_pick_count = pick_count
if "public_reaction" not in st.session_state:
    st.session_state.public_reaction = None
if "public_reaction_until" not in st.session_state:
    st.session_state.public_reaction_until = 0.0

if reactions_enabled and pick_count > int(st.session_state.public_seen_pick_count):
    new_pick = picks[-1] if picks else {}
    st.session_state.public_reaction = make_pick_reaction(
        new_pick,
        slot_to_owner,
        owner_banter_enabled=owner_banter_enabled,
        quality_mode=quality_mode,
        gif_api_key=giphy_key,
        gif_frequency=gif_frequency if gifs_enabled else 0,
    )
    st.session_state.public_reaction_until = time.time() + reaction_seconds
    st.session_state.public_seen_pick_count = pick_count
    try:
        st.toast(f"New pick: {new_pick.get('player', 'Player selected')}", icon="🎉")
    except Exception:
        pass
elif pick_count < int(st.session_state.public_seen_pick_count):
    # Handles undo/reset/new-draft cases without replaying a stale reaction.
    st.session_state.public_seen_pick_count = pick_count
    st.session_state.public_reaction = None
    st.session_state.public_reaction_until = 0.0
elif not reactions_enabled:
    st.session_state.public_seen_pick_count = pick_count
    st.session_state.public_reaction = None
    st.session_state.public_reaction_until = 0.0

st.markdown(
    f'<div class="board-status">{teams}-team snake draft · {rounds} rounds · '
    f'{len(picks)}/{total} picks complete{updated_text}</div>',
    unsafe_allow_html=True,
)

reaction = st.session_state.public_reaction
if reaction and time.time() < float(st.session_state.public_reaction_until):
    gif_url = str(reaction.get("gif_url") or "").strip()
    gif_html = ""
    css_class = "reaction-pop"
    if gif_url:
        gif_title = escape(str(reaction.get("gif_title") or "Reaction GIF"), quote=True)
        gif_html = (
            '<div class="reaction-media">'
            f'<img src="{escape(gif_url, quote=True)}" alt="{gif_title}">'
            '<div class="giphy-credit">GIF via GIPHY</div>'
            '</div>'
        )
    else:
        css_class += " no-gif"

    st.markdown(
        f'<div class="{css_class}">'
        + gif_html
        + '<div>'
        + f'<div class="reaction-kicker">{escape(str(reaction.get("kicker") or "📣 Draft Room Reaction"))}</div>'
        + f'<div class="reaction-line">{escape(str(reaction.get("line") or ""))}</div>'
        + f'<div class="reaction-sub">{escape(str(reaction.get("sub") or ""))}</div>'
        + '</div></div>',
        unsafe_allow_html=True,
    )

if len(picks) >= total:
    banner = "Draft complete"
else:
    round_no = ((next_pick - 1) // teams) + 1
    within = ((next_pick - 1) % teams) + 1
    slot = within if round_no % 2 == 1 else teams - within + 1
    banner_owner = slot_to_owner.get(slot, f"Team {slot}")
    banner = f"On the clock: Pick {next_pick} · Round {round_no} · {banner_owner}"

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
    html.append(f'<th>{escape(slot_to_owner.get(slot, f"Team {slot}"))}</th>')
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

st.markdown(
    '<div class="caption-muted">Public board display only — no rankings, values, projections, or pick suggestions are shown.</div>',
    unsafe_allow_html=True,
)
