from __future__ import annotations

"""Transparent DraftEdge Ranking v2.

This module is intentionally layered on top of the existing fantasy engine so
legacy draft mechanics remain compatible while player evaluation becomes more
transparent. It separates model rank, market rank, projection provenance,
risk/opportunity, and current-pick recommendation rank.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

import fantasy_engine as _legacy


LEGACY_NORMALIZE = _legacy.normalize_player_data
LEGACY_SCORE_POINTS = _legacy.score_fantasy_points
LEGACY_ASSIGN_ROLE = _legacy.assign_role
LEGACY_ROSTER_COUNTS = _legacy.roster_counts
LEGACY_ROSTER_NEED_FACTOR = _legacy.roster_need_factor
LEGACY_NEXT_PICK_FOR_SLOT = _legacy.next_pick_for_slot
LEGACY_AVAILABILITY_PROBABILITY = _legacy.availability_probability


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _minmax(series: pd.Series) -> pd.Series:
    s = _num(series)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    valid = s.notna()
    if not valid.any():
        return out
    lo = float(s[valid].min())
    hi = float(s[valid].max())
    if hi <= lo:
        out.loc[valid] = 50.0
        return out
    out.loc[valid] = (s.loc[valid] - lo) / (hi - lo) * 100.0
    return out


def _health_score(status: str) -> float:
    s = str(status or "").lower()
    if any(x in s for x in ["ir", "injured reserve", "pup", "out"]):
        return 25.0
    if "doubt" in s:
        return 45.0
    if "question" in s:
        return 70.0
    if "prob" in s:
        return 85.0
    return 100.0


def _age_risk(position: str, age: float) -> float:
    pos = str(position or "").upper()
    a = float(age or 0)
    thresholds = {"RB": (27.0, 7.0), "WR": (29.0, 5.0), "TE": (30.0, 4.0), "QB": (35.0, 3.0)}
    threshold, per_year = thresholds.get(pos, (30.0, 4.0))
    return float(min(32.0, max(0.0, a - threshold) * per_year))


def _risk_label(score: float) -> str:
    if score >= 55:
        return "High"
    if score >= 30:
        return "Moderate"
    return "Low"


def _confidence_label(score: float) -> str:
    if score >= 75:
        return "High"
    if score >= 50:
        return "Medium"
    return "Low"


def _projection_source(df: pd.DataFrame, supplied: pd.Series) -> pd.Series:
    source_text = df["data_source"].fillna("").astype(str).str.lower()
    labels = pd.Series("Historical fallback", index=df.index, dtype=object)
    labels.loc[supplied] = "Current / uploaded projection"
    labels.loc[supplied & source_text.str.contains("blended projection", regex=False)] = "Blended projections"
    return labels


def _weighted_component_score(components: dict[str, tuple[pd.Series, float]], index: pd.Index) -> pd.Series:
    numerator = pd.Series(0.0, index=index)
    denominator = pd.Series(0.0, index=index)
    for series, weight in components.values():
        values = _num(series)
        valid = values.notna()
        numerator.loc[valid] += values.loc[valid] * float(weight)
        denominator.loc[valid] += float(weight)
    return numerator / denominator.replace(0, np.nan)


def prepare_rankings(players: pd.DataFrame, config: _legacy.LeagueConfig) -> pd.DataFrame:
    """Build transparent model rankings without inventing missing ADP/ECR."""
    df = LEGACY_NORMALIZE(players)
    if df.empty:
        return df

    calculated = LEGACY_SCORE_POINTS(df, config)
    historical_points = df["fantasy_points"].where(df["fantasy_points"].notna(), calculated)
    games_for_rate = _num(df["games"]).replace(0, np.nan).fillna(17).clip(lower=1, upper=17)
    historical_ppg = historical_points.fillna(0) / games_for_rate
    annualized = historical_ppg * 17

    pos_median_annualized = annualized.where(annualized.gt(0)).groupby(df["position"]).transform("median")
    defaults = df["position"].map({"QB": 230.0, "RB": 130.0, "WR": 135.0, "TE": 105.0}).astype(float)
    baseline_center = pos_median_annualized.fillna(defaults)
    sample_weight = (_num(df["games"]).clip(lower=0, upper=17) / 17.0).clip(lower=0.30, upper=1.0)
    historical_baseline = annualized.where(annualized.gt(0), baseline_center * 0.65)
    historical_baseline = historical_baseline * sample_weight + baseline_center * (1.0 - sample_weight)

    supplied_projection = _num(df["projection"]).gt(0)
    current_projection = _num(df["projection"])
    projection = current_projection.where(supplied_projection, historical_baseline)

    df["historical_baseline"] = historical_baseline.round(2)
    df["projection"] = projection.round(2)
    df["projection_source"] = _projection_source(df, supplied_projection)
    df["fantasy_ppg"] = historical_ppg.round(2)
    df["role"] = df.apply(LEGACY_ASSIGN_ROLE, axis=1)
    df["health_score"] = df["injury_status"].map(_health_score)

    demand = {
        "QB": max(1, int(round(config.teams * (config.qb + 0.78 * config.superflex)))),
        "RB": max(1, int(round(config.teams * (config.rb + 0.42 * config.flex + 0.05 * config.superflex)))),
        "WR": max(1, int(round(config.teams * (config.wr + 0.48 * config.flex + 0.05 * config.superflex)))),
        "TE": max(1, int(round(config.teams * (config.te + 0.10 * config.flex + 0.02 * config.superflex)))),
    }
    replacement: dict[str, float] = {}
    for pos, grp in df.groupby("position"):
        vals = _num(grp["projection"]).dropna().sort_values(ascending=False).reset_index(drop=True)
        idx = min(max(demand.get(pos, 1) - 1, 0), len(vals) - 1) if len(vals) else 0
        replacement[pos] = float(vals.iloc[idx]) if len(vals) else 0.0
    df["replacement_points"] = df["position"].map(replacement).fillna(0.0)
    df["vor"] = df["projection"] - df["replacement_points"]

    g = games_for_rate
    usage_raw = pd.Series(0.0, index=df.index)
    usage_raw += (_num(df["rushing_attempts"]).fillna(0) / g) * df["position"].eq("RB") * 1.4
    usage_raw += (_num(df["targets"]).fillna(0) / g) * df["position"].isin(["RB", "WR", "TE"]) * 2.0
    usage_raw += (_num(df["passing_yards"]).fillna(0) / g / 25.0) * df["position"].eq("QB")
    df["usage_index"] = _minmax(usage_raw).fillna(50.0)

    depth = _num(df["depth_chart_order"])
    df["depth_score"] = (100 - (depth.fillna(2.5) - 1).clip(lower=0) * 18).clip(lower=20, upper=100)
    role_bonus = df["role"].str.contains("Alpha|Workhorse|Dual-Threat|Elite Target", regex=True, na=False).astype(float) * 10.0
    df["opportunity_score"] = (
        0.65 * df["usage_index"] + 0.25 * df["depth_score"] + 0.10 * (70.0 + role_bonus)
    ).clip(0, 100).round(1)

    availability_risk = ((17.0 - _num(df["games"]).clip(lower=0, upper=17)) / 17.0 * 25.0).fillna(12.0)
    age_risk = pd.Series(
        [_age_risk(pos, age) for pos, age in zip(df["position"], _num(df["age"]).fillna(26))],
        index=df.index,
    )
    health_risk = (100.0 - df["health_score"]) * 0.35
    source_risk = np.where(supplied_projection, 0.0, 12.0)
    depth_risk = np.where(depth.isna(), 5.0, ((depth.fillna(1) - 1).clip(lower=0) * 5.0).clip(upper=12.0))
    df["risk_score"] = (health_risk + age_risk + availability_risk + source_risk + depth_risk).clip(0, 100).round(1)
    df["risk_label"] = df["risk_score"].map(_risk_label)

    base_spread = pd.Series(np.where(supplied_projection, 0.11, 0.19), index=df.index, dtype=float)
    spread = (base_spread + df["risk_score"] / 500.0).clip(lower=0.10, upper=0.36)
    df["projection_floor"] = (df["projection"] * (1.0 - spread)).round(1)
    df["projection_ceiling"] = (df["projection"] * (1.0 + spread * 1.10)).round(1)
    df["projection_range"] = df.apply(lambda r: f"{r['projection_floor']:.0f}–{r['projection_ceiling']:.0f}", axis=1)
    df["floor_score"] = _minmax(df["projection_floor"]).fillna(50.0)
    df["upside_score"] = _minmax(df["projection_ceiling"]).fillna(50.0)

    adp = _num(df["adp"])
    ecr = _num(df["ecr"])
    df["market_data_points"] = adp.notna().astype(int) + ecr.notna().astype(int)
    df["market_rank"] = pd.concat([adp, ecr], axis=1).median(axis=1, skipna=True)
    df.loc[df["market_data_points"].eq(0), "market_rank"] = np.nan
    df["market_score"] = _minmax(-df["market_rank"])

    source_text = df["data_source"].fillna("").astype(str).str.lower()
    projection_points = pd.Series(np.where(supplied_projection, 35.0, 15.0), index=df.index)
    projection_points.loc[source_text.str.contains("blended projection", regex=False)] = 42.0
    market_points = df["market_data_points"] * 10.0
    sample_points = (_num(df["games"]).clip(lower=0, upper=17).fillna(0) / 17.0 * 20.0)
    depth_points = depth.notna().astype(float) * 8.0
    source_points = source_text.ne("").astype(float) * 10.0
    df["data_confidence_score"] = (projection_points + market_points + sample_points + depth_points + source_points).clip(0, 100).round(0)
    df["data_confidence"] = df["data_confidence_score"].map(_confidence_label)
    df["projection_confidence"] = df["data_confidence"]

    components = {
        "projection": (_minmax(df["projection"]), 0.30),
        "vor": (_minmax(df["vor"]), 0.25),
        "opportunity": (df["opportunity_score"], 0.15),
        "market": (df["market_score"], 0.15),
        "depth": (df["depth_score"], 0.05),
        "durability": (100.0 - df["risk_score"], 0.10),
    }
    df["model_score"] = _weighted_component_score(components, df.index).fillna(50.0).round(1)
    df["draft_value"] = df["model_score"]
    df["model_rank"] = df["model_score"].rank(method="first", ascending=False).astype(int)
    df["overall_rank"] = df["model_rank"]
    df["position_rank"] = df.groupby("position")["model_score"].rank(method="first", ascending=False).astype(int)
    df["model_market_delta"] = (df["market_rank"] - df["model_rank"]).round(1)

    df["market_reference"] = adp.where(adp.notna(), ecr).where(lambda s: s.notna(), df["model_rank"].astype(float))
    df["market_reference_source"] = np.select(
        [adp.notna(), adp.isna() & ecr.notna()], ["ADP", "ECR"], default="Model fallback"
    )

    tiers = pd.Series(index=df.index, dtype=int)
    for pos, grp in df.groupby("position"):
        g2 = grp.sort_values("model_score", ascending=False)
        tier = 1
        anchor: float | None = None
        count_in_tier = 0
        for idx, row in g2.iterrows():
            score = float(row["model_score"])
            if anchor is not None and count_in_tier >= 3 and anchor - score >= 4.5:
                tier += 1
                anchor = score
                count_in_tier = 0
            elif anchor is None:
                anchor = score
            tiers.loc[idx] = tier
            count_in_tier += 1
    df["tier"] = tiers.astype(int)

    return df.sort_values(["model_score", "projection"], ascending=False).reset_index(drop=True)


def recommend_players(
    ranked: pd.DataFrame,
    draft_log: List[dict],
    config: _legacy.LeagueConfig,
    user_slot: int,
    current_pick: int,
    top_n: int = 50,
    monte_carlo: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    drafted_ids = {str(p.get("player_id")) for p in draft_log}
    avail = ranked[~ranked["player_id"].astype(str).isin(drafted_ids)].copy()
    if avail.empty:
        return avail

    counts = LEGACY_ROSTER_COUNTS(draft_log, user_slot)
    next_user_pick = LEGACY_NEXT_PICK_FOR_SLOT(current_pick + 1, config.teams, config.rounds, user_slot)
    avail["roster_fit"] = avail["position"].map(lambda p: LEGACY_ROSTER_NEED_FACTOR(p, counts, config))
    market_ref = _num(avail.get("market_reference", avail.get("overall_rank")))
    avail["p_available_next"] = market_ref.map(lambda a: LEGACY_AVAILABILITY_PROBABILITY(a, next_user_pick))
    avail["availability_basis"] = avail.get("market_reference_source", "Model fallback")

    if monte_carlo is not None and isinstance(monte_carlo, pd.DataFrame) and not monte_carlo.empty:
        mc_cols = [c for c in ["player_id", "mc_p_available_next", "wait_value", "take_now_edge", "fallback_if_gone"] if c in monte_carlo.columns]
        avail = avail.merge(monte_carlo[mc_cols], on="player_id", how="left")
        if "mc_p_available_next" in avail.columns:
            use_mc = avail["mc_p_available_next"].notna()
            avail.loc[use_mc, "p_available_next"] = avail.loc[use_mc, "mc_p_available_next"]
            avail.loc[use_mc, "availability_basis"] = "Monte Carlo"
    for col, default in [("mc_p_available_next", np.nan), ("wait_value", np.nan), ("take_now_edge", np.nan), ("fallback_if_gone", "")]:
        if col not in avail.columns:
            avail[col] = default

    avail["urgency"] = 1.0 - avail["p_available_next"]
    pos_remaining = avail.groupby("position")["model_score"].transform("count")
    pos_top = avail.groupby("position")["model_score"].transform("max")
    scarcity_raw = (pos_top - avail["model_score"]).abs() + 100 / pos_remaining.clip(lower=1)
    sf_qb_bonus = avail["position"].eq("QB").astype(float) * config.superflex * 8.0
    avail["scarcity_score"] = _minmax(avail["vor"] + scarcity_raw + sf_qb_bonus).fillna(50.0)

    risk_penalty = avail["risk_score"].fillna(30.0) * 0.025
    avail["recommendation_score"] = (
        avail["model_score"] * avail["roster_fit"]
        + 7.0 * avail["urgency"]
        + 0.06 * avail["scarcity_score"]
        - risk_penalty
    )
    avail["recommendation_score"] += avail["take_now_edge"].fillna(0).clip(-5, 8) * 0.20
    avail["recommendation_score"] = avail["recommendation_score"].round(2)

    avail["why"] = avail.apply(_recommendation_reason, axis=1)
    avail = avail.sort_values(["recommendation_score", "model_score"], ascending=False).reset_index(drop=True)
    avail["pick_rank"] = np.arange(1, len(avail) + 1)
    return avail.head(top_n).reset_index(drop=True)


def _recommendation_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    if float(row.get("roster_fit", 1.0)) >= 1.10:
        reasons.append("fills a starter/SF need")
    if float(row.get("urgency", 0.0)) >= 0.70:
        reasons.append("unlikely to reach your next pick")
    take_now = row.get("take_now_edge")
    if pd.notna(take_now) and float(take_now) >= 3:
        reasons.append("Monte Carlo favors taking now")
    edge = row.get("model_market_delta")
    if pd.notna(edge) and float(edge) >= 6:
        reasons.append(f"model is {int(round(float(edge)))} spots above market")
    if float(row.get("vor", 0.0)) > 20:
        reasons.append("strong positional advantage")
    if float(row.get("opportunity_score", 50.0)) >= 80:
        reasons.append("elite opportunity profile")
    if str(row.get("risk_label", "")) == "High":
        reasons.append("high risk / wider outcome range")
    if str(row.get("data_confidence", "")) == "Low":
        reasons.append("low data confidence")
    if not reasons:
        reasons.append("balanced model value")
    return "; ".join(reasons[:3])


def simulate_opponent_pick(
    ranked: pd.DataFrame,
    draft_log: List[dict],
    config: _legacy.LeagueConfig,
    slot: int,
    current_pick: int,
) -> Optional[pd.Series]:
    drafted_ids = {str(p.get("player_id")) for p in draft_log}
    avail = ranked[~ranked["player_id"].astype(str).isin(drafted_ids)].copy()
    if avail.empty:
        return None
    counts = LEGACY_ROSTER_COUNTS(draft_log, slot)
    avail["fit"] = avail["position"].map(lambda p: LEGACY_ROSTER_NEED_FACTOR(p, counts, config))
    market_ref = _num(avail.get("market_reference", avail["overall_rank"])).fillna(avail["overall_rank"])
    avail["adp_pull"] = np.exp(-np.abs(market_ref - current_pick) / 18.0)
    avail["sim_score"] = avail["model_score"] * avail["fit"] + 8 * avail["adp_pull"]
    return avail.sort_values("sim_score", ascending=False).iloc[0]


def player_explanation(row: pd.Series) -> dict[str, list[str]]:
    strengths: list[str] = []
    cautions: list[str] = []

    if float(row.get("vor", 0)) >= 20:
        strengths.append(f"Strong positional advantage: +{float(row['vor']):.0f} points over replacement")
    if float(row.get("opportunity_score", 0)) >= 80:
        strengths.append(f"Elite opportunity score ({float(row['opportunity_score']):.0f}/100)")
    edge = row.get("model_market_delta")
    if pd.notna(edge) and float(edge) >= 5:
        strengths.append(f"DraftEdge is {float(edge):.0f} ranking spots more bullish than the market")
    if str(row.get("data_confidence", "")) == "High":
        strengths.append("High data confidence")
    if float(row.get("upside_score", 0)) >= 78:
        strengths.append("High estimated ceiling")

    if str(row.get("projection_source", "")) == "Historical fallback":
        cautions.append("Projection is a regressed historical baseline, not a current preseason projection")
    if str(row.get("risk_label", "")) == "High":
        cautions.append(f"High risk score ({float(row.get('risk_score', 0)):.0f}/100)")
    elif str(row.get("risk_label", "")) == "Moderate":
        cautions.append(f"Moderate risk ({float(row.get('risk_score', 0)):.0f}/100)")
    if pd.isna(row.get("market_rank")):
        cautions.append("No real ADP/ECR market rank available")
    elif pd.notna(edge) and float(edge) <= -5:
        cautions.append(f"Market is {abs(float(edge)):.0f} spots more bullish than DraftEdge")
    if str(row.get("data_confidence", "")) == "Low":
        cautions.append("Low data confidence; treat the rank as provisional")

    if not strengths:
        strengths.append("Balanced profile without one dominant model advantage")
    if not cautions:
        cautions.append("No major model caution detected from the available data")
    return {"strengths": strengths[:4], "cautions": cautions[:4]}
