from __future__ import annotations

from datetime import datetime
import re

import pandas as pd
import streamlit as st

from decision_context import (
    apply_bye_overlap_context,
    fetch_sleeper_player_context,
    load_team_bye_weeks,
    merge_live_context,
)
from fantasy_engine import LeagueConfig
from ranking_v2_live import player_explanation, prepare_rankings, recommend_players


st.set_page_config(page_title="DraftEdge Decision Center", page_icon="🧭", layout="wide")


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _cached_sleeper_context() -> pd.DataFrame:
    return fetch_sleeper_player_context()


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def _cached_bye_weeks(season: int) -> pd.DataFrame:
    return load_team_bye_weeks(int(season))


def _infer_season(players: pd.DataFrame) -> int:
    current = datetime.now().year
    if players is None or players.empty or "data_source" not in players:
        return current
    years: list[int] = []
    for text in players["data_source"].fillna("").astype(str).head(100):
        years.extend(int(y) for y in re.findall(r"\b20\d{2}\b", text))
    plausible = [y for y in years if current - 1 <= y <= current + 1]
    return max(plausible) if plausible else current


def _market_text(value) -> str:
    return "—" if pd.isna(value) else f"{float(value):.1f}"


def _bye_text(value) -> str:
    return "—" if pd.isna(value) else f"Week {int(value)}"


st.title("🧭 DraftEdge Decision Center")
st.caption(
    "Model Rank evaluates the player. Market Rank shows external consensus. Pick Rank adds your roster, wait/availability, "
    "live injury context, and bye-week conflicts."
)

players = st.session_state.get("players")
config = st.session_state.get("config")
draft_log = st.session_state.get("draft_log", [])

if players is None or not isinstance(players, pd.DataFrame) or players.empty:
    st.warning("No player pool is loaded in this browser session. Open the main DraftEdge page and load your player data first.")
    st.stop()
if not isinstance(config, LeagueConfig):
    config = LeagueConfig()

with st.expander("Live context settings", expanded=False):
    default_season = _infer_season(players)
    schedule_season = st.number_input("NFL season for bye weeks", 2024, 2030, int(default_season), step=1)
    bye_mode = st.selectbox(
        "Bye-week overlap handling",
        ["Warn only", "Balanced", "Strict"],
        index=1,
        help=(
            "Bye weeks never change Model Rank. They only adjust Pick Rank. Balanced applies a modest penalty so a strong value "
            "can still be worth drafting despite one overlap."
        ),
    )
    if st.button("Refresh live injury + schedule context"):
        _cached_sleeper_context.clear()
        _cached_bye_weeks.clear()
        st.rerun()

bye_strength = {"Warn only": 0.0, "Balanced": 1.5, "Strict": 3.0}[bye_mode]

ranked = prepare_rankings(players, config)
current_pick = len(draft_log) + 1
mc_results = st.session_state.get("mc_results")
if not isinstance(mc_results, pd.DataFrame):
    mc_results = pd.DataFrame()

base_recs = recommend_players(
    ranked,
    draft_log,
    config,
    int(config.user_slot),
    current_pick,
    top_n=max(100, len(ranked)),
    monte_carlo=mc_results,
)

injury_context = pd.DataFrame()
injury_error = ""
try:
    injury_context = _cached_sleeper_context()
except Exception as exc:
    injury_error = str(exc)

bye_weeks = pd.DataFrame()
bye_error = ""
try:
    bye_weeks = _cached_bye_weeks(int(schedule_season))
except Exception as exc:
    bye_error = str(exc)

recs = merge_live_context(base_recs, injury_context, bye_weeks)
base_injury = recs.get("injury_status", pd.Series("", index=recs.index)).fillna("").astype(str).str.strip()
live_injury = recs.get("live_injury_status", pd.Series("", index=recs.index)).fillna("").astype(str).str.strip()
no_live = live_injury.eq("") & base_injury.ne("")
recs.loc[no_live, "injury_display"] = "🟡 " + base_injury.loc[no_live]
recs.loc[no_live, "absence_estimate"] = "Current return timetable not available from the connected data source"

