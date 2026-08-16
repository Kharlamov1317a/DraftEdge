from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional
import re

import numpy as np
import pandas as pd

from fantasy_engine import CANONICAL_COLUMNS, normalize_name, normalize_player_data


@dataclass
class NflverseLoadResult:
    players: pd.DataFrame
    messages: list[str]
    loaded: dict[str, int]


def _to_pandas(obj) -> pd.DataFrame:
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.DataFrame):
        return obj.copy()
    if hasattr(obj, "to_pandas"):
        return obj.to_pandas()
    try:
        return pd.DataFrame(obj)
    except Exception:
        return pd.DataFrame()


def _try_loader(func: Callable, season: int) -> tuple[pd.DataFrame, Optional[str]]:
    attempts = [
        lambda: func([season]),
        lambda: func(seasons=[season]),
        lambda: func(season=season),
        lambda: func(),
    ]
    last_error = None
    for attempt in attempts:
        try:
            result = _to_pandas(attempt())
            return result, None
        except Exception as exc:  # loader APIs differ slightly across versions
            last_error = exc
    return pd.DataFrame(), str(last_error) if last_error else "loader failed"


def _find_col(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    lookup = {re.sub(r"[^a-z0-9]+", "", str(c).lower()): c for c in df.columns}
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        if key in lookup:
            return lookup[key]
    return None


def _filter_season(df: pd.DataFrame, season: int) -> pd.DataFrame:
    if df.empty:
        return df
    c = _find_col(df, ["season", "year"])
    if c is None:
        return df
    vals = pd.to_numeric(df[c], errors="coerce")
    subset = df[vals == int(season)]
    return subset if not subset.empty else df


def _name_key_series(df: pd.DataFrame) -> pd.Series:
    name_col = _find_col(df, ["player", "player_name", "player_display_name", "full_name", "display_name", "name"])
    if name_col is None:
        return pd.Series([""] * len(df), index=df.index)
    return df[name_col].fillna("").map(normalize_name)


def _id_series(df: pd.DataFrame) -> pd.Series:
    c = _find_col(df, ["gsis_id", "player_id", "gsisid"])
    if c is None:
        return pd.Series([""] * len(df), index=df.index)
    return df[c].fillna("").astype(str).replace({"nan": "", "None": ""})


def _latest_by_player(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    work = df.copy()
    work["__id"] = _id_series(work)
    work["__name"] = _name_key_series(work)
    work["__key"] = np.where(work["__id"].ne(""), "id:" + work["__id"], "nm:" + work["__name"])
    sort_col = _find_col(work, ["date", "game_date", "report_date", "week", "depth_team", "timestamp", "scrape_date"])
    if sort_col is not None:
        try:
            work = work.sort_values(sort_col)
        except Exception:
            pass
    return work.drop_duplicates("__key", keep="last")


def _aggregate_historical_stats(stats: pd.DataFrame) -> pd.DataFrame:
    if stats.empty:
        return pd.DataFrame()
    work = stats.copy()
    work["__id"] = _id_series(work)
    work["__name"] = _name_key_series(work)
    work["__key"] = np.where(work["__id"].ne(""), "id:" + work["__id"], "nm:" + work["__name"])

    name_col = _find_col(work, ["player_display_name", "player_name", "player", "full_name", "name"])
    pos_col = _find_col(work, ["position", "pos"])
    team_col = _find_col(work, ["recent_team", "team", "team_abbr"])
    week_col = _find_col(work, ["week"])

    field_candidates = {
        "passing_yards": ["passing_yards"],
        "passing_td": ["passing_tds", "passing_td"],
        "interceptions": ["interceptions", "passing_interceptions"],
        "rushing_attempts": ["carries", "rushing_attempts"],
        "rushing_yards": ["rushing_yards"],
        "rushing_td": ["rushing_tds", "rushing_td"],
        "targets": ["targets"],
        "receptions": ["receptions"],
        "receiving_yards": ["receiving_yards"],
        "receiving_td": ["receiving_tds", "receiving_td"],
        "fumbles": ["rushing_fumbles", "receiving_fumbles", "fumbles", "sack_fumbles"],
        "fantasy_points": ["fantasy_points_ppr", "fantasy_points"],
    }

    rows = []
    for key, grp in work.groupby("__key", dropna=False):
        row = {
            "join_key": key,
            "player_id": str(grp["__id"].iloc[-1] or ""),
            "player": str(grp[name_col].dropna().iloc[-1]) if name_col and grp[name_col].notna().any() else "",
            "position": str(grp[pos_col].dropna().iloc[-1]) if pos_col and grp[pos_col].notna().any() else "",
            "team": str(grp[team_col].dropna().iloc[-1]) if team_col and grp[team_col].notna().any() else "FA",
        }
        if week_col is not None:
            row["games"] = int(pd.to_numeric(grp[week_col], errors="coerce").nunique())
        else:
            games_col = _find_col(grp, ["games", "g"])
            row["games"] = float(pd.to_numeric(grp[games_col], errors="coerce").max()) if games_col else 17
        for target, candidates in field_candidates.items():
            col = _find_col(grp, candidates)
            if col is None:
                row[target] = np.nan
                continue
            vals = pd.to_numeric(grp[col], errors="coerce")
            # Weekly/game-level rows should sum; season-level rows should not.
            row[target] = float(vals.sum(min_count=1)) if len(grp) > 1 else float(vals.iloc[0]) if vals.notna().any() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _build_roster_master(roster: pd.DataFrame, historical: pd.DataFrame) -> pd.DataFrame:
    if roster.empty and historical.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    if roster.empty:
        base = historical.copy()
        if "join_key" in base.columns:
            base = base.drop(columns=["join_key"])
        return normalize_player_data(base)

    latest = _latest_by_player(roster)
    name_col = _find_col(latest, ["full_name", "player_name", "player_display_name", "display_name", "player", "name"])
    pos_col = _find_col(latest, ["position", "pos"])
    team_col = _find_col(latest, ["team", "team_abbr", "club_code", "recent_team"])
    age_col = _find_col(latest, ["age"])
    exp_col = _find_col(latest, ["years_exp", "experience", "exp"])

    rows = []
    for _, r in latest.iterrows():
        pos = str(r.get(pos_col, "") if pos_col else "").upper()
        if pos not in {"QB", "RB", "WR", "TE", "HB", "FB"}:
            continue
        pid = str(r.get("__id", "") or "")
        name = str(r.get(name_col, "") if name_col else "").strip()
        if not name:
            continue
        key = str(r.get("__key", f"nm:{normalize_name(name)}"))
        rows.append({
            "join_key": key,
            "player_id": pid,
            "gsis_id": pid,
            "player": name,
            "team": str(r.get(team_col, "FA") if team_col else "FA"),
            "position": pos,
            "age": r.get(age_col, np.nan) if age_col else np.nan,
            "years_exp": r.get(exp_col, np.nan) if exp_col else np.nan,
            "data_source": "nflverse",
        })
    base = pd.DataFrame(rows)
    if base.empty:
        return normalize_player_data(historical.drop(columns=["join_key"], errors="ignore"))

    if not historical.empty:
        hist_cols = [c for c in historical.columns if c not in {"player_id", "player", "position", "team"}]
        base = base.merge(historical[["join_key"] + hist_cols], on="join_key", how="left")
    base = base.drop(columns=["join_key"], errors="ignore")
    return normalize_player_data(base)


def _merge_latest_status(master: pd.DataFrame, status_df: pd.DataFrame, kind: str) -> pd.DataFrame:
    if master.empty or status_df.empty:
        return master
    latest = _latest_by_player(status_df)
    latest["name_key"] = _name_key_series(latest)
    latest["id_key"] = _id_series(latest)

    out = master.copy()
    out["name_key"] = out["player"].map(normalize_name)
    out["id_key"] = out["gsis_id"].fillna("").astype(str)

    if kind == "injury":
        injury_col = _find_col(latest, ["report_status", "injury_status", "status"])
        practice_col = _find_col(latest, ["practice_status", "practice_participation"])
        keep = ["name_key", "id_key"]
        if injury_col:
            latest = latest.rename(columns={injury_col: "_injury_status"})
            keep.append("_injury_status")
        if practice_col:
            latest = latest.rename(columns={practice_col: "_practice_status"})
            keep.append("_practice_status")
        status = latest[keep].copy()
    else:
        order_col = _find_col(latest, ["depth_chart_order", "depth_order", "depth_team", "depth"])
        pos_col = _find_col(latest, ["depth_chart_position", "position", "pos"])
        keep = ["name_key", "id_key"]
        if order_col:
            latest = latest.rename(columns={order_col: "_depth_order"})
            keep.append("_depth_order")
        if pos_col:
            latest = latest.rename(columns={pos_col: "_depth_pos"})
            keep.append("_depth_pos")
        status = latest[keep].copy()

    # Name join is deliberately the fallback because some nflverse components use
    # different identifiers for the same player.
    by_id = status[status["id_key"].ne("")].drop_duplicates("id_key", keep="last")
    by_name = status[status["name_key"].ne("")].drop_duplicates("name_key", keep="last")
    if not by_id.empty:
        out = out.merge(by_id.drop(columns=["name_key"], errors="ignore"), on="id_key", how="left")
    if not by_name.empty:
        suffix_cols = [c for c in by_name.columns if c.startswith("_")]
        fallback = by_name[["name_key"] + suffix_cols].copy()
        fallback = fallback.rename(columns={c: c + "_name" for c in suffix_cols})
        out = out.merge(fallback, on="name_key", how="left")

    if kind == "injury":
        if "_injury_status" in out:
            out["injury_status"] = out["_injury_status"].where(out["_injury_status"].notna(), out.get("_injury_status_name"))
            out["injury_status"] = out["injury_status"].fillna(out.get("injury_status", ""))
        if "_practice_status" in out:
            out["practice_status"] = out["_practice_status"].where(out["_practice_status"].notna(), out.get("_practice_status_name"))
            out["practice_status"] = out["practice_status"].fillna(out.get("practice_status", ""))
    else:
        if "_depth_order" in out:
            out["depth_chart_order"] = pd.to_numeric(
                out["_depth_order"].where(out["_depth_order"].notna(), out.get("_depth_order_name")), errors="coerce"
            ).fillna(out.get("depth_chart_order"))
        if "_depth_pos" in out:
            out["depth_chart_position"] = out["_depth_pos"].where(out["_depth_pos"].notna(), out.get("_depth_pos_name"))
            out["depth_chart_position"] = out["depth_chart_position"].fillna(out.get("depth_chart_position", ""))

    drop_cols = [c for c in out.columns if c.startswith("_")] + ["name_key", "id_key"]
    return normalize_player_data(out.drop(columns=drop_cols, errors="ignore"))


def _merge_ff_rankings(master: pd.DataFrame, rankings: pd.DataFrame) -> pd.DataFrame:
    if master.empty or rankings.empty:
        return master
    work = rankings.copy()
    work["name_key"] = _name_key_series(work)
    pos_col = _find_col(work, ["position", "pos", "fantasy_position"])
    rank_col = _find_col(work, ["ecr", "rank", "overall_rank", "rank_ecr"])
    adp_col = _find_col(work, ["adp", "average_draft_position", "avg_pick"])
    date_col = _find_col(work, ["scrape_date", "date", "timestamp"])
    if date_col:
        try:
            work = work.sort_values(date_col)
        except Exception:
            pass
    if pos_col:
        work["pos_key"] = work[pos_col].fillna("").astype(str).str.upper()
    else:
        work["pos_key"] = ""

    agg_rows = []
    for (name_key, pos_key), grp in work.groupby(["name_key", "pos_key"], dropna=False):
        if not name_key:
            continue
        ecr = pd.to_numeric(grp[rank_col], errors="coerce").dropna().iloc[-1] if rank_col and pd.to_numeric(grp[rank_col], errors="coerce").notna().any() else np.nan
        adp = pd.to_numeric(grp[adp_col], errors="coerce").dropna().iloc[-1] if adp_col and pd.to_numeric(grp[adp_col], errors="coerce").notna().any() else np.nan
        agg_rows.append({"name_key": name_key, "pos_key": pos_key, "_ecr": ecr, "_adp": adp})
    ranks = pd.DataFrame(agg_rows)
    if ranks.empty:
        return master

    out = master.copy()
    out["name_key"] = out["player"].map(normalize_name)
    out["pos_key"] = out["position"].astype(str).str.upper()
    exact = out.merge(ranks, on=["name_key", "pos_key"], how="left")
    # Rankings sources sometimes omit position in the key; use name-only fallback.
    name_only = ranks.sort_values("_ecr").drop_duplicates("name_key", keep="first")[["name_key", "_ecr", "_adp"]]
    name_only = name_only.rename(columns={"_ecr": "_ecr_name", "_adp": "_adp_name"})
    exact = exact.merge(name_only, on="name_key", how="left")
    exact["ecr"] = exact["_ecr"].where(exact["_ecr"].notna(), exact["_ecr_name"])
    exact["ecr"] = exact["ecr"].fillna(master["ecr"].reset_index(drop=True))
    exact["adp"] = exact["_adp"].where(exact["_adp"].notna(), exact["_adp_name"])
    exact["adp"] = exact["adp"].fillna(master["adp"].reset_index(drop=True))
    return normalize_player_data(exact.drop(columns=["name_key", "pos_key", "_ecr", "_adp", "_ecr_name", "_adp_name"], errors="ignore"))


def load_nflverse_bundle(season: int, historical_season: Optional[int] = None) -> NflverseLoadResult:
    historical_season = int(historical_season or (season - 1))
    messages: list[str] = []
    loaded: dict[str, int] = {}
    try:
        import nflreadpy as nfl
    except Exception as exc:
        raise RuntimeError(
            "nflreadpy is not installed. Install requirements.txt, then retry the nflverse loader."
        ) from exc

    datasets: dict[str, pd.DataFrame] = {}
    specs = {
        "historical player stats": (getattr(nfl, "load_player_stats", None), historical_season),
        "current rosters": (getattr(nfl, "load_rosters", None), season),
        "injuries": (getattr(nfl, "load_injuries", None), season),
        "depth charts": (getattr(nfl, "load_depth_charts", None), season),
        "fantasy rankings": (getattr(nfl, "load_ff_rankings", None), season),
    }
    for label, (func, target_season) in specs.items():
        if func is None:
            messages.append(f"{label}: loader not available in installed nflreadpy version")
            datasets[label] = pd.DataFrame()
            continue
        frame, err = _try_loader(func, int(target_season))
        if err:
            messages.append(f"{label}: unavailable ({err})")
        frame = _filter_season(frame, int(target_season))
        if label == "historical player stats" and not frame.empty:
            season_type_col = _find_col(frame, ["season_type", "season_type_abbr"])
            if season_type_col is not None:
                reg = frame[frame[season_type_col].fillna("").astype(str).str.upper().isin(["REG", "REGULAR"])]
                if not reg.empty:
                    frame = reg
        datasets[label] = frame
        loaded[label] = len(frame)

    historical = _aggregate_historical_stats(datasets["historical player stats"])
    master = _build_roster_master(datasets["current rosters"], historical)
    master = _merge_latest_status(master, datasets["injuries"], "injury")
    master = _merge_latest_status(master, datasets["depth charts"], "depth")
    master = _merge_ff_rankings(master, datasets["fantasy rankings"])
    if not master.empty:
        master["data_source"] = f"nflverse {historical_season} stats + {season} roster/status"
    return NflverseLoadResult(players=master, messages=messages, loaded=loaded)


def _projection_column(df: pd.DataFrame) -> Optional[str]:
    return _find_col(df, ["projection", "projected_points", "proj", "projected_fantasy_points", "fpts", "points"])


def blend_projection_sources(
    master: pd.DataFrame,
    sources: list[tuple[str, pd.DataFrame, float]],
    baseline_projection: Optional[pd.Series] = None,
    baseline_weight: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Blend multiple uploaded projection/ADP sources by normalized player name.

    Returns (updated master, audit table). Each source needs a player/name column and
    a projection column; position is optional. ADP and ECR are blended when present.
    """
    out = normalize_player_data(master).copy()
    out["name_key"] = out["player"].map(normalize_name)
    out["pos_key"] = out["position"].astype(str).str.upper()

    proj_num = pd.Series(0.0, index=out.index)
    proj_den = pd.Series(0.0, index=out.index)
    adp_num = pd.Series(0.0, index=out.index)
    adp_den = pd.Series(0.0, index=out.index)
    ecr_num = pd.Series(0.0, index=out.index)
    ecr_den = pd.Series(0.0, index=out.index)

    if baseline_projection is not None and baseline_weight > 0:
        base = pd.to_numeric(pd.Series(baseline_projection).reset_index(drop=True), errors="coerce")
        mask = base.notna()
        proj_num.loc[mask] += base.loc[mask] * float(baseline_weight)
        proj_den.loc[mask] += float(baseline_weight)

    audits = []
    for source_name, frame, weight in sources:
        weight = float(weight)
        if weight <= 0 or frame is None or len(frame) == 0:
            continue
        f = frame.copy()
        name_col = _find_col(f, ["player", "name", "player_name", "player_display_name", "full_name"])
        proj_col = _projection_column(f)
        if name_col is None or proj_col is None:
            audits.append({"source": source_name, "weight": weight, "rows": len(f), "matched": 0, "note": "missing player or projection column"})
            continue
        pos_col = _find_col(f, ["position", "pos", "fantpos"])
        adp_col = _find_col(f, ["adp", "average_draft_position", "avg_pick"])
        ecr_col = _find_col(f, ["ecr", "rank", "overall_rank"])
        f["name_key"] = f[name_col].fillna("").map(normalize_name)
        f["pos_key"] = f[pos_col].fillna("").astype(str).str.upper() if pos_col else ""
        f["_proj"] = pd.to_numeric(f[proj_col], errors="coerce")
        f["_adp"] = pd.to_numeric(f[adp_col], errors="coerce") if adp_col else np.nan
        f["_ecr"] = pd.to_numeric(f[ecr_col], errors="coerce") if ecr_col else np.nan
        f = f[f["name_key"].ne("")].copy()
        f = f.sort_values("_proj", ascending=False).drop_duplicates(["name_key", "pos_key"], keep="first")

        exact = out[["name_key", "pos_key"]].merge(
            f[["name_key", "pos_key", "_proj", "_adp", "_ecr"]], on=["name_key", "pos_key"], how="left"
        )
        name_only = f.sort_values("_proj", ascending=False).drop_duplicates("name_key", keep="first")
        fallback = out[["name_key"]].merge(name_only[["name_key", "_proj", "_adp", "_ecr"]], on="name_key", how="left")
        for metric in ["_proj", "_adp", "_ecr"]:
            exact[metric] = exact[metric].where(exact[metric].notna(), fallback[metric])

        p = exact["_proj"]
        mask = p.notna()
        proj_num.loc[mask] += p.loc[mask].to_numpy() * weight
        proj_den.loc[mask] += weight
        a = exact["_adp"]
        mask_a = a.notna()
        adp_num.loc[mask_a] += a.loc[mask_a].to_numpy() * weight
        adp_den.loc[mask_a] += weight
        e = exact["_ecr"]
        mask_e = e.notna()
        ecr_num.loc[mask_e] += e.loc[mask_e].to_numpy() * weight
        ecr_den.loc[mask_e] += weight
        audits.append({"source": source_name, "weight": weight, "rows": len(frame), "matched": int(mask.sum()), "note": "ok"})

    blended_proj = proj_num / proj_den.replace(0, np.nan)
    blended_adp = adp_num / adp_den.replace(0, np.nan)
    blended_ecr = ecr_num / ecr_den.replace(0, np.nan)
    out["projection"] = blended_proj.where(blended_proj.notna(), out["projection"])
    out["adp"] = blended_adp.where(blended_adp.notna(), out["adp"])
    out["ecr"] = blended_ecr.where(blended_ecr.notna(), out["ecr"])
    out["data_source"] = out["data_source"].astype(str).str.strip() + np.where(proj_den.gt(0), " + blended projections", "")
    return normalize_player_data(out.drop(columns=["name_key", "pos_key"], errors="ignore")), pd.DataFrame(audits)
