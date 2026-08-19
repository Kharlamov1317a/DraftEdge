from __future__ import annotations

"""DraftEdge Ranking v3 with kicker and D/ST valuation."""

from typing import Optional

import numpy as np
import pandas as pd

import fantasy_engine as engine
from special_teams_support import apply_special_teams_support, normalize_position

apply_special_teams_support(engine)

import ranking_v2_live as _base  # noqa: E402

player_explanation_base = _base.player_explanation


def _num(values) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")


def _minmax(values: pd.Series) -> pd.Series:
    s = _num(values)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    valid = s.notna()
    if not valid.any():
        return out
    lo, hi = float(s[valid].min()), float(s[valid].max())
    if hi <= lo:
        out.loc[valid] = 50.0
    else:
        out.loc[valid] = (s.loc[valid] - lo) / (hi - lo) * 100.0
    return out


def _weighted(components: dict[str, tuple[pd.Series, float]], index: pd.Index) -> pd.Series:
    numerator = pd.Series(0.0, index=index, dtype=float)
    denominator = pd.Series(0.0, index=index, dtype=float)
    for values, weight in components.values():
        v = _num(values)
        ok = v.notna()
        numerator.loc[ok] += v.loc[ok] * float(weight)
        denominator.loc[ok] += float(weight)
    return numerator / denominator.replace(0, np.nan)


def _rebuild_tiers(df: pd.DataFrame) -> pd.Series:
    tiers = pd.Series(index=df.index, dtype=int)
    for pos, grp in df.groupby("position"):
        ordered = grp.sort_values("model_score", ascending=False)
        tier = 1
        anchor = None
        count = 0
        threshold = 3.0 if pos in {"K", "DST"} else 4.5
        min_count = 4 if pos in {"K", "DST"} else 3
        for idx, row in ordered.iterrows():
            score = float(row["model_score"])
            if anchor is not None and count >= min_count and anchor - score >= threshold:
                tier += 1
                anchor = score
                count = 0
            elif anchor is None:
                anchor = score
            tiers.loc[idx] = tier
            count += 1
    return tiers.fillna(1).astype(int)


def _special_replacement(df: pd.DataFrame, config) -> None:
    for pos, slots in [("K", int(getattr(config, "k", 1))), ("DST", int(getattr(config, "dst", 1)))]:
        mask = df["position"].eq(pos)
        if not mask.any():
            continue
        vals = _num(df.loc[mask, "projection"]).dropna().sort_values(ascending=False).reset_index(drop=True)
        demand = max(1, int(config.teams) * max(slots, 1))
        idx = min(demand - 1, len(vals) - 1) if len(vals) else 0
        repl = float(vals.iloc[idx]) if len(vals) else 0.0
        df.loc[mask, "replacement_points"] = repl
        df.loc[mask, "vor"] = _num(df.loc[mask, "projection"]) - repl