recs, roster_byes = apply_bye_overlap_context(
    recs,
    draft_log,
    int(config.user_slot),
    bye_weeks,
    penalty_strength=bye_strength,
)

real_adp = int(pd.to_numeric(ranked["adp"], errors="coerce").notna().sum())
real_ecr = int(pd.to_numeric(ranked["ecr"], errors="coerce").notna().sum())
current_proj = int(ranked["projection_source"].ne("Historical fallback").sum())
high_conf = int(ranked["data_confidence"].eq("High").sum())
injury_flags = (
    int(recs["injury_display"].fillna("").astype(str).str.startswith(("🟡", "🔴")).sum())
    if "injury_display" in recs
    else 0
)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Current projections", current_proj)
m2.metric("Players with ADP", real_adp)
m3.metric("Players with ECR", real_ecr)
m4.metric("High-confidence ranks", high_conf)
m5.metric("Current injury flags", injury_flags)

if injury_error:
    st.warning(f"Live Sleeper injury metadata could not be refreshed: {injury_error}. Existing player-pool injury fields are still shown.")
if bye_error or bye_weeks.empty:
    st.warning(
        "Bye-week schedule data is unavailable, so Pick Rank is not currently applying bye-overlap adjustments."
        + (f" ({bye_error})" if bye_error else "")
    )

with st.expander("How to read the decision data", expanded=False):
    st.markdown(
        "**Model Rank** = player quality/value independent of your current roster.  \n"
        "**Market Rank** = real ADP/ECR consensus when available.  \n"
        "**Pick Rank** = what DraftEdge recommends at this exact pick after roster fit, scarcity, next-pick availability, "
        "Monte Carlo information, and the selected bye-overlap setting.  \n\n"
        "**Injury / expected availability** uses current Sleeper player metadata when available. Sleeper exposes injury status, "
        "injury start date and practice participation, but it does not guarantee a precise return date. DraftEdge therefore "
        "labels uncertain timelines instead of inventing a number of weeks.  \n\n"
        "**Bye overlap** is deliberately a soft Pick-Rank adjustment, not a change to Model Rank. One overlap can be acceptable "
        "when the player is a major value; repeated overlaps become more costly."
    )

