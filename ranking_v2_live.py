from __future__ import annotations

import numpy as np
import pandas as pd

import ranking_v2 as _base

recommend_players = _base.recommend_players
simulate_opponent_pick = _base.simulate_opponent_pick
player_explanation = _base.player_explanation


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _minmax(series: pd.Series) -> pd.Series:
    s = _num(series)
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
    num = pd.Series(0.0, index=index)
    den = pd.Series(0.0, index=index)
    for values, weight in components.values():
        v = _num(values)
        ok = v.notna()
        num.loc[ok] += v.loc[ok] * float(weight)
        den.loc[ok] += float(weight)
    return num / den.replace(0, np.nan)


def prepare_rankings(players, config):
    """Final live weighting layer for Ranking v2.

    Current projections can carry forecast weight. Historical fallbacks lean
    more heavily on real market consensus and durability so an unusually strong
    per-game historical season cannot dominate merely because it was annualized.
    """
    df = _base.prepare_rankings(players, config).copy()
    if df.empty:
        return df

    supplied = df["projection_source"].ne("Historical fallback")
    projection_component = _minmax(df["projection"])
    vor_component = _minmax(df["vor"])
    durability_component = 100.0 - _num(df["risk_score"])

    current_components = {
        "projection": (projection_component, 0.32),
        "vor": (vor_component, 0.24),
        "opportunity": (df["opportunity_score"], 0.14),
        "market": (df["market_score"], 0.12),
        "depth": (df["depth_score"], 0.05),
        "durability": (durability_component, 0.13),
    }
    fallback_components = {
        "projection": (projection_component, 0.18),
        "vor": (vor_component, 0.15),
        "opportunity": (df["opportunity_score"], 0.12),
        "market": (df["market_score"], 0.35),
        "depth": (df["depth_score"], 0.05),
        "durability": (durability_component, 0.15),
    }
    current_score = _weighted(current_components, df.index)
    fallback_score = _weighted(fallback_components, df.index)
    df["model_score"] = current_score.where(supplied, fallback_score).fillna(50.0).round(1)
    df["draft_value"] = df["model_score"]
    df["model_rank"] = df["model_score"].rank(method="first", ascending=False).astype(int)
    df["overall_rank"] = df["model_rank"]
    df["position_rank"] = df.groupby("position")["model_score"].rank(method="first", ascending=False).astype(int)
    df["model_market_delta"] = (df["market_rank"] - df["model_rank"]).round(1)

    adp = _num(df["adp"])
    ecr = _num(df["ecr"])
    df["market_reference"] = adp.where(adp.notna(), ecr).where(lambda s: s.notna(), df["model_rank"].astype(float))
    df["market_reference_source"] = np.select(
        [adp.notna(), adp.isna() & ecr.notna()], ["ADP", "ECR"], default="Model fallback"
    )

    tiers = pd.Series(index=df.index, dtype=int)
    for pos, grp in df.groupby("position"):
        ordered = grp.sort_values("model_score", ascending=False)
        tier = 1
        anchor = None
        count = 0
        for idx, row in ordered.iterrows():
            score = float(row["model_score"])
            if anchor is not None and count >= 3 and anchor - score >= 4.5:
                tier += 1
                anchor = score
                count = 0
            elif anchor is None:
                anchor = score
            tiers.loc[idx] = tier
            count += 1
    df["tier"] = tiers.astype(int)
    return df.sort_values(["model_score", "projection"], ascending=False).reset_index(drop=True)