def _patch_special_profiles(df: pd.DataFrame, config) -> None:
    defaults = {"K": 118.0, "DST": 105.0}
    for pos in ["K", "DST"]:
        mask = df["position"].eq(pos)
        if not mask.any():
            continue
        projections = _num(df.loc[mask, "projection"])
        valid = projections[projections.gt(0)]
        fallback = float(valid.median()) if len(valid) else defaults[pos]
        missing = mask & (_num(df["projection"]).isna() | _num(df["projection"]).le(0))
        if missing.any():
            df.loc[missing, "projection"] = fallback
            df.loc[missing, "projection_source"] = "Historical fallback / no current special-teams projection"

        pos_proj = _num(df.loc[mask, "projection"])
        pct = pos_proj.rank(method="average", pct=True) * 100.0
        if pos == "K":
            df.loc[mask, "opportunity_score"] = (38.0 + 0.42 * pct).clip(38, 80).to_numpy()
            age = _num(df.loc[mask, "age"]).fillna(30.0)
            age_risk = ((age - 38).clip(lower=0) * 2.0).clip(upper=12)
            health = 100.0 - _num(df.loc[mask, "health_score"]).fillna(100.0)
            fallback_risk = df.loc[mask, "projection_source"].astype(str).str.contains("fallback", case=False).astype(float) * 10.0
            risk = (8.0 + age_risk + health * 0.35 + fallback_risk).clip(0, 60)
            df.loc[mask, "risk_score"] = risk.to_numpy()
            spread = (0.12 + risk / 700.0).clip(0.12, 0.22)
            df.loc[mask, "projection_floor"] = (pos_proj * (1 - spread)).round(1).to_numpy()
            df.loc[mask, "projection_ceiling"] = (pos_proj * (1 + spread)).round(1).to_numpy()
        else:
            df.loc[mask, "opportunity_score"] = (32.0 + 0.40 * pct).clip(32, 74).to_numpy()
            fallback_risk = df.loc[mask, "projection_source"].astype(str).str.contains("fallback", case=False).astype(float) * 12.0
            risk = (24.0 + fallback_risk).clip(20, 55)
            df.loc[mask, "risk_score"] = risk.to_numpy()
            spread = (0.22 + risk / 650.0).clip(0.22, 0.34)
            df.loc[mask, "projection_floor"] = (pos_proj * (1 - spread)).round(1).to_numpy()
            df.loc[mask, "projection_ceiling"] = (pos_proj * (1 + spread)).round(1).to_numpy()

        df.loc[mask, "risk_label"] = np.select(
            [df.loc[mask, "risk_score"].ge(55), df.loc[mask, "risk_score"].ge(30)],
            ["High", "Moderate"],
            default="Low",
        )
        df.loc[mask, "projection_range"] = df.loc[mask].apply(
            lambda r: f"{float(r['projection_floor']):.0f}–{float(r['projection_ceiling']):.0f}", axis=1
        )
        df.loc[mask, "depth_score"] = 65.0 if pos == "K" else 60.0
        df.loc[mask, "role"] = "Kicker" if pos == "K" else "Team Defense / Special Teams"

    df["floor_score"] = _minmax(df["projection_floor"]).fillna(50.0)
    df["upside_score"] = _minmax(df["projection_ceiling"]).fillna(50.0)


def _recompute_model(df: pd.DataFrame) -> None:
    projection_component = _minmax(df["projection"])
    vor_component = _minmax(df["vor"])
    durability = 100.0 - _num(df["risk_score"])
    current_projection = ~df["projection_source"].astype(str).str.lower().str.contains("historical fallback|no current")

    current_components = {
        "projection": (projection_component, 0.32),
        "vor": (vor_component, 0.24),
        "opportunity": (df["opportunity_score"], 0.14),
        "market": (df["market_score"], 0.12),
        "depth": (df["depth_score"], 0.05),
        "durability": (durability, 0.13),
    }
    fallback_components = {
        "projection": (projection_component, 0.18),
        "vor": (vor_component, 0.15),
        "opportunity": (df["opportunity_score"], 0.12),
        "market": (df["market_score"], 0.35),
        "depth": (df["depth_score"], 0.05),
        "durability": (durability, 0.15),
    }
    score_current = _weighted(current_components, df.index)
    score_fallback = _weighted(fallback_components, df.index)
    score = score_current.where(current_projection, score_fallback).fillna(50.0)
    score -= df["position"].map({"K": 3.0, "DST": 5.0}).fillna(0.0)
    df["model_score"] = score.clip(0, 100).round(1)
    df["draft_value"] = df["model_score"]
    df["model_rank"] = df["model_score"].rank(method="first", ascending=False).astype(int)
    df["overall_rank"] = df["model_rank"]
    df["position_rank"] = df.groupby("position")["model_score"].rank(method="first", ascending=False).astype(int)
    df["model_market_delta"] = (_num(df["market_rank"]) - df["model_rank"]).round(1)

    adp = _num(df["adp"])
    ecr = _num(df["ecr"])
    df["market_reference"] = adp.where(adp.notna(), ecr).where(lambda s: s.notna(), df["model_rank"].astype(float))
    df["market_reference_source"] = np.select(
        [adp.notna(), adp.isna() & ecr.notna()], ["ADP", "ECR"], default="Model fallback"
    )
    df["tier"] = _rebuild_tiers(df)


def prepare_rankings(players: pd.DataFrame, config) -> pd.DataFrame:
    df = _base.prepare_rankings(players, config).copy()
    if df.empty:
        return df
    df["position"] = df["position"].map(normalize_position)
    _patch_special_profiles(df, config)
    _special_replacement(df, config)
    _recompute_model(df)
    return df.sort_values(["model_score", "projection"], ascending=False).reset_index(drop=True)