st.subheader("Top available — decision view")
f1, f2, f3, f4 = st.columns([1.1, 1.0, 1.0, 1.0])
positions = f1.multiselect("Position", ["QB", "RB", "WR", "TE"], default=["QB", "RB", "WR", "TE"])
max_risk = f2.selectbox("Risk", ["All", "Low + Moderate", "Low only"], index=0)
conf_filter = f3.multiselect("Data confidence", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
injury_filter = f4.selectbox("Injury", ["All", "No current flag", "Flagged only"], index=0)

view = recs[recs["position"].isin(positions) & recs["data_confidence"].isin(conf_filter)].copy()
if max_risk == "Low + Moderate":
    view = view[view["risk_label"].isin(["Low", "Moderate"])]
elif max_risk == "Low only":
    view = view[view["risk_label"].eq("Low")]
if injury_filter == "No current flag":
    view = view[view["injury_display"].eq("🟢 No current injury flag")]
elif injury_filter == "Flagged only":
    view = view[~view["injury_display"].eq("🟢 No current injury flag")]

if view.empty:
    st.info("No available players match these filters.")
else:
    decision = view.copy()
    decision["market_rank_display"] = decision["market_rank"].round(1)
    decision["model_market_delta_display"] = decision["model_market_delta"].round(1)
    decision["next_avail"] = (decision["p_available_next"] * 100).round(0)
    decision["projection_display"] = decision["projection"].round(1)
    decision["vor_display"] = decision["vor"].round(1)
    decision["opportunity_display"] = decision["opportunity_score"].round(0)
    decision["bye_display"] = decision["bye_week"].map(_bye_text)
    decision["bye_conflict"] = decision.apply(
        lambda row: "—" if int(row.get("bye_overlap_count", 0)) == 0 else f"⚠️ {int(row['bye_overlap_count'])}: {row['bye_conflict_players']}",
        axis=1,
    )
    display_cols = [
        "pick_rank", "model_rank", "market_rank_display", "model_market_delta_display",
        "player", "position", "team", "tier", "projection_display", "projection_range",
        "vor_display", "opportunity_display", "risk_label", "data_confidence",
        "injury_display", "absence_estimate", "bye_display", "bye_conflict", "next_avail", "why",
    ]
    table = decision[display_cols].rename(columns={
        "pick_rank": "Pick Rank", "model_rank": "Model Rank", "market_rank_display": "Market Rank",
        "model_market_delta_display": "Model vs Market", "player": "Player", "position": "Pos", "team": "Team",
        "tier": "Tier", "projection_display": "Proj", "projection_range": "Est. Range", "vor_display": "VOR",
        "opportunity_display": "Opportunity", "risk_label": "Risk", "data_confidence": "Confidence",
        "injury_display": "Current Injury", "absence_estimate": "Expected Availability", "bye_display": "Bye",
        "bye_conflict": "Bye Conflict", "next_avail": "Next-pick avail. %", "why": "Why now",
    })
    st.dataframe(
        table.head(50), use_container_width=True, hide_index=True,
        column_config={
            "Pick Rank": st.column_config.NumberColumn(help="Current recommendation after roster/draft context and selected bye-overlap handling."),
            "Model Rank": st.column_config.NumberColumn(help="Player evaluation independent of your current roster."),
            "Market Rank": st.column_config.NumberColumn(format="%.1f", help="Median of real ADP/ECR; blank when unavailable."),
            "Model vs Market": st.column_config.NumberColumn(format="%+.1f", help="Positive = DraftEdge is more bullish than the market."),
            "Proj": st.column_config.NumberColumn(format="%.1f"),
            "VOR": st.column_config.NumberColumn(format="%+.1f", help="Projected points above league-specific replacement level."),
            "Opportunity": st.column_config.NumberColumn(format="%.0f", help="0–100 workload/opportunity score."),
            "Next-pick avail. %": st.column_config.NumberColumn(format="%.0f%%"),
        },
    )

st.divider()
st.subheader("Why is this player ranked here?")
available_names = view["player"].tolist() if not view.empty else recs["player"].tolist()
selected_name = st.selectbox("Player to explain", available_names)
selected = recs.loc[recs["player"].eq(selected_name)].iloc[0]

left, center, right = st.columns([1.0, 1.1, 1.35])
with left:
    image = str(selected.get("image_url") or "").strip()
    if image:
        st.image(image, width=150)
    st.markdown(f"### {selected['player']}")
    st.caption(f"{selected['position']} · {selected['team']} · {selected['role']} · Tier {int(selected['tier'])}")

with center:
    edge = selected.get("model_market_delta")
    st.metric("Pick Rank", int(selected["pick_rank"]))
    st.metric("Model Rank", int(selected["model_rank"]))
    st.metric(
        "Market Rank", _market_text(selected.get("market_rank")),
        delta=(f"{float(edge):+.1f}" if pd.notna(edge) else None),
        help="Delta is Model vs Market; positive means DraftEdge is more bullish.",
    )

with right:
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

injury_detail = str(selected.get("injury_detail") or "").strip()
injury_since = str(selected.get("injury_since") or "").strip()
if injury_detail or injury_since:
    detail = injury_detail
    if injury_since:
        detail = (detail + " · " if detail else "") + f"Flagged since: {injury_since}"
    st.caption(detail)

bye_week = selected.get("bye_week")
bye_overlap = int(selected.get("bye_overlap_count", 0) or 0)
if pd.notna(bye_week):
    if bye_overlap:
        st.warning(
            f"**Bye Week {int(bye_week)} conflict:** overlaps with {selected.get('bye_conflict_players', '')}. "
            f"Current Pick Rank includes a {float(selected.get('bye_penalty', 0)):.1f}-point bye-context penalty ({bye_mode})."
        )
    else:
        st.info(f"**Bye Week {int(bye_week)}:** no overlap with your current roster.")

x1, x2, x3, x4 = st.columns(4)
x1.metric("Opportunity", f"{float(selected['opportunity_score']):.0f}/100")
x2.metric("Risk", str(selected["risk_label"]), f"{float(selected['risk_score']):.0f}/100")
x3.metric("Data confidence", str(selected["data_confidence"]), f"{float(selected['data_confidence_score']):.0f}/100")
x4.metric("Projection basis", str(selected["projection_source"]))

explanation = player_explanation(selected)
strength_col, caution_col = st.columns(2)
with strength_col:
    st.markdown("**Why DraftEdge likes the player**")
    for item in explanation["strengths"]:
        st.write(f"✅ {item}")
with caution_col:
    st.markdown("**Why to be cautious**")
    for item in explanation["cautions"]:
        st.write(f"⚠️ {item}")
    if bye_overlap:
        st.write(f"⚠️ Bye Week {int(bye_week)} overlaps with {selected.get('bye_conflict_players', '')}")
    if not injury_text.startswith("🟢"):
        st.write(f"⚠️ {injury_text}: {selected.get('absence_estimate', 'timeline unknown')}")

st.caption(
    f"Availability estimate basis: **{selected.get('availability_basis', '—')}** · "
    f"Projection source: **{selected.get('projection_source', '—')}**"
)

st.divider()
st.subheader("Your roster bye-week map")
if roster_byes.empty:
    st.caption("No bye-week conflicts yet because your roster is empty or schedule data is unavailable.")
else:
    summary = (
        roster_byes.groupby("bye_week", as_index=False)
        .agg(count=("player", "size"), players=("player", lambda series: ", ".join(series)))
        .sort_values(["count", "bye_week"], ascending=[False, True])
    )
    summary["status"] = summary["count"].map(lambda count: "⚠️ overlap" if int(count) >= 2 else "OK")
    st.dataframe(summary.rename(columns={"bye_week": "Bye Week", "count": "Players", "players": "Roster", "status": "Status"}), use_container_width=True, hide_index=True)

st.divider()
st.subheader("Compare players")
compare_default = recs.head(min(3, len(recs)))["player"].tolist()
compare_names = st.multiselect("Choose 2–4 players", recs["player"].tolist(), default=compare_default, max_selections=4)
if len(compare_names) >= 2:
    comp = recs[recs["player"].isin(compare_names)].copy()
    comp["Market Rank"] = comp["market_rank"].round(1)
    comp["Model vs Market"] = comp["model_market_delta"].round(1)
    comp["Next-pick avail. %"] = (comp["p_available_next"] * 100).round(0)
    comp["Bye"] = comp["bye_week"].map(_bye_text)
    comp["Bye overlap"] = comp["bye_overlap_count"].astype(int)
    comp_table = comp[[
        "player", "pick_rank", "model_rank", "Market Rank", "Model vs Market", "projection", "projection_range",
        "vor", "opportunity_score", "risk_label", "data_confidence", "injury_display", "absence_estimate",
        "Bye", "Bye overlap", "Next-pick avail. %",
    ]].rename(columns={
        "player": "Player", "pick_rank": "Pick Rank", "model_rank": "Model Rank", "projection": "Proj",
        "projection_range": "Est. Range", "vor": "VOR", "opportunity_score": "Opportunity",
        "risk_label": "Risk", "data_confidence": "Confidence", "injury_display": "Current Injury",
        "absence_estimate": "Expected Availability",
    })
    st.dataframe(comp_table, use_container_width=True, hide_index=True)

st.caption(
    "Injury timelines are decision-support interpretations of available metadata, not medical diagnoses or guaranteed return dates. "
    "Bye-week penalties affect Pick Rank only; they do not change the underlying Model Rank."
)
