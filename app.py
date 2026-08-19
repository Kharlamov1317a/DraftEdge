from __future__ import annotations

"""DraftEdge entry point with Ranking v3, K/DST support and public-board controls."""

from dataclasses import asdict, fields, is_dataclass, replace
import os
from pathlib import Path

import pandas as pd
import streamlit as st

import fantasy_engine as _fantasy_engine
from special_teams_support import apply_special_teams_support, install_demo_support

apply_special_teams_support(_fantasy_engine)

import demo_data as _demo_data  # noqa: E402
install_demo_support(_demo_data, _fantasy_engine)

import data_sources as _data_sources  # noqa: E402
from special_teams_data import install_data_support  # noqa: E402
install_data_support(_data_sources, _fantasy_engine)

import sleeper_client as _sleeper_client  # noqa: E402
from special_teams_sleeper import install_sleeper_support  # noqa: E402
install_sleeper_support(_sleeper_client, _fantasy_engine)

from ranking_v3 import prepare_rankings as _prepare_rankings_v3  # noqa: E402
from ranking_v3 import recommend_players as _recommend_players_v3  # noqa: E402
from ranking_v3 import simulate_opponent_pick as _simulate_opponent_pick_v3  # noqa: E402
from shared_draft_state import publish_board_state_from_session  # noqa: E402

_fantasy_engine.prepare_rankings = _prepare_rankings_v3
_fantasy_engine.recommend_players = _recommend_players_v3
_fantasy_engine.simulate_opponent_pick = _simulate_opponent_pick_v3


if not hasattr(st, "_draftedge_original_rerun"):
    st._draftedge_original_rerun = st.rerun
_original_rerun = st._draftedge_original_rerun

_SPECIAL_CONFIG_FIELDS = [
    "k", "dst",
    "kicker_xp_made", "kicker_xp_missed", "kicker_fg_made", "kicker_fg_missed",
    "dst_sack", "dst_interception", "dst_fumble_recovery", "dst_td", "dst_safety",
    "dst_blocked_kick", "dst_return_td", "dst_two_point_return", "dst_points_allowed_enabled",
    "dst_pa_0", "dst_pa_1_6", "dst_pa_7_13", "dst_pa_14_20", "dst_pa_21_27", "dst_pa_28_34", "dst_pa_35_plus",
]


def _special_snapshot(cfg) -> dict:
    return {name: getattr(cfg, name) for name in _SPECIAL_CONFIG_FIELDS if hasattr(cfg, name)}


def _sync_or_restore_special_config() -> None:
    cfg = st.session_state.get("config")
    if not isinstance(cfg, _fantasy_engine.LeagueConfig):
        return
    if "_draftedge_special_config_snapshot" not in st.session_state:
        st.session_state._draftedge_special_config_snapshot = _special_snapshot(cfg)
        return
    if bool(st.session_state.pop("_draftedge_special_update_intent", False)):
        st.session_state._draftedge_special_config_snapshot = _special_snapshot(cfg)
        return
    snapshot = dict(st.session_state.get("_draftedge_special_config_snapshot") or {})
    changes = {k: v for k, v in snapshot.items() if hasattr(cfg, k) and getattr(cfg, k) != v}
    if changes:
        st.session_state.config = replace(cfg, **changes)


def _rerun_with_board_publish(*args, **kwargs):
    _sync_or_restore_special_config()
    publish_board_state_from_session(st.session_state)
    return _original_rerun(*args, **kwargs)