def _special_timing_adjustment(position: str, counts: dict[str, int], config, current_pick: int) -> tuple[float, str]:
    pos = normalize_position(position)
    if pos not in {"K", "DST"}:
        return 0.0, ""
    required = int(getattr(config, "k" if pos == "K" else "dst", 1))
    owned = int(counts.get(pos, 0))
    round_no = ((int(current_pick) - 1) // max(int(config.teams), 1)) + 1
    final_window = max(1, int(config.rounds) - 4)

    if required <= 0:
        return -45.0, f"{pos} is not a configured starter"
    if owned >= required:
        return -24.0, f"{pos} starter slot already filled"
    if round_no < final_window:
        distance = final_window - round_no
        penalty = -(7.0 + min(18.0, distance * 2.6))
        label = "Kicker can usually wait" if pos == "K" else "D/ST is highly streamable and can usually wait"
        return penalty, label

    rounds_left = max(0, int(config.rounds) - round_no)
    bonus = max(0.0, 3.5 - 0.7 * rounds_left)
    return bonus, f"fills your remaining {pos} starter slot in the late-draft window"


def recommend_players(
    ranked: pd.DataFrame,
    draft_log: list[dict],
    config,
    user_slot: int,
    current_pick: int,
    top_n: int = 50,
    monte_carlo: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    recs = _base.recommend_players(
        ranked, draft_log, config, user_slot, current_pick,
        top_n=max(top_n, len(ranked)), monte_carlo=monte_carlo,
    ).copy()
    if recs.empty:
        return recs

    counts = engine.roster_counts(draft_log, user_slot)
    adjustments = recs["position"].map(lambda p: _special_timing_adjustment(p, counts, config, current_pick))
    recs["special_teams_adjustment"] = adjustments.map(lambda x: float(x[0]))
    recs["special_teams_context"] = adjustments.map(lambda x: str(x[1]))
    recs["recommendation_score"] = (
        _num(recs["recommendation_score"]).fillna(0.0) + recs["special_teams_adjustment"]
    ).round(2)

    special_mask = recs["position"].isin(["K", "DST"]) & recs["special_teams_context"].ne("")
    recs.loc[special_mask, "why"] = recs.loc[special_mask].apply(
        lambda r: f"{r['special_teams_context']}; {r.get('why', '')}".strip("; "), axis=1
    )
    recs = recs.sort_values(["recommendation_score", "model_score"], ascending=False).reset_index(drop=True)
    recs["pick_rank"] = np.arange(1, len(recs) + 1)
    return recs.head(top_n).reset_index(drop=True)


def simulate_opponent_pick(ranked: pd.DataFrame, draft_log: list[dict], config, slot: int, current_pick: int):
    drafted = {str(p.get("player_id")) for p in draft_log}
    avail = ranked[~ranked["player_id"].astype(str).isin(drafted)].copy()
    if avail.empty:
        return None
    counts = engine.roster_counts(draft_log, slot)
    avail["fit"] = avail["position"].map(lambda p: engine.roster_need_factor(p, counts, config))
    adp = _num(avail["adp"]).where(_num(avail["adp"]).notna(), _num(avail["market_reference"]))
    adp = adp.where(adp.notna(), _num(avail["model_rank"]))
    avail["adp_pull"] = np.exp(-np.abs(adp - float(current_pick)) / 18.0)
    avail["special_adj"] = avail["position"].map(lambda p: _special_timing_adjustment(p, counts, config, current_pick)[0])
    avail["sim_score"] = avail["model_score"] * avail["fit"] + 8.0 * avail["adp_pull"] + avail["special_adj"]
    return avail.sort_values(["sim_score", "model_score"], ascending=False).iloc[0]


def player_explanation(row: pd.Series) -> dict[str, list[str]]:
    base = player_explanation_base(row)
    strengths = list(base.get("strengths", []))
    cautions = list(base.get("cautions", []))
    pos = normalize_position(row.get("position", ""))
    if pos == "K":
        strengths.append(f"Kicker projection: {float(row.get('projection', 0)):.1f} points; K VOR {float(row.get('vor', 0)):+.1f}")
        cautions.append("Kicker scoring is relatively flat and replaceable; DraftEdge intentionally favors waiting unless the late-draft need is real")
    elif pos == "DST":
        strengths.append(f"Season D/ST projection: {float(row.get('projection', 0)):.1f} points; D/ST VOR {float(row.get('vor', 0)):+.1f}")
        cautions.append("D/ST output is matchup-sensitive and streamable; season projections carry wider uncertainty than skill-position projections")
    return {"strengths": strengths[:5], "cautions": cautions[:5]}
