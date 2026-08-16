import pandas as pd

from data_sources import blend_projection_sources
from demo_data import make_demo_players
from fantasy_engine import (
    LeagueConfig,
    monte_carlo_wait_analysis,
    prepare_rankings,
    recommend_players,
    score_fantasy_points,
    snake_pick_metadata,
)
from sleeper_client import draft_log_from_sleeper, enrich_players_from_sleeper


def test_rankings_build():
    cfg = LeagueConfig()
    ranked = prepare_rankings(make_demo_players(), cfg)
    assert len(ranked) > 100
    assert ranked["draft_value"].notna().all()
    assert set(ranked["position"].unique()) == {"QB", "RB", "WR", "TE"}
    assert {"health_score", "market_score", "depth_score"}.issubset(ranked.columns)


def test_snake_order():
    meta = snake_pick_metadata(4, 2)
    assert meta["slot"].tolist() == [1, 2, 3, 4, 4, 3, 2, 1]


def test_recommendations_and_monte_carlo():
    cfg = LeagueConfig(teams=12, user_slot=6)
    ranked = prepare_rankings(make_demo_players(), cfg)
    # Pick 6 is user's first pick in a 12-team draft.
    mc = monte_carlo_wait_analysis(ranked, [], cfg, 6, 6, simulations=30, candidate_count=8)
    recs = recommend_players(ranked, [], cfg, 6, 6, monte_carlo=mc)
    assert len(recs) > 0
    assert "p_available_next" in recs.columns
    assert "take_now_edge" in recs.columns
    assert not mc.empty


def test_te_premium_changes_scoring():
    df = pd.DataFrame([
        {"position": "TE", "receptions": 50},
        {"position": "WR", "receptions": 50},
    ])
    base = score_fantasy_points(df, LeagueConfig(ppr=1.0, te_premium=0.0))
    tep = score_fantasy_points(df, LeagueConfig(ppr=1.0, te_premium=0.5))
    assert tep.iloc[0] - base.iloc[0] == 25
    assert tep.iloc[1] == base.iloc[1]


def test_superflex_boosts_qb_replacement_demand():
    players = make_demo_players()
    one_qb = prepare_rankings(players, LeagueConfig(superflex=0))
    sf = prepare_rankings(players, LeagueConfig(superflex=1))
    q1 = one_qb[one_qb["position"] == "QB"]["replacement_points"].iloc[0]
    q2 = sf[sf["position"] == "QB"]["replacement_points"].iloc[0]
    # More QB demand pushes replacement deeper and lowers replacement points.
    assert q2 <= q1


def test_projection_blend():
    master = make_demo_players().head(5)
    base_rank = prepare_rankings(master, LeagueConfig())
    base_map = base_rank.set_index("player_id")["projection"]
    normalized_ids = master["player_id"].astype(str)
    baseline = normalized_ids.map(base_map)
    source = pd.DataFrame({
        "player": master["player"].tolist(),
        "position": master["position"].tolist(),
        "projection": [300, 290, 280, 270, 260],
        "adp": [1, 2, 3, 4, 5],
    })
    blended, audit = blend_projection_sources(master, [("test", source, 2.0)], baseline, 1.0)
    assert blended["projection"].notna().all()
    assert audit.iloc[0]["matched"] == 5


def test_sleeper_pick_mapping():
    ranked = prepare_rankings(make_demo_players(), LeagueConfig())
    target = ranked.iloc[0].copy()
    sleeper = pd.DataFrame([{
        "player_id": "9999", "sleeper_id": "9999", "player": target["player"], "team": target["team"],
        "position": target["position"], "injury_status": "Questionable", "depth_chart_order": 1,
    }])
    enriched = enrich_players_from_sleeper(ranked, sleeper)
    row = enriched[enriched["player"].eq(target["player"])].iloc[0]
    assert row["sleeper_id"] == "9999"
    picks = [{
        "player_id": "9999", "pick_no": 1, "round": 1, "draft_slot": 1,
        "metadata": {"first_name": target["player"].split()[0], "last_name": " ".join(target["player"].split()[1:]),
                     "position": target["position"], "team": target["team"]},
    }]
    log = draft_log_from_sleeper(picks, prepare_rankings(enriched, LeagueConfig()), sleeper)
    assert len(log) == 1
    assert log[0]["pick"] == 1
