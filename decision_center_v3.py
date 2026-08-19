from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
import re

import pandas as pd
import streamlit as st

from decision_context_special import (
    apply_bye_overlap_context,
    fetch_sleeper_player_context,
    load_team_bye_weeks,
    merge_live_context,
)
from fantasy_engine import LeagueConfig
from ranking_v3 import player_explanation, prepare_rankings, recommend_players


POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _cached_sleeper_context() -> pd.DataFrame:
    return fetch_sleeper_player_context()


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def _cached_bye_weeks(season: int) -> pd.DataFrame:
    return load_team_bye_weeks(int(season))


def _infer_season(players: pd.DataFrame) -> int:
    current = datetime.now().year
    years: list[int] = []
    if isinstance(players, pd.DataFrame) and "data_source" in players:
        for text in players["data_source"].fillna("").astype(str).head(150):
            years.extend(int(y) for y in re.findall(r"\b20\d{2}\b", text))
    plausible = [y for y in years if current - 1 <= y <= current + 1]
    return max(plausible) if plausible else current


def _market_text(value) -> str:
    return "—" if pd.isna(value) else f"{float(value):.1f}"


def _bye_text(value) -> str:
    return "—" if pd.isna(value) else f"Week {int(value)}"


def render_decision_center() -> None:
    st.title("🧭 DraftEdge Decision Center")
    st.caption(
        "Model Rank evaluates the player/unit. Market Rank shows external consensus. Pick Rank adds roster fit, timing, "
        "next-pick availability, live injury context, bye overlap, and K/DST draft strategy."
    )

    players = st.session_state.get("players")
    config = st.session_state.get("config")
    draft_log = st.session_state.get("draft_log", [])
    if players is None or not isinstance(players, pd.DataFrame) or players.empty:
        st.warning("No player pool is loaded in this browser session. Open the main DraftEdge page and load player data first.")
        return
    if not isinstance(config, LeagueConfig):
        try:
            raw = asdict(config) if is_dataclass(config) else dict(config or {})
        except Exception:
            raw = {}
        allowed = {f.name for f in fields(LeagueConfig)}
        config = LeagueConfig(**{k: v for k, v in raw.items() if k in allowed})
        st.session_state.config = config

    with st.expander("Decision settings", expanded=False):
        season = st.number_input("NFL season for bye weeks", 2024, 2030, int(_infer_season(players)), step=1)
        bye_mode = st.selectbox(
            "Bye-week overlap handling", ["Warn only", "Balanced", "Strict"], index=1,
            help="Bye overlap changes Pick Rank only, never the underlying Model Rank.",
        )
        st.caption(
            f"Configured starters: {config.qb} QB · {config.rb} RB · {config.wr} WR · {config.te} TE · "
            f"{config.flex} FLEX · {config.superflex} SUPERFLEX · {getattr(config, 'k', 1)} K · {getattr(config, 'dst', 1)} D/ST."
        )
        if st.button("Refresh live injury + schedule context"):
            _cached_sleeper_context.clear()
            _cached_bye_weeks.clear()
            st.rerun()

    bye_strength = {"Warn only": 0.0, "Balanced": 1.5, "Strict": 3.0}[bye_mode]
    ranked = prepare_rankings(players, config)
    current_pick = len(draft_log) + 1
    mc = st.session_state.get("mc_results")
    if not isinstance(mc, pd.DataFrame):
        mc = pd.DataFrame()
    base_recs = recommend_players(
        ranked, draft_log, config, int(config.user_slot), current_pick,
        top_n=max(150, len(ranked)), monte_carlo=mc,
    )

    injury_error = ""
    try:
        injury_context = _cached_sleeper_context()
    except Exception as exc:
        injury_context = pd.DataFrame()
        injury_error = str(exc)
    bye_error = ""
    try:
        bye_weeks = _cached_bye_weeks(int(season))
    except Exception as exc:
        bye_weeks = pd.DataFrame()
        bye_error = str(exc)

    recs = merge_live_context(base_recs, injury_context, bye_weeks)
    base_injury = recs.get("injury_status", pd.Series("", index=recs.index)).fillna("").astype(str).str.strip()
    live_injury = recs.get("live_injury_status", pd.Series("", index=recs.index)).fillna("").astype(str).str.strip()
    no_live = live_injury.eq("") & base_injury.ne("") & ~recs["position"].eq("DST")
    recs.loc[no_live, "injury_display"] = "🟡 " + base_injury.loc[no_live]
    recs.loc[no_live, "absence_estimate"] = "Current return timetable not available from the connected data source"

    recs, roster_byes = apply_bye_overlap_context(
        recs, draft_log, int(config.user_slot), bye_weeks, penalty_strength=bye_strength,
    )

    real_adp = int(pd.to_numeric(ranked["adp"], errors="coerce").notna().sum())
    current_proj = int((~ranked["projection_source"].astype(str).str.lower().str.contains("historical fallback|no current")).sum())
    special_count = int(ranked["position"].isin(["K", "DST"]).sum())
    injury_flags = int(
        recs["injury_display"].fillna("").astype(str).str.startswith(("🟡", "🔴")).sum()
    ) if "injury_display" in recs else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Current projections", current_proj)
    m2.metric("Players/units with ADP", real_adp)
    m3.metric("K + D/ST in pool", special_count)
    m4.metric("Current injury flags", injury_flags)

    if injury_error:
        st.warning(f"Live Sleeper injury metadata could not refresh: {injury_error}. Existing injury fields are still shown.")
    if bye_error or bye_weeks.empty:
        st.warning("Bye-week schedule data is unavailable; bye-overlap adjustment is temporarily disabled." + (f" ({bye_error})" if bye_error else ""))

    with st.expander("How K/DST are handled", expanded=False):
        st.markdown(
            "**Kickers and team defenses are fully ranked**, but their Model Score includes league-specific replacement value and "
            "a modest replaceability adjustment. **Pick Rank additionally discourages drafting K/DST too early** and strongly "
            "discourages a backup K/DST after the configured starter slot is filled. D/ST ranges are intentionally wider because "
            "weekly matchup variance is high.  \n\n"
            "For Footballguys raw projections, kicker points use converted/missed XPs and FGs. Team-defense points use sacks, "
            "interceptions, fumble recoveries, TDs, safeties, blocks and return TDs. If points-allowed tiers are enabled, the raw "
            "season PA total is converted to an **average-PA/game approximation**, because the export does not contain weekly PA outcomes."
        )

    st.subheader("Top available — decision view")
    f1, f2, f3, f4 = st.columns([1.25, 1.0, 1.0, 1.0])
    positions = f1.multiselect("Position", POSITIONS, default=POSITIONS)
    risk_filter = f2.selectbox("Risk", ["All", "Low + Moderate", "Low only"], index=0)
    conf_filter = f3.multiselect("Data confidence", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
    injury_filter = f4.selectbox("Injury", ["All", "No current flag", "Flagged only"], index=0)

    view = recs[recs["position"].isin(positions) & recs["data_confidence"].isin(conf_filter)].copy()
    if risk_filter == "Low + Moderate":
        view = view[view["risk_label"].isin(["Low", "Moderate"])]
    elif risk_filter == "Low only":
        view = view[view["risk_label"].eq("Low")]
    if injury_filter == "No current flag":
        view = view[~view["injury_display"].fillna("").astype(str).str.startswith(("🟡", "🔴"))]
    elif injury_filter == "Flagged only":
        view = view[view["injury_display"].fillna("").astype(str).str.startswith(("🟡", "🔴"))]

    if view.empty:
        st.info("No available players match these filters.")
        return

    decision = view.copy()
    decision["Market Rank"] = decision["market_rank"].round(1)
    decision["Model vs Market"] = decision["model_market_delta"].round(1)
    decision["Next-pick avail. %"] = (decision["p_available_next"] * 100).round(0)
    decision["Bye"] = decision["bye_week"].map(_bye_text)
    decision["Bye Conflict"] = decision.apply(
        lambda r: "—" if int(r.get("bye_overlap_count", 0) or 0) == 0 else f"⚠️ {int(r['bye_overlap_count'])}: {r.get('bye_conflict_players', '')}", axis=1
    )
    columns = [
        "pick_rank", "model_rank", "Market Rank", "Model vs Market", "player", "position", "team", "tier",
        "projection", "projection_range", "vor", "opportunity_score", "risk_label", "data_confidence",
        "injury_display", "absence_estimate", "Bye", "Bye Conflict", "Next-pick avail. %", "why",
    ]
    table = decision[columns].rename(columns={
        "pick_rank": "Pick Rank", "model_rank": "Model Rank", "player": "Player", "position": "Pos", "team": "Team",
        "tier": "Tier", "projection": "Proj", "projection_range": "Est. Range", "vor": "VOR",
        "opportunity_score": "Opportunity", "risk_label": "Risk", "data_confidence": "Confidence",
        "injury_display": "Current Injury", "absence_estimate": "Expected Availability", "why": "Why now",
    })
    st.dataframe(table.head(60), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Why is this player or unit ranked here?")
    selected_name = st.selectbox("Player / D/ST to explain", view["player"].tolist())
    selected = recs.loc[recs["player"].eq(selected_name)].iloc[0]

    a, b, c = st.columns([1.0, 1.1, 1.35])
    with a:
        image = str(selected.get("image_url") or "").strip()
        if image and selected["position"] != "DST":
            st.image(image, width=150)
        st.markdown(f"### {selected['player']}")
        st.caption(f"{selected['position']} · {selected['team']} · {selected['role']} · Tier {int(selected['tier'])}")
    with b:
        edge = selected.get("model_market_delta")
        st.metric("Pick Rank", int(selected["pick_rank"]))
        st.metric("Model Rank", int(selected["model_rank"]))
        st.metric("Market Rank", _market_text(selected.get("market_rank")), delta=(f"{float(edge):+.1f}" if pd.notna(edge) else None))
    with c:
        st.metric("Projection", f"{float(selected['projection']):.1f}")
        st.metric("Estimated range", str(selected["projection_range"]))
        st.metric("Positional advantage (VOR)", f"{float(selected['vor']):+.1f}")

    injury_text = str(selected.get("injury_display") or "🟢 No current injury flag")
    if injury_text.startswith("🔴"):
        st.error(f"**Current injury:** {injury_text}\n\n**Expected availability:** {selected.get('absence_estimate', 'Unknown')}")
    elif injury_text.startswith("🟡"):
        st.warning(f"**Current injury:** {injury_text}\n\n**Expected availability:** {selected.get('absence_estimate', 'Unknown')}")
    else:
        st.success(f"**Current injury:** {injury_text}")
    detail = str(selected.get("injury_detail") or "").strip()
    if detail:
        st.caption(detail)

    bye = selected.get("bye_week")
    overlap = int(selected.get("bye_overlap_count", 0) or 0)
    if pd.notna(bye):
        if overlap:
            st.warning(f"**Bye Week {int(bye)} conflict:** overlaps with {selected.get('bye_conflict_players', '')}.")
        else:
            st.info(f"**Bye Week {int(bye)}:** no overlap with your current roster.")

    x1, x2, x3, x4 = st.columns(4)
    x1.metric("Opportunity / unit strength", f"{float(selected['opportunity_score']):.0f}/100")
    x2.metric("Risk", str(selected["risk_label"]), f"{float(selected['risk_score']):.0f}/100")
    x3.metric("Data confidence", str(selected["data_confidence"]), f"{float(selected['data_confidence_score']):.0f}/100")
    x4.metric("Projection basis", str(selected["projection_source"]))

    expl = player_explanation(selected)
    l, r = st.columns(2)
    with l:
        st.markdown("**Why DraftEdge likes it**")
        for item in expl["strengths"]:
            st.write(f"✅ {item}")
    with r:
        st.markdown("**Why to be cautious**")
        for item in expl["cautions"]:
            st.write(f"⚠️ {item}")
        if overlap:
            st.write(f"⚠️ Bye Week {int(bye)} overlaps with {selected.get('bye_conflict_players', '')}")

    st.divider()
    st.subheader("Your roster bye-week map")
    if roster_byes.empty:
        st.caption("No roster bye-week map yet because your roster is empty or schedule data is unavailable.")
    else:
        summary = (
            roster_byes.groupby("bye_week", as_index=False)
            .agg(count=("player", "size"), players=("player", lambda s: ", ".join(s)))
            .sort_values(["count", "bye_week"], ascending=[False, True])
        )
        summary["status"] = summary["count"].map(lambda n: "⚠️ overlap" if int(n) >= 2 else "OK")
        st.dataframe(summary.rename(columns={"bye_week": "Bye Week", "count": "Players/units", "players": "Roster", "status": "Status"}), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Compare players / units")
    default_compare = recs.head(min(3, len(recs)))["player"].tolist()
    names = st.multiselect("Choose 2–4", recs["player"].tolist(), default=default_compare, max_selections=4)
    if len(names) >= 2:
        comp = recs[recs["player"].isin(names)].copy()
        comp["Market Rank"] = comp["market_rank"].round(1)
        comp["Next-pick avail. %"] = (comp["p_available_next"] * 100).round(0)
        comp["Bye"] = comp["bye_week"].map(_bye_text)
        st.dataframe(
            comp[[
                "player", "position", "pick_rank", "model_rank", "Market Rank", "projection", "projection_range", "vor",
                "risk_label", "data_confidence", "injury_display", "absence_estimate", "Bye", "Next-pick avail. %",
            ]].rename(columns={
                "player": "Player", "position": "Pos", "pick_rank": "Pick Rank", "model_rank": "Model Rank",
                "projection": "Proj", "projection_range": "Est. Range", "vor": "VOR", "risk_label": "Risk",
                "data_confidence": "Confidence", "injury_display": "Current Injury", "absence_estimate": "Expected Availability",
            }),
            use_container_width=True, hide_index=True,
        )

    st.caption(
        "Injury timelines are decision-support interpretations, not guaranteed return dates. D/ST has no unit-level injury designation. "
        "Bye penalties and K/DST timing affect Pick Rank only; they do not rewrite the underlying player/unit projection."
    )
