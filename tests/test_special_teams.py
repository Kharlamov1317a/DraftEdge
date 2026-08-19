import pandas as pd

import fantasy_engine as engine
from special_teams_support import apply_special_teams_support


apply_special_teams_support(engine)


def test_normalize_and_score_kicker_and_dst():
    cfg = engine.LeagueConfig()
    raw = pd.DataFrame([
        {
            "player": "Demo Kicker", "team": "DET", "position": "PK", "games": 17,
            "kicker_fg_made": 30, "kicker_fg_missed": 5,
            "kicker_xp_made": 40, "kicker_xp_missed": 1,
        },
        {
            "player": "Detroit Lions D/ST", "team": "DET", "position": "DEF", "games": 17,
            "dst_sacks": 40, "dst_interceptions": 15, "dst_fumble_recoveries": 8,
            "dst_td": 4, "dst_safeties": 0, "dst_blocked_kicks": 0,
            "dst_points_allowed": 340,
        },
    ])
    norm = engine.normalize_player_data(raw)
    assert norm["position"].tolist() == ["K", "DST"]

    points = engine.score_fantasy_points(norm, cfg)
    assert points.iloc[0] == 130.0
    # 40 sacks + 30 INT + 16 FR + 24 TD + 17 points-allowed tier points.
    assert points.iloc[1] == 127.0


def test_special_teams_roster_counts_and_needs():
    cfg = engine.LeagueConfig(k=1, dst=1)
    empty = engine.roster_counts([], 1)
    assert empty["K"] == 0
    assert empty["DST"] == 0
    assert engine.roster_need_factor("K", empty, cfg) > 1.0
    assert engine.roster_need_factor("DST", empty, cfg) > 1.0

    log = [
        {"slot": 1, "position": "K"},
        {"slot": 1, "position": "DST"},
    ]
    filled = engine.roster_counts(log, 1)
    assert filled["K"] == 1
    assert filled["DST"] == 1
    assert engine.roster_need_factor("K", filled, cfg) < 1.0
    assert engine.roster_need_factor("DST", filled, cfg) < 1.0


def test_ranking_v3_keeps_kicker_and_dst():
    from ranking_v3 import prepare_rankings

    cfg = engine.LeagueConfig(teams=10, rounds=16, k=1, dst=1)
    players = pd.DataFrame([
        {"player_id": "q1", "player": "QB One", "team": "DET", "position": "QB", "games": 17, "projection": 300, "adp": 20},
        {"player_id": "r1", "player": "RB One", "team": "ATL", "position": "RB", "games": 17, "projection": 250, "adp": 5},
        {"player_id": "w1", "player": "WR One", "team": "CIN", "position": "WR", "games": 17, "projection": 240, "adp": 7},
        {"player_id": "t1", "player": "TE One", "team": "KC", "position": "TE", "games": 17, "projection": 190, "adp": 25},
        {"player_id": "k1", "player": "K One", "team": "DAL", "position": "K", "games": 17, "projection": 145, "adp": 145},
        {"player_id": "d1", "player": "Dallas Cowboys D/ST", "team": "DAL", "position": "DST", "games": 17, "projection": 125, "adp": 150},
    ])
    ranked = prepare_rankings(players, cfg)
    assert {"K", "DST"}.issubset(set(ranked["position"]))
    assert ranked.loc[ranked["position"].eq("K"), "role"].iloc[0] == "Kicker"
    assert ranked.loc[ranked["position"].eq("DST"), "role"].iloc[0] == "Team Defense / Special Teams"