def _init_public_board_settings() -> None:
    defaults = {
        "owner_names": {},
        "public_reactions_enabled": True,
        "public_gifs_enabled": True,
        "public_owner_banter_enabled": True,
        "public_pick_quality_mode": True,
        "public_gif_frequency": 55,
        "public_curated_gif_bias": 75,
        "public_reaction_seconds": 7,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _giphy_key_configured() -> bool:
    if str(os.environ.get("GIPHY_API_KEY", "")).strip():
        return True
    try:
        return bool(str(st.secrets.get("GIPHY_API_KEY", "")).strip())
    except Exception:
        return False


def _enrich_public_pick_metadata() -> None:
    ranked = globals().get("ranked")
    log = st.session_state.get("draft_log", [])
    if not isinstance(ranked, pd.DataFrame) or ranked.empty or not log:
        return
    work = ranked.copy()
    work["_player_id"] = work["player_id"].fillna("").astype(str) if "player_id" in work else ""
    work["_sleeper_id"] = work["sleeper_id"].fillna("").astype(str) if "sleeper_id" in work else ""
    by_player = {row["_player_id"]: row for _, row in work.iterrows() if row["_player_id"]}
    by_sleeper = {row["_sleeper_id"]: row for _, row in work.iterrows() if row["_sleeper_id"]}
    for pick in log:
        row = by_player.get(str(pick.get("player_id") or ""))
        if row is None:
            row = by_sleeper.get(str(pick.get("sleeper_id") or ""))
        if row is None:
            continue

        def num(name: str):
            try:
                value = row.get(name)
                return None if pd.isna(value) else float(value)
            except Exception:
                return None

        pick_no = float(pick.get("pick") or 0)
        overall_rank, adp, ecr, years_exp = num("overall_rank"), num("adp"), num("ecr"), num("years_exp")
        if overall_rank is not None:
            pick["overall_rank"] = overall_rank
            pick["rank_delta"] = pick_no - overall_rank
        if adp is not None:
            pick["adp"] = adp
            pick["adp_delta"] = pick_no - adp
        if ecr is not None:
            pick["ecr"] = ecr
        if years_exp is not None:
            pick["years_exp"] = years_exp
            pick["is_rookie"] = years_exp <= 0


_init_public_board_settings()

if "config" in st.session_state and not isinstance(st.session_state.get("config"), _fantasy_engine.LeagueConfig):
    old_cfg = st.session_state.get("config")
    try:
        raw = asdict(old_cfg) if is_dataclass(old_cfg) else dict(old_cfg)
    except Exception:
        raw = {}
    allowed = {f.name for f in fields(_fantasy_engine.LeagueConfig)}
    st.session_state.config = _fantasy_engine.LeagueConfig(**{k: v for k, v in raw.items() if k in allowed})

_sync_or_restore_special_config()
st.rerun = _rerun_with_board_publish
_legacy = Path(__file__).resolve().with_name("app_legacy.py")

try:
    exec(compile(_legacy.read_text(encoding="utf-8"), str(_legacy), "exec"), globals(), globals())
finally:
    _enrich_public_pick_metadata()
    publish_board_state_from_session(st.session_state)

try:
    with data_tab:
        st.divider()
        st.subheader("Footballguys + special-teams projection support")
        st.info(
            "Footballguys `projection-set-preseason-all-YYYY.csv` exports are auto-detected. DraftEdge now imports the separate "
            "Consensus sets for **QB/RB/WR/TE, kickers (PK), and team defenses (TD)**. Offensive points are rescored from raw stats; "
            "kickers use converted/missed XPs and FGs; D/ST uses sacks, interceptions, fumble recoveries, TDs, safeties, blocks, "
            "return TDs and optional points-allowed tiers. Because the export contains season PA rather than weekly PA, points-allowed "
            "tier scoring is an **average-PA/game approximation** and is labeled as such in the projection audit."
        )
        st.caption(
            "For best current-season rankings, load nflverse/Sleeper metadata first, configure league + advanced scoring, then blend the Footballguys file."
        )
except Exception:
    pass


with st.sidebar:
    st.divider()
    st.subheader("Decision support")
    st.page_link("pages/2_Draft_Decision_Center.py", label="Open Draft Decision Center", icon="🧭", use_container_width=True)
    st.caption("Includes QB/RB/WR/TE/K/DST, injury context, bye conflicts, special-teams draft timing and player/unit comparison.")

    cfg = st.session_state.config
    with st.expander("Kicker & D/ST roster settings", expanded=False):
        k_slots = st.number_input("Kicker starters", 0, 3, int(getattr(cfg, "k", 1)), 1)
        dst_slots = st.number_input("D/ST starters", 0, 3, int(getattr(cfg, "dst", 1)), 1)
        st.caption("These slots are included in replacement-level demand, roster needs and Pick Rank. Default is 1 K + 1 D/ST.")
        if st.button("Apply K/DST roster settings", use_container_width=True):
            st.session_state.config = replace(cfg, k=int(k_slots), dst=int(dst_slots))
            st.session_state._draftedge_special_update_intent = True
            st.session_state.draft_log = []
            st.session_state.mc_key = None
            st.success("K/DST roster settings applied. Draft reset.")
            st.rerun()

    with st.expander("Advanced scoring", expanded=False):
        cfg = st.session_state.config
        st.caption("These values rescore raw Footballguys projections and the DraftEdge model.")
        st.markdown("**Offense**")
        a, b = st.columns(2)
        pass_yd = a.number_input("Pass yds / point", 1.0, 100.0, float(cfg.pass_yd_per_point), 1.0)
        pass_td = b.number_input("Pass TD", 0.0, 10.0, float(cfg.pass_td), 0.5)
        inter = a.number_input("Interception", -10.0, 0.0, float(cfg.interception), 0.5)
        rush_yd = b.number_input("Rush yds / point", 1.0, 50.0, float(cfg.rush_yd_per_point), 1.0)
        rush_td = a.number_input("Rush TD", 0.0, 10.0, float(cfg.rush_td), 0.5)
        rec_yd = b.number_input("Rec yds / point", 1.0, 50.0, float(cfg.rec_yd_per_point), 1.0)
        rec_td = a.number_input("Rec TD", 0.0, 10.0, float(cfg.rec_td), 0.5)
        fumble = b.number_input("Fumble lost", -10.0, 0.0, float(cfg.fumble), 0.5)

        st.markdown("**Kicker**")
        k1, k2 = st.columns(2)
        xp_made = k1.number_input("XP made", -5.0, 10.0, float(cfg.kicker_xp_made), 0.5)
        xp_miss = k2.number_input("XP missed", -5.0, 5.0, float(cfg.kicker_xp_missed), 0.5)
        fg_made = k1.number_input("FG made", -5.0, 10.0, float(cfg.kicker_fg_made), 0.5)
        fg_miss = k2.number_input("FG missed", -5.0, 5.0, float(cfg.kicker_fg_missed), 0.5)
        st.caption("Footballguys raw CSV has total FG conversions/misses, not distance buckets, so DraftEdge uses one FG-made value.")

        st.markdown("**D/ST events**")
        d1, d2 = st.columns(2)
        dst_sack = d1.number_input("Sack", -5.0, 10.0, float(cfg.dst_sack), 0.5)
        dst_int = d2.number_input("Interception", -5.0, 10.0, float(cfg.dst_interception), 0.5)
        dst_fr = d1.number_input("Fumble recovery", -5.0, 10.0, float(cfg.dst_fumble_recovery), 0.5)
        dst_td = d2.number_input("Defensive TD", 0.0, 12.0, float(cfg.dst_td), 0.5)
        dst_safe = d1.number_input("Safety", -5.0, 10.0, float(cfg.dst_safety), 0.5)
        dst_blk = d2.number_input("Blocked kick", -5.0, 10.0, float(cfg.dst_blocked_kick), 0.5)
        dst_ret = d1.number_input("Return TD", 0.0, 12.0, float(cfg.dst_return_td), 0.5)
        dst_2pr = d2.number_input("2-point return", 0.0, 10.0, float(cfg.dst_two_point_return), 0.5)

        pa_enabled = st.toggle("Use D/ST points-allowed tiers", value=bool(cfg.dst_points_allowed_enabled))
        if pa_enabled:
            st.caption("For season-level Footballguys projections, these tiers are approximated from average projected PA/game.")
            p1, p2 = st.columns(2)
            pa0 = p1.number_input("PA 0", -10.0, 20.0, float(cfg.dst_pa_0), 1.0)
            pa1 = p2.number_input("PA 1–6", -10.0, 20.0, float(cfg.dst_pa_1_6), 1.0)
            pa7 = p1.number_input("PA 7–13", -10.0, 20.0, float(cfg.dst_pa_7_13), 1.0)
            pa14 = p2.number_input("PA 14–20", -10.0, 20.0, float(cfg.dst_pa_14_20), 1.0)
            pa21 = p1.number_input("PA 21–27", -10.0, 20.0, float(cfg.dst_pa_21_27), 1.0)
            pa28 = p2.number_input("PA 28–34", -10.0, 20.0, float(cfg.dst_pa_28_34), 1.0)
            pa35 = p1.number_input("PA 35+", -20.0, 20.0, float(cfg.dst_pa_35_plus), 1.0)
        else:
            pa0, pa1, pa7, pa14, pa21, pa28, pa35 = (
                cfg.dst_pa_0, cfg.dst_pa_1_6, cfg.dst_pa_7_13, cfg.dst_pa_14_20,
                cfg.dst_pa_21_27, cfg.dst_pa_28_34, cfg.dst_pa_35_plus,
            )

        if st.button("Apply advanced scoring", use_container_width=True):
            st.session_state.config = replace(
                cfg,
                pass_yd_per_point=float(pass_yd), pass_td=float(pass_td), interception=float(inter),
                rush_yd_per_point=float(rush_yd), rush_td=float(rush_td), rec_yd_per_point=float(rec_yd),
                rec_td=float(rec_td), fumble=float(fumble),
                kicker_xp_made=float(xp_made), kicker_xp_missed=float(xp_miss),
                kicker_fg_made=float(fg_made), kicker_fg_missed=float(fg_miss),
                dst_sack=float(dst_sack), dst_interception=float(dst_int), dst_fumble_recovery=float(dst_fr),
                dst_td=float(dst_td), dst_safety=float(dst_safe), dst_blocked_kick=float(dst_blk),
                dst_return_td=float(dst_ret), dst_two_point_return=float(dst_2pr),
                dst_points_allowed_enabled=bool(pa_enabled), dst_pa_0=float(pa0), dst_pa_1_6=float(pa1),
                dst_pa_7_13=float(pa7), dst_pa_14_20=float(pa14), dst_pa_21_27=float(pa21),
                dst_pa_28_34=float(pa28), dst_pa_35_plus=float(pa35),
            )
            st.session_state._draftedge_special_update_intent = True
            st.session_state.mc_key = None
            st.success("Advanced offense/K/DST scoring applied.")
            st.rerun()

    st.divider()
    st.subheader("Public draft board")
    st.page_link("pages/1_Public_Draft_Board.py", label="Open public draft board", icon="🖥️", use_container_width=True)

    with st.expander("Board reactions & owner names", expanded=False):
        st.session_state.public_reactions_enabled = st.toggle("Pick reactions", value=bool(st.session_state.public_reactions_enabled))
        st.session_state.public_gifs_enabled = st.toggle(
            "Reaction GIFs", value=bool(st.session_state.public_gifs_enabled), disabled=not st.session_state.public_reactions_enabled,
        )
        st.session_state.public_gif_frequency = st.slider(
            "GIF frequency", 0, 100, int(st.session_state.public_gif_frequency), 5, format="%d%%",
            disabled=(not st.session_state.public_reactions_enabled or not st.session_state.public_gifs_enabled),
        )
        st.session_state.public_curated_gif_bias = st.slider(
            "Iconic meme bias", 0, 100, int(st.session_state.public_curated_gif_bias), 5, format="%d%%",
            disabled=(not st.session_state.public_reactions_enabled or not st.session_state.public_gifs_enabled),
        )
        st.session_state.public_owner_banter_enabled = st.toggle(
            "Owner-specific banter", value=bool(st.session_state.public_owner_banter_enabled), disabled=not st.session_state.public_reactions_enabled,
        )
        st.session_state.public_pick_quality_mode = st.toggle(
            "Use pick context for reactions", value=bool(st.session_state.public_pick_quality_mode), disabled=not st.session_state.public_reactions_enabled,
            help="Now includes early/late kicker and D/ST picks, special-teams runs, reaches/steals, stacks and roster behavior.",
        )
        st.session_state.public_reaction_seconds = st.slider(
            "Reaction display time", 3, 12, int(st.session_state.public_reaction_seconds), 1, format="%d sec",
            disabled=not st.session_state.public_reactions_enabled,
        )
        if st.session_state.public_gifs_enabled:
            if _giphy_key_configured():
                st.success("GIPHY GIF provider configured.")
            else:
                st.warning("Reaction GIFs need GIPHY_API_KEY in Streamlit Cloud secrets; text/emoji reactions still work.")

        st.markdown("**Owner names**")
        team_count = int(getattr(st.session_state.config, "teams", 12))
        current_names = dict(st.session_state.get("owner_names", {}) or {})
        updated_names = {}
        for slot in range(1, team_count + 1):
            existing = str(current_names.get(slot, current_names.get(str(slot), "")) or "")
            name = st.text_input(f"Pick slot {slot}", value=existing, placeholder=f"Team {slot}", key=f"public_owner_name_{slot}").strip()
            if name:
                updated_names[slot] = name
        st.session_state.owner_names = updated_names

    publish_board_state_from_session(st.session_state)

try:
    with rankings_tab:
        st.divider()
        st.subheader("Kicker & D/ST rankings")
        special = ranked[ranked["position"].isin(["K", "DST"])].copy()
        if special.empty:
            st.info("No kickers or team defenses are currently in the player pool. Load Sleeper metadata or a projection source containing K/DST.")
        else:
            cols = [
                "overall_rank", "player", "team", "position", "position_rank", "tier", "projection", "vor",
                "model_score", "adp", "ecr", "risk_label", "projection_source",
            ]
            st.dataframe(special[[c for c in cols if c in special.columns]].head(100), use_container_width=True, hide_index=True)
            st.caption("K/DST Model Rank incorporates starter demand and replaceability; Pick Rank in Decision Center additionally discourages drafting them too early.")
except Exception:
    pass

try:
    with setup_tab:
        st.divider()
        cfg = st.session_state.config
        st.subheader("Special teams configuration")
        st.write(f"**Starters:** {getattr(cfg, 'k', 1)} K · {getattr(cfg, 'dst', 1)} D/ST")
        st.write(
            f"**K scoring:** XP {cfg.kicker_xp_made:+g}, FG {cfg.kicker_fg_made:+g}, missed XP {cfg.kicker_xp_missed:+g}, missed FG {cfg.kicker_fg_missed:+g}"
        )
        st.write(
            f"**D/ST:** sack {cfg.dst_sack:g}, INT {cfg.dst_interception:g}, FR {cfg.dst_fumble_recovery:g}, TD {cfg.dst_td:g}, "
            f"safety {cfg.dst_safety:g}, block {cfg.dst_blocked_kick:g}, return TD {cfg.dst_return_td:g}"
        )
        st.code(
            "Special-team input columns: position=K or DST; kicker_fg_attempts,kicker_fg_made,kicker_fg_missed,"
            "kicker_xp_attempts,kicker_xp_made,kicker_xp_missed,dst_sacks,dst_interceptions,"
            "dst_fumble_recoveries,dst_td,dst_safeties,dst_blocked_kicks,dst_return_td,dst_points_allowed",
            language="text",
        )
except Exception:
    pass
