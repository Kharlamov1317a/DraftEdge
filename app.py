from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:  # optional runtime convenience; manual refresh still works
    st_autorefresh = None

from data_sources import blend_projection_sources, load_nflverse_bundle
from demo_data import make_demo_players
from fantasy_engine import (
    LeagueConfig,
    draft_board,
    monte_carlo_wait_analysis,
    next_pick_for_slot,
    normalize_player_data,
    prepare_rankings,
    recommend_players,
    simulate_opponent_pick,
    snake_pick_metadata,
    team_roster,
)
from sleeper_client import (
    config_from_sleeper,
    draft_log_from_sleeper,
    enrich_players_from_sleeper,
    fetch_draft,
    fetch_draft_picks,
    fetch_league,
    fetch_sleeper_players,
    fetch_user,
)


APP_NAME = "DraftEdge Fantasy Draft Assistant v3"
st.set_page_config(
    page_title=APP_NAME,
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="auto",
)

st.markdown(
    """
    <style>
    .small-note {font-size: 0.84rem; color: #6b7280;}
    .recommend-card {border: 1px solid #d1d5db; border-radius: 10px; padding: 12px; min-height: 145px;}
    .current-pick {font-size: 1.35rem; font-weight: 700;}
    .sync-good {border-left: 4px solid #888; padding-left: 10px;}

    /* Touch targets and horizontal tab scrolling improve phone use without
       changing the desktop layout. Streamlit stacks columns automatically. */
    button, [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"] {
        min-height: 42px;
    }
    [data-baseweb="tab-list"] {
        overflow-x: auto;
        scrollbar-width: thin;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-top: 1rem;
            padding-left: 0.75rem;
            padding-right: 0.75rem;
            padding-bottom: 3rem;
        }
        h1 {font-size: 1.65rem !important; line-height: 1.15 !important;}
        h2 {font-size: 1.35rem !important;}
        h3 {font-size: 1.15rem !important;}
        .current-pick {font-size: 1.15rem;}
        .recommend-card {min-height: 0; padding: 10px;}
        [data-testid="stDataFrame"] {font-size: 0.82rem;}
        [data-baseweb="tab"] {white-space: nowrap;}
        div[data-testid="stHorizontalBlock"] {gap: 0.5rem;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def default_config() -> LeagueConfig:
    return LeagueConfig()


def init_state():
    defaults = {
        "config": default_config(),
        "players": make_demo_players(),
        "draft_log": [],
        "data_label": "Synthetic demo data",
        "projection_audit": pd.DataFrame(),
        "nflverse_messages": [],
        "nflverse_loaded": {},
        "sleeper_draft_id": "",
        "sleeper_username": "",
        "sleeper_auto_refresh": False,
        "sleeper_refresh_seconds": 10,
        "sleeper_connected": False,
        "sleeper_sync_message": "",
        "mc_enabled": True,
        "mc_simulations": 300,
        "mc_key": None,
        "mc_results": pd.DataFrame(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def pick_info(config: LeagueConfig):
    current_pick = len(st.session_state.draft_log) + 1
    meta = snake_pick_metadata(config.teams, config.rounds)
    if current_pick > len(meta):
        return current_pick, None
    return current_pick, meta.iloc[current_pick - 1]


def record_pick(player_row: pd.Series, pick_row: pd.Series):
    st.session_state.draft_log.append({
        "pick": int(pick_row["pick"]),
        "round": int(pick_row["round"]),
        "slot": int(pick_row["slot"]),
        "team": str(pick_row["team"]),
        "player_id": str(player_row["player_id"]),
        "sleeper_id": str(player_row.get("sleeper_id", "") or ""),
        "player": str(player_row["player"]),
        "position": str(player_row["position"]),
        "nfl_team": str(player_row["team"]),
        "draft_value": float(player_row.get("draft_value", 0)),
        "source": "manual",
    })
    st.session_state.mc_key = None


def recommendation_cards(recs: pd.DataFrame):
    if recs.empty:
        st.info("No players remain.")
        return
    candidates = [
        ("Best Pick", recs.sort_values("recommendation_score", ascending=False).iloc[0]),
        ("Best Value", recs.sort_values("draft_value", ascending=False).iloc[0]),
        ("Safest", recs.sort_values("floor_score", ascending=False).iloc[0]),
        ("Upside", recs.sort_values("upside_score", ascending=False).iloc[0]),
        ("Scarcity", recs.sort_values("scarcity_score", ascending=False).iloc[0]),
    ]
    if recs["take_now_edge"].notna().any():
        candidates.append(("Take Now", recs.sort_values("take_now_edge", ascending=False).iloc[0]))
    else:
        candidates.append(("Role Fit", recs.sort_values(["roster_fit", "draft_value"], ascending=False).iloc[0]))

    cols = st.columns(3)
    for i, (label, row) in enumerate(candidates):
        with cols[i % 3]:
            st.markdown('<div class="recommend-card">', unsafe_allow_html=True)
            st.markdown(f"**{label}**")
            st.markdown(f"### {row['player']}")
            st.caption(f"{row['position']} · {row['team']} · Tier {int(row['tier'])} · {row['role']}")
            st.write(f"Value **{row['draft_value']:.1f}** · Proj **{row['projection']:.1f}**")
            if pd.notna(row.get("mc_p_available_next")):
                st.caption(
                    f"MC next-pick availability: {float(row['mc_p_available_next'])*100:.0f}% · "
                    f"Take-now edge: {float(row.get('take_now_edge', 0)):+.1f}"
                )
            st.caption(str(row.get("why", "")))
            st.markdown("</div>", unsafe_allow_html=True)


def serialize_draft(config: LeagueConfig) -> str:
    payload = {
        "app_version": 3,
        "league_config": asdict(config),
        "data_label": st.session_state.data_label,
        "draft_log": st.session_state.draft_log,
        "sleeper_draft_id": st.session_state.sleeper_draft_id,
        "sleeper_username": st.session_state.sleeper_username,
    }
    return json.dumps(payload, indent=2)


@st.cache_data(ttl=86400, show_spinner=False)
def cached_sleeper_players() -> pd.DataFrame:
    return fetch_sleeper_players(active_only=True)


@st.cache_data(ttl=5, show_spinner=False)
def cached_sleeper_picks(draft_id: str) -> list[dict]:
    return fetch_draft_picks(draft_id)


def sync_sleeper_picks(ranked: pd.DataFrame, force: bool = False):
    draft_id = st.session_state.sleeper_draft_id.strip()
    if not draft_id:
        return
    try:
        if force:
            cached_sleeper_picks.clear()
        picks = cached_sleeper_picks(draft_id)
        sp = cached_sleeper_players()
        new_log = draft_log_from_sleeper(picks, ranked, sp)
        changed = len(new_log) != len(st.session_state.draft_log) or [p.get("player_id") for p in new_log] != [
            p.get("player_id") for p in st.session_state.draft_log
        ]
        st.session_state.draft_log = new_log
        st.session_state.sleeper_connected = True
        st.session_state.sleeper_sync_message = f"Synced {len(new_log)} picks from Sleeper."
        if changed:
            st.session_state.mc_key = None
    except Exception as exc:
        st.session_state.sleeper_sync_message = f"Sleeper sync failed: {exc}"


def connect_sleeper_and_apply_settings(ranked: pd.DataFrame):
    draft_id = st.session_state.sleeper_draft_id.strip()
    if not draft_id:
        st.error("Enter a Sleeper draft ID first.")
        return
    try:
        draft = fetch_draft(draft_id)
        user_id = None
        username = st.session_state.sleeper_username.strip()
        if username:
            user = fetch_user(username)
            user_id = str(user.get("user_id")) if user else None
        league = None
        league_id = draft.get("league_id")
        if league_id:
            try:
                league = fetch_league(str(league_id))
            except Exception:
                league = None
        st.session_state.config = config_from_sleeper(draft, league, st.session_state.config, user_id=user_id)
        sp = cached_sleeper_players()
        st.session_state.players = enrich_players_from_sleeper(st.session_state.players, sp)
        st.session_state.data_label = st.session_state.data_label + " + Sleeper metadata"
        ranked_after = prepare_rankings(st.session_state.players, st.session_state.config)
        picks = fetch_draft_picks(draft_id)
        st.session_state.draft_log = draft_log_from_sleeper(picks, ranked_after, sp)
        st.session_state.sleeper_connected = True
        st.session_state.sleeper_sync_message = (
            f"Connected to Sleeper draft {draft_id}; applied league/draft settings and synced {len(picks)} picks."
        )
        st.session_state.mc_key = None
        st.success(st.session_state.sleeper_sync_message)
    except Exception as exc:
        st.error(f"Could not connect to Sleeper: {exc}")


init_state()

st.title("🏈 DraftEdge Fantasy Draft Assistant v3")
st.caption(
    "Phone + desktop ready · live draft board · 2026 data ingest · Superflex/TE premium · "
    "injuries/depth charts · projection blending · Monte Carlo pick advice · Sleeper sync"
)

with st.expander("📱 Phone / cross-device access", expanded=False):
    st.markdown(
        "**Hosted:** deploy this folder to Streamlit Community Cloud and open the resulting `*.streamlit.app` "
        "URL from Safari, Chrome, or any computer. Add it to your iPhone Home Screen for app-like access.  "
        "\n\n**Same Wi-Fi:** run `run_draftedge_network.sh` (macOS/Linux) or "
        "`run_draftedge_windows.bat` (Windows), then open the printed LAN address on your iPhone.  "
        "\n\n**Cross-device draft state:** Sleeper-connected drafts re-sync from Sleeper on either device. "
        "For manual drafts, use **League & Draft → Download draft state** and load the JSON on the other device."
    )

with st.sidebar:
    st.header("League setup")
    cfg: LeagueConfig = st.session_state.config
    teams = st.slider("Teams", 8, 16, int(cfg.teams))
    rounds = st.slider("Draft rounds", 10, 24, int(cfg.rounds))
    user_slot = st.number_input("Your draft slot", 1, teams, min(int(cfg.user_slot), teams), step=1)

    scoring_options = ["PPR", "Half-PPR", "Standard", "Custom"]
    default_scoring = "PPR" if cfg.ppr == 1 else "Half-PPR" if cfg.ppr == 0.5 else "Standard" if cfg.ppr == 0 else "Custom"
    scoring = st.selectbox("Scoring", scoring_options, index=scoring_options.index(default_scoring))
    ppr = {"PPR": 1.0, "Half-PPR": 0.5, "Standard": 0.0}.get(scoring, cfg.ppr)
    if scoring == "Custom":
        ppr = st.number_input("Points per reception", 0.0, 2.0, float(cfg.ppr), 0.1)
    te_premium = st.number_input("TE premium (extra PPR)", 0.0, 2.0, float(cfg.te_premium), 0.1)

    st.subheader("Starters")
    c1, c2 = st.columns(2)
    qb = c1.number_input("QB", 0, 3, int(cfg.qb))
    rb = c2.number_input("RB", 0, 5, int(cfg.rb))
    wr = c1.number_input("WR", 0, 6, int(cfg.wr))
    te = c2.number_input("TE", 0, 3, int(cfg.te))
    flex = c1.number_input("FLEX", 0, 4, int(cfg.flex))
    superflex = c2.number_input("SUPERFLEX", 0, 3, int(cfg.superflex))
    bench = c1.number_input("Bench", 0, 18, int(cfg.bench))

    if st.button("Apply league settings", use_container_width=True):
        st.session_state.config = LeagueConfig(
            teams=int(teams), rounds=int(rounds), user_slot=int(user_slot), qb=int(qb), rb=int(rb), wr=int(wr),
            te=int(te), flex=int(flex), superflex=int(superflex), bench=int(bench), ppr=float(ppr),
            te_premium=float(te_premium), pass_yd_per_point=cfg.pass_yd_per_point, pass_td=cfg.pass_td,
            interception=cfg.interception, rush_yd_per_point=cfg.rush_yd_per_point, rush_td=cfg.rush_td,
            rec_yd_per_point=cfg.rec_yd_per_point, rec_td=cfg.rec_td, fumble=cfg.fumble,
        )
        st.session_state.draft_log = []
        st.session_state.mc_key = None
        st.success("Settings applied. Draft reset.")
        st.rerun()

    st.divider()
    st.subheader("Monte Carlo")
    st.session_state.mc_enabled = st.toggle("Use take-now vs wait model", value=bool(st.session_state.mc_enabled))
    st.session_state.mc_simulations = st.slider("Simulations", 100, 1000, int(st.session_state.mc_simulations), 100)
    st.caption("Runs automatically on your pick; models opponent selections from ADP, board value, and roster need.")
    st.divider()
    st.caption(f"Data: {st.session_state.data_label}")

cfg = st.session_state.config
ranked = prepare_rankings(st.session_state.players, cfg)

# Optional Sleeper polling. Player metadata is cached for a day; draft picks are cached for 5 seconds.
if st.session_state.sleeper_auto_refresh and st.session_state.sleeper_draft_id.strip():
    if st_autorefresh is not None:
        st_autorefresh(interval=int(st.session_state.sleeper_refresh_seconds) * 1000, key="sleeper_live_refresh")
        sync_sleeper_picks(ranked)
    else:
        st.session_state.sleeper_sync_message = "Auto-refresh package unavailable; use Refresh picks manually."

current_pick, current_meta = pick_info(cfg)

mc = pd.DataFrame()
if (
    st.session_state.mc_enabled
    and current_meta is not None
    and int(current_meta["slot"]) == int(cfg.user_slot)
):
    mc_key = (
        len(st.session_state.draft_log), int(st.session_state.mc_simulations), cfg.teams, cfg.user_slot,
        cfg.superflex, cfg.ppr, cfg.te_premium, st.session_state.data_label,
    )
    if st.session_state.mc_key != mc_key:
        with st.spinner("Running take-now vs wait simulations…"):
            st.session_state.mc_results = monte_carlo_wait_analysis(
                ranked,
                st.session_state.draft_log,
                cfg,
                cfg.user_slot,
                current_pick,
                simulations=int(st.session_state.mc_simulations),
                candidate_count=30,
            )
        st.session_state.mc_key = mc_key
    mc = st.session_state.mc_results

recs = recommend_players(
    ranked,
    st.session_state.draft_log,
    cfg,
    cfg.user_slot,
    current_pick,
    top_n=100,
    monte_carlo=mc,
)

room_tab, rankings_tab, sync_tab, data_tab, setup_tab = st.tabs(
    ["🎯 Draft Room", "📊 Rankings", "🔄 Sleeper Live", "📥 Data Hub", "⚙️ League & Draft"]
)

with room_tab:
    if current_meta is None:
        st.success("Draft complete.")
    else:
        is_user = int(current_meta["slot"]) == cfg.user_slot
        st.markdown(
            f'<div class="current-pick">Pick {current_pick} · Round {int(current_meta["round"])} · '
            f'{current_meta["team"]}{" — YOUR PICK" if is_user else ""}</div>',
            unsafe_allow_html=True,
        )
        next_user = next_pick_for_slot(current_pick + 1, cfg.teams, cfg.rounds, cfg.user_slot)
        if next_user:
            st.caption(f"Your next scheduled pick after this one: {next_user}")
        if is_user and not mc.empty:
            top_mc = mc.sort_values("take_now_edge", ascending=False).iloc[0]
            st.info(
                f"Monte Carlo urgency leader: **{top_mc['player']}** — "
                f"{float(top_mc['mc_p_available_next'])*100:.0f}% estimated chance to reach your next pick; "
                f"take-now edge {float(top_mc['take_now_edge']):+.1f}."
            )

    st.subheader("Pick suggestions")
    recommendation_cards(recs)

    st.divider()
    left, right = st.columns([1.05, 1.25])
    with left:
        st.subheader("Enter current pick")
        if current_meta is not None:
            drafted_ids = {str(p["player_id"]) for p in st.session_state.draft_log}
            available = ranked[~ranked["player_id"].astype(str).isin(drafted_ids)].copy()
            available["label"] = available.apply(
                lambda r: f"#{int(r['overall_rank'])} {r['player']} — {r['position']} {r['team']} (Tier {int(r['tier'])})", axis=1
            )
            selected_label = st.selectbox("Player drafted", available["label"].tolist(), key="draft_select")
            selected = available.loc[available["label"] == selected_label].iloc[0]
            b1, b2, b3 = st.columns(3)
            if b1.button("Draft selected", type="primary", use_container_width=True):
                record_pick(selected, current_meta)
                st.rerun()
            if b2.button(
                "Sim opponent",
                disabled=int(current_meta["slot"]) == cfg.user_slot,
                use_container_width=True,
            ):
                sim = simulate_opponent_pick(ranked, st.session_state.draft_log, cfg, int(current_meta["slot"]), current_pick)
                if sim is not None:
                    record_pick(sim, current_meta)
                    st.rerun()
            if b3.button("Undo", disabled=len(st.session_state.draft_log) == 0, use_container_width=True):
                st.session_state.draft_log.pop()
                st.session_state.mc_key = None
                st.rerun()

            st.caption(
                f"Role: **{selected['role']}** · Projection: **{selected['projection']:.1f}** · "
                f"VOR: **{selected['vor']:.1f}** · ADP/ECR: **{selected['adp']:.1f}/{selected['ecr']:.1f}**"
            )
            injury = str(selected.get("injury_status", "") or "").strip() or "No listed injury"
            depth = selected.get("depth_chart_order")
            depth_text = "unknown" if pd.isna(depth) else str(int(depth))
            st.caption(f"Health: **{injury}** · Depth-chart order: **{depth_text}**")

            rec_match = recs[recs["player_id"].astype(str).eq(str(selected["player_id"]))]
            if not rec_match.empty:
                r = rec_match.iloc[0]
                st.caption(f"Recommendation context: {r['why']}")
                if pd.notna(r.get("mc_p_available_next")):
                    fallback = str(r.get("fallback_if_gone", "") or "")
                    st.caption(
                        f"MC: **{float(r['mc_p_available_next'])*100:.0f}%** chance to survive to next pick · "
                        f"take-now edge **{float(r.get('take_now_edge', 0)):+.1f}**"
                        + (f" · common fallback: **{fallback}**" if fallback else "")
                    )

        st.subheader("Your roster")
        roster = team_roster(st.session_state.draft_log, cfg.user_slot)
        st.dataframe(roster, use_container_width=True, hide_index=True)

    with right:
        st.subheader("Top available")
        cols = [
            "overall_rank", "player", "position", "team", "tier", "role", "projection", "vor", "draft_value",
            "adp", "ecr", "p_available_next", "take_now_edge", "injury_status", "depth_chart_order", "why"
        ]
        show = recs[[c for c in cols if c in recs.columns]].copy() if not recs.empty else recs
        if not show.empty:
            show["p_available_next"] = (show["p_available_next"] * 100).round(0).astype(int).astype(str) + "%"
            show = show.rename(columns={
                "overall_rank": "Rank", "player": "Player", "position": "Pos", "team": "Team", "tier": "Tier",
                "role": "Role", "projection": "Proj", "vor": "VOR", "draft_value": "Value", "adp": "ADP",
                "ecr": "ECR", "p_available_next": "Next-pick avail.", "take_now_edge": "Take-now edge",
                "injury_status": "Injury", "depth_chart_order": "Depth", "why": "Why"
            })
        st.dataframe(show.head(35), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Draft board")
    st.dataframe(draft_board(st.session_state.draft_log, cfg.teams, cfg.rounds), use_container_width=True)

with rankings_tab:
    st.subheader("Dynamic player rankings")
    st.caption(
        "Draft Value combines projected scoring, value over replacement, historical usage, current market rank, "
        "depth-chart position, and injury status. Superflex and TE premium change the underlying valuation."
    )
    c1, c2, c3 = st.columns([1, 1, 1.2])
    pfilter = c1.multiselect("Position", ["QB", "RB", "WR", "TE"], default=["QB", "RB", "WR", "TE"])
    tier_max = c2.slider("Max tier", 1, max(1, int(ranked["tier"].max() if not ranked.empty else 1)), min(8, int(ranked["tier"].max() if not ranked.empty else 1)))
    role_search = c3.text_input("Filter role/player", "")
    view = ranked[ranked["position"].isin(pfilter) & ranked["tier"].le(tier_max)].copy()
    if role_search:
        q = role_search.lower()
        view = view[view["player"].str.lower().str.contains(q) | view["role"].str.lower().str.contains(q)]
    display_cols = [
        "overall_rank", "player", "team", "position", "position_rank", "tier", "role", "age", "games",
        "fantasy_ppg", "projection", "vor", "draft_value", "adp", "ecr", "injury_status", "practice_status",
        "depth_chart_order"
    ]
    st.dataframe(view[display_cols].head(300), use_container_width=True, hide_index=True)

    st.subheader("Role categories")
    st.markdown(
        "**QB:** Dual-Threat, High-Volume Passer, Pocket, Streaming/Developmental  \n"
        "**RB:** Workhorse, Receiving, Goal-Line, Early-Down/Committee, Handcuff/Upside  \n"
        "**WR:** Alpha/Target-Hog, Deep-Threat, Red-Zone, Possession, Boom/Bust/Upside  \n"
        "**TE:** Elite Target, High-Volume, Red-Zone, Streaming/Upside"
    )

    csv = ranked.to_csv(index=False).encode("utf-8")
    st.download_button("Download current rankings CSV", csv, "draftedge_rankings_v3.csv", "text/csv")

with sync_tab:
    st.subheader("Sleeper live draft synchronization")
    st.caption("Sleeper's public API is read-only: DraftEdge reads draft settings and picks; it never makes picks for you.")
    c1, c2 = st.columns(2)
    with c1:
        st.session_state.sleeper_draft_id = st.text_input(
            "Sleeper draft ID", value=st.session_state.sleeper_draft_id, placeholder="e.g. 123456789012345678"
        )
        st.session_state.sleeper_username = st.text_input(
            "Your Sleeper username (optional, used to infer your draft slot)", value=st.session_state.sleeper_username
        )
    with c2:
        st.session_state.sleeper_auto_refresh = st.toggle(
            "Auto-refresh picks", value=bool(st.session_state.sleeper_auto_refresh)
        )
        st.session_state.sleeper_refresh_seconds = st.slider(
            "Refresh every (seconds)", 5, 60, int(st.session_state.sleeper_refresh_seconds), 5
        )

    b1, b2, b3 = st.columns(3)
    if b1.button("Connect + apply Sleeper settings", type="primary", use_container_width=True):
        connect_sleeper_and_apply_settings(ranked)
        st.rerun()
    if b2.button("Refresh picks now", use_container_width=True):
        sync_sleeper_picks(ranked, force=True)
        st.rerun()
    if b3.button("Refresh Sleeper player metadata", use_container_width=True):
        try:
            cached_sleeper_players.clear()
            sp = cached_sleeper_players()
            st.session_state.players = enrich_players_from_sleeper(st.session_state.players, sp)
            st.session_state.data_label += " + refreshed Sleeper metadata"
            st.session_state.mc_key = None
            st.success(f"Updated metadata for {len(sp)} active Sleeper players.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if st.session_state.sleeper_sync_message:
        st.info(st.session_state.sleeper_sync_message)
    st.write(f"**Synced picks:** {len(st.session_state.draft_log)}")
    st.write(f"**Auto-refresh:** {'on' if st.session_state.sleeper_auto_refresh else 'off'}")
    st.caption(
        "Tip: the draft ID is the numeric ID in a Sleeper draft URL. Player metadata is cached locally for up to one day; "
        "draft picks are polled separately so live refresh does not repeatedly download the full player map."
    )

with data_tab:
    st.subheader("Automatic 2026 data")
    st.markdown(
        "Use **nflverse** for automated historical player stats plus current rosters, injuries, depth charts, and fantasy rankings. "
        "For a 2026 redraft, the recommended setup is 2025 historical production + 2026 roster/status/ranking data."
    )
    c1, c2 = st.columns(2)
    season = c1.number_input("Draft season", 2024, 2030, 2026, step=1)
    historical_season = c2.number_input("Historical-stat season", 2020, 2029, int(season) - 1, step=1)
    if st.button("Load nflverse player pool", type="primary"):
        try:
            with st.spinner("Downloading nflverse datasets…"):
                result = load_nflverse_bundle(int(season), int(historical_season))
            if result.players.empty:
                st.error("nflverse returned no usable QB/RB/WR/TE player rows.")
            else:
                st.session_state.players = result.players
                st.session_state.data_label = f"nflverse: {historical_season} stats + {season} current data"
                st.session_state.nflverse_messages = result.messages
                st.session_state.nflverse_loaded = result.loaded
                st.session_state.draft_log = []
                st.session_state.mc_key = None
                st.success(f"Loaded {len(result.players)} fantasy-relevant players.")
                st.rerun()
        except Exception as exc:
            st.error(f"nflverse load failed: {exc}")

    if st.session_state.nflverse_loaded:
        st.dataframe(
            pd.DataFrame(
                [{"dataset": k, "rows": v} for k, v in st.session_state.nflverse_loaded.items()]
            ),
            use_container_width=True,
            hide_index=True,
        )
    for message in st.session_state.nflverse_messages:
        st.warning(message)

    st.divider()
    st.subheader("PFR / custom historical CSV")
    st.caption(
        "PFR remains upload-based rather than automatically scraped. Common fields such as Player, Tm, FantPos, G, Tgt, Rec, FantPt and PPR are recognized."
    )
    f = st.file_uploader("Upload a PFR/custom player CSV", type=["csv"], key="player_upload_v3")
    if f is not None:
        raw = pd.read_csv(f)
        st.dataframe(raw.head(15), use_container_width=True)
        try:
            normalized = normalize_player_data(raw)
            if st.button("Use uploaded player pool"):
                st.session_state.players = normalized
                st.session_state.data_label = f.name
                st.session_state.draft_log = []
                st.session_state.mc_key = None
                st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Projection blending")
    st.caption(
        "Upload multiple projection CSVs and set a weight for each source. Each file needs a player/name column and a projection column. "
        "Position is recommended; ADP/ECR columns are blended when present."
    )
    projection_files = st.file_uploader(
        "Projection files", type=["csv"], accept_multiple_files=True, key="projection_files_v3"
    )
    baseline_weight = st.slider("Weight: DraftEdge historical baseline", 0.0, 5.0, 1.0, 0.25)
    sources = []
    if projection_files:
        for i, pf in enumerate(projection_files):
            weight = st.slider(f"Weight: {pf.name}", 0.0, 5.0, 1.0, 0.25, key=f"weight_{i}_{pf.name}")
            try:
                pf.seek(0)
                sources.append((pf.name, pd.read_csv(pf), weight))
            except Exception as exc:
                st.error(f"Could not read {pf.name}: {exc}")
    if st.button("Blend projections into current player pool", disabled=not bool(sources)):
        try:
            master = normalize_player_data(st.session_state.players)
            baseline_ranked = prepare_rankings(master, cfg)
            baseline_map = baseline_ranked.set_index("player_id")["projection"]
            baseline = master["player_id"].map(baseline_map)
            blended, audit = blend_projection_sources(
                master, sources, baseline_projection=baseline, baseline_weight=float(baseline_weight)
            )
            st.session_state.players = blended
            st.session_state.projection_audit = audit
            st.session_state.data_label += " + blended projections"
            st.session_state.mc_key = None
            st.success("Projection blend applied.")
            st.rerun()
        except Exception as exc:
            st.error(f"Projection blend failed: {exc}")

    if not st.session_state.projection_audit.empty:
        st.dataframe(st.session_state.projection_audit, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Current data coverage")
    current = normalize_player_data(st.session_state.players)
    coverage = pd.DataFrame([
        {"field": "Players", "coverage": len(current)},
        {"field": "Explicit projections", "coverage": int(current["projection"].notna().sum())},
        {"field": "ADP", "coverage": int(current["adp"].notna().sum())},
        {"field": "ECR/rank", "coverage": int(current["ecr"].notna().sum())},
        {"field": "Injury status", "coverage": int(current["injury_status"].fillna("").astype(str).ne("").sum())},
        {"field": "Depth chart", "coverage": int(current["depth_chart_order"].notna().sum())},
        {"field": "Sleeper IDs", "coverage": int(current["sleeper_id"].fillna("").astype(str).ne("").sum())},
    ])
    st.dataframe(coverage, use_container_width=True, hide_index=True)

    if st.button("Reload synthetic demo data"):
        st.session_state.players = make_demo_players()
        st.session_state.data_label = "Synthetic demo data"
        st.session_state.draft_log = []
        st.session_state.mc_key = None
        st.rerun()

with setup_tab:
    st.subheader("Draft controls & persistence")
    st.write(f"**Format:** {cfg.teams}-team snake · {cfg.rounds} rounds · Your slot: {cfg.user_slot}")
    st.write(
        f"**Starters:** {cfg.qb} QB · {cfg.rb} RB · {cfg.wr} WR · {cfg.te} TE · "
        f"{cfg.flex} FLEX · {cfg.superflex} SUPERFLEX · {cfg.bench} bench"
    )
    st.write(f"**Reception scoring:** {cfg.ppr:g} PPR · TE premium +{cfg.te_premium:g} PPR")

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download draft state (.json)",
            data=serialize_draft(cfg),
            file_name="draftedge_draft_state_v3.json",
            mime="application/json",
            use_container_width=True,
        )
        if st.button("Reset draft", use_container_width=True):
            st.session_state.draft_log = []
            st.session_state.mc_key = None
            st.rerun()
    with c2:
        upload_state = st.file_uploader("Load saved draft state", type=["json"], key="state_upload_v2")
        if upload_state is not None and st.button("Load state", use_container_width=True):
            payload = json.load(upload_state)
            st.session_state.config = LeagueConfig(**payload["league_config"])
            st.session_state.draft_log = payload.get("draft_log", [])
            st.session_state.sleeper_draft_id = payload.get("sleeper_draft_id", "")
            st.session_state.sleeper_username = payload.get("sleeper_username", "")
            st.session_state.mc_key = None
            st.rerun()

    st.subheader("Pick log")
    st.dataframe(pd.DataFrame(st.session_state.draft_log), use_container_width=True, hide_index=True)

    st.subheader("Canonical player input columns")
    st.code(
        "player,team,position,age,games,passing_yards,passing_td,interceptions,"
        "rushing_attempts,rushing_yards,rushing_td,targets,receptions,receiving_yards,receiving_td,"
        "fumbles,fantasy_points,projection,adp,ecr,injury_status,practice_status,depth_chart_order,sleeper_id",
        language="text",
    )

st.caption(
    "DraftEdge v3 · Recommendations are decision-support estimates, not guaranteed player outcomes or draft probabilities. "
    "PFR data is imported by the user; automated data uses nflverse and optional read-only Sleeper synchronization. "
    "The UI is responsive for desktop and mobile browsers."
)
