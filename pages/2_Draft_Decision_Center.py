from __future__ import annotations

import pandas as pd
import streamlit as st

from fantasy_engine import LeagueConfig
from ranking_v2_live import player_explanation, prepare_rankings, recommend_players


st.set_page_config(page_title="DraftEdge Decision Center", page_icon="🧭", layout="wide")

st.title("🧭 DraftEdge Decision Center")
st.caption(
    "Transparent player evaluation: Model Rank ≠ Market Rank ≠ Pick Rank. "
    "Use this page to understand why players are ordered the way they are."
)

players = st.session_state.get("players")
config = st.session_state.get("config")
draft_log = st.session_state.get("draft_log", [])

if players is None or not isinstance(players, pd.DataFrame) or players.empty:
    st.warning("No player pool is loaded in this browser session. Open the main DraftEdge page and load your player data first.")
    st.stop()
if not isinstance(config, LeagueConfig):
    config = LeagueConfig()

ranked = prepare_rankings(players, config)
current_pick = len(draft_log) + 1
mc_results = st.session_state.get("mc_results")
if not isinstance(mc_results, pd.DataFrame):
    mc_results = pd.DataFrame()
recs = recommend_players(
    ranked,
    draft_log,
    config,
    int(config.user_slot),
    current_pick,
    top_n=max(100, len(ranked)),
    monte_carlo=mc_results,
)

real_adp = int(pd.to_numeric(ranked["adp"], errors="coerce").notna().sum())
real_ecr = int(pd.to_numeric(ranked["ecr"], errors="coerce").notna().sum())
current_proj = int(ranked["projection_source"].ne("Historical fallback").sum())
historical_fallback = int(ranked["projection_source"].eq("Historical fallback").sum())
high_conf = int(ranked["data_confidence"].eq("High").sum())

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Current projections", current_proj)
m2.metric("Historical fallbacks", historical_fallback)
m3.metric("Players with ADP", real_adp)
m4.metric("Players with ECR", real_ecr)
m5.metric("High-confidence ranks", high_conf)

with st.expander("How to read these rankings", expanded=False):
    st.markdown(
        "**Model Rank** evaluates the player independent of your current roster. It combines projection, league-specific "
        "value over replacement, opportunity, real market consensus when available, depth-chart security, and risk.  \n\n"
        "**Market Rank** is the median of real ADP/ECR inputs. If those inputs are absent, it stays blank; DraftEdge does not "
        "invent a market rank.  \n\n"
        "**Pick Rank** is the recommendation for your current draft position. It adds roster fit, positional scarcity, "
        "estimated availability at your next pick, and Monte Carlo take-now/wait information when available.  \n\n"
        "**Est. Range** is a heuristic floor–ceiling range derived from projection provenance and risk. It is not a formal "
        "statistical prediction interval."
    )

st.subheader("Top available — decision view")
filter1, filter2, filter3 = st.columns([1.2, 1.0, 1.1])
positions = filter1.multiselect("Position", ["QB", "RB", "WR", "TE"], default=["QB", "RB", "WR", "TE"])
max_risk = filter2.selectbox("Risk", ["All", "Low + Moderate", "Low only"], index=0)
conf_filter = filter3.multiselect("Data confidence", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])

view = recs[recs["position"].isin(positions) & recs["data_confidence"].isin(conf_filter)].copy()
if max_risk == "Low + Moderate":
    view = view[view["risk_label"].isin(["Low", "Moderate"])]
elif max_risk == "Low only":
    view = view[view["risk_label"].eq("Low")]

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
    display_cols = [
        "pick_rank", "model_rank", "market_rank_display", "model_market_delta_display",
        "player", "position", "team", "tier", "projection_display", "projection_range",
        "vor_display", "opportunity_display", "risk_label", "data_confidence", "next_avail", "why",
    ]
    decision = decision[display_cols].rename(columns={
        "pick_rank": "Pick Rank", "model_rank": "Model Rank", "market_rank_display": "Market Rank",
        "model_market_delta_display": "Model vs Market", "player": "Player", "position": "Pos", "team": "Team",
        "tier": "Tier", "projection_display": "Proj", "projection_range": "Est. Range", "vor_display": "VOR",
        "opportunity_display": "Opportunity", "risk_label": "Risk", "data_confidence": "Confidence",
        "next_avail": "Next-pick avail. %", "why": "Why now",
    })
    st.dataframe(
        decision.head(50), use_container_width=True, hide_index=True,
        column_config={
            "Pick Rank": st.column_config.NumberColumn(help="Who DraftEdge recommends at this exact pick."),
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

left, center, right = st.columns([1.0, 1.2, 1.2])
with left:
    image = str(selected.get("image_url") or "").strip()
    if image:
        st.image(image, width=150)
    st.markdown(f"### {selected['player']}")
    st.caption(f"{selected['position']} · {selected['team']} · {selected['role']} · Tier {int(selected['tier'])}")

with center:
    market_text = "—" if pd.isna(selected.get("market_rank")) else f"{float(selected['market_rank']):.1f}"
    edge_text = "—" if pd.isna(selected.get("model_market_delta")) else f"{float(selected['model_market_delta']):+.1f}"
    st.metric("Pick Rank", int(selected["pick_rank"]))
    st.metric("Model Rank", int(selected["model_rank"]))
    st.metric("Market Rank", market_text, delta=edge_text if edge_text != "—" else None, help="Delta is Model vs Market; positive means DraftEdge is more bullish.")

with right:
    st.metric("Projection", f"{float(selected['projection']):.1f}")
    st.metric("Estimated range", str(selected["projection_range"]))
    st.metric("Positional advantage (VOR)", f"{float(selected['vor']):+.1f}")

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

st.caption(
    f"Availability estimate basis: **{selected.get('availability_basis', '—')}** · "
    f"Projection source: **{selected.get('projection_source', '—')}**"
)

st.divider()
st.subheader("Compare players")
compare_default = recs.head(min(3, len(recs)))["player"].tolist()
compare_names = st.multiselect("Choose 2–4 players", recs["player"].tolist(), default=compare_default, max_selections=4)
if len(compare_names) >= 2:
    comp = recs[recs["player"].isin(compare_names)].copy()
    comp["Market Rank"] = comp["market_rank"].round(1)
    comp["Model vs Market"] = comp["model_market_delta"].round(1)
    comp["Next-pick avail. %"] = (comp["p_available_next"] * 100).round(0)
    comp_table = comp[[
        "player", "pick_rank", "model_rank", "Market Rank", "Model vs Market", "projection", "projection_range",
        "vor", "opportunity_score", "risk_label", "data_confidence", "Next-pick avail. %",
    ]].rename(columns={
        "player": "Player", "pick_rank": "Pick Rank", "model_rank": "Model Rank", "projection": "Proj",
        "projection_range": "Est. Range", "vor": "VOR", "opportunity_score": "Opportunity",
        "risk_label": "Risk", "data_confidence": "Confidence",
    })
    st.dataframe(comp_table, use_container_width=True, hide_index=True)
else:
    st.caption("Select at least two players to compare them side by side.")

with st.expander("Raw ranking components / audit view", expanded=False):
    audit_cols = [
        "model_rank", "player", "position", "model_score", "projection", "historical_baseline", "projection_source",
        "projection_floor", "projection_ceiling", "vor", "opportunity_score", "usage_index", "depth_score",
        "risk_score", "market_rank", "adp", "ecr", "model_market_delta", "data_confidence_score", "data_source",
    ]
    st.dataframe(ranked[[c for c in audit_cols if c in ranked.columns]], use_container_width=True, hide_index=True)
