from __future__ import annotations
import numpy as np
import pandas as pd


def make_demo_players(seed: int = 2026) -> pd.DataFrame:
    """Create a deterministic fictional player pool for testing the app UI.

    The names and stats are synthetic; replace with a PFR-exported or custom CSV
    before using the board for a real draft.
    """
    rng = np.random.default_rng(seed)
    rows = []
    counts = {"QB": 30, "RB": 55, "WR": 70, "TE": 35}
    teams = ["ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB","HOU","IND","JAX","KC","LAC","LAR","LV","MIA","MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF","TB","TEN","WAS"]
    first = ["Alex","Blake","Cameron","Drew","Evan","Grant","Hayden","Isaac","Jalen","Kendall","Logan","Mason","Noah","Owen","Parker","Quinn","Riley","Sam","Trey","Wyatt"]
    last = ["Adams","Brooks","Carter","Davis","Edwards","Foster","Gray","Hall","Irwin","Johnson","King","Lewis","Miller","Nelson","Owens","Price","Reed","Stone","Turner","Walker"]

    idx = 1
    for pos, n in counts.items():
        for i in range(n):
            talent = max(0.05, 1 - i / (n * 1.15))
            games = int(rng.integers(13, 18))
            age = int(rng.integers(21, 34))
            row = dict(
                player_id=f"D{idx:04d}",
                player=f"{first[(idx*7)%len(first)]} {last[(idx*11)%len(last)]} {idx}",
                team=teams[(idx*5)%len(teams)],
                position=pos,
                age=age,
                games=games,
                passing_yards=0, passing_td=0, interceptions=0,
                rushing_attempts=0, rushing_yards=0, rushing_td=0,
                targets=0, receptions=0, receiving_yards=0, receiving_td=0,
                fumbles=int(rng.integers(0, 4)),
                fantasy_points=np.nan,
                projection=np.nan,
                adp=np.nan,
            )
            if pos == "QB":
                row["passing_yards"] = int(2600 + talent*2200 + rng.normal(0, 250))
                row["passing_td"] = int(15 + talent*22 + rng.normal(0, 3))
                row["interceptions"] = int(max(3, 14 - talent*5 + rng.normal(0, 2)))
                row["rushing_yards"] = int(max(20, rng.gamma(2.2, 90) * (0.5 + talent)))
                row["rushing_attempts"] = int(row["rushing_yards"] / max(3.5, rng.normal(5.2, 0.8)))
                row["rushing_td"] = int(max(0, rng.poisson(2.5 + 3*talent)))
            elif pos == "RB":
                row["rushing_attempts"] = int(70 + talent*230 + rng.normal(0, 25))
                row["rushing_yards"] = int(row["rushing_attempts"] * max(3.3, rng.normal(4.4, 0.45)))
                row["rushing_td"] = int(max(1, rng.poisson(3 + 7*talent)))
                row["targets"] = int(15 + talent*70 + rng.normal(0, 10))
                row["receptions"] = int(row["targets"] * max(0.55, min(0.88, rng.normal(0.73, 0.06))))
                row["receiving_yards"] = int(row["receptions"] * max(5, rng.normal(7.8, 1.2)))
                row["receiving_td"] = int(max(0, rng.poisson(1 + 2*talent)))
            elif pos == "WR":
                row["targets"] = int(35 + talent*125 + rng.normal(0, 12))
                row["receptions"] = int(row["targets"] * max(0.48, min(0.82, rng.normal(0.66, 0.06))))
                row["receiving_yards"] = int(row["receptions"] * max(8, rng.normal(13.2, 2.4)))
                row["receiving_td"] = int(max(1, rng.poisson(2 + 7*talent)))
                row["rushing_attempts"] = int(max(0, rng.poisson(2 + 4*talent)))
                row["rushing_yards"] = int(row["rushing_attempts"] * max(3, rng.normal(7, 2)))
                row["rushing_td"] = int(max(0, rng.poisson(0.3)))
            else:
                row["targets"] = int(25 + talent*90 + rng.normal(0, 10))
                row["receptions"] = int(row["targets"] * max(0.5, min(0.84, rng.normal(0.68, 0.06))))
                row["receiving_yards"] = int(row["receptions"] * max(7, rng.normal(10.8, 1.6)))
                row["receiving_td"] = int(max(1, rng.poisson(2 + 5*talent)))
            rows.append(row)
            idx += 1

    df = pd.DataFrame(rows)
    # ADP roughly follows synthetic scoring strength but with noise.
    sort_key = (
        df["passing_yards"] / 25 + df["passing_td"]*4 - df["interceptions"]*2 +
        df["rushing_yards"] / 10 + df["rushing_td"]*6 + df["receptions"] +
        df["receiving_yards"] / 10 + df["receiving_td"]*6
    )
    order = sort_key.rank(method="first", ascending=False)
    df["adp"] = (order + rng.normal(0, 8, len(df))).clip(1, len(df)).round(1)
    return df
