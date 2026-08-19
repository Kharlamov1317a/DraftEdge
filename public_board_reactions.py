from __future__ import annotations

from functools import lru_cache
import random
import re
from typing import Any

import requests

from special_teams_support import normalize_position


GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"

CURATED_MEMES: dict[str, list[str]] = {
    "highway_robbery": ["leonardo dicaprio cheers", "chef kiss", "stonks", "big brain"],
    "steal": ["robert redford nod", "leonardo dicaprio cheers", "well played", "chef kiss"],
    "good_value": ["approval nod", "nice very nice", "leonardo dicaprio pointing"],
    "minor_reach": ["confused nick young", "side eye monkey puppet", "interesting choice"],
    "reach": ["facepalm", "confused nick young", "bold strategy cotton", "shocked pikachu"],
    "massive_reach": ["michael scott no god please no", "facepalm", "what are you doing", "shocked pikachu"],
    "early_qb": ["bold strategy cotton", "big brain", "power move"],
    "qb_hoarder": ["another one dj khaled", "more kylo ren", "gotta catch em all"],
    "early_te": ["interesting choice", "spicy", "hmm suspicious"],
    "rookie_hype": ["hype train", "lets go", "crowd cheering"],
    "position_run": ["everybody stay calm office", "here we go again cj", "everybody panic"],
    "position_hoarder": ["another one dj khaled", "gotta catch em all", "more kylo ren"],
    "team_stack": ["avengers assemble", "dynamic duo", "perfectly balanced thanos"],
    "nfl_team_homer": ["one of us", "fanboy", "another one dj khaled"],
    "roster_need_ignored": ["this is fine", "michael jackson popcorn", "ignore problem"],
    "late_sleeper": ["lottery ticket", "let him cook", "fingers crossed"],
    "early_kicker": ["michael jackson popcorn", "confused nick young", "bold strategy cotton", "what are you doing"],
    "early_dst": ["this is fine", "michael jackson popcorn", "everybody stay calm office", "confused nick young"],
    "kicker_run": ["another one dj khaled", "everybody panic", "here we go again cj"],
    "dst_run": ["avengers assemble", "everybody panic", "here we go again cj"],
    "special_teams_late": ["adulting", "robert redford nod", "respect", "job done"],
    "default": ["leonardo dicaprio pointing", "michael jackson popcorn", "robert redford nod"],
}

FRESH_QUERIES = {
    key: [f"{key.replace('_', ' ')} funny reaction", f"fantasy football {key.replace('_', ' ')} reaction"]
    for key in CURATED_MEMES
}

TITLES = {
    "highway_robbery": "🚨 Highway Robbery",
    "steal": "💰 Steal Alert",
    "good_value": "📈 Nice Value",
    "minor_reach": "🤨 A Little Spicy",
    "reach": "😂 Reach Watch",
    "massive_reach": "🚨 We Need to Talk",
    "early_qb": "🧠 Early QB Energy",
    "qb_hoarder": "🏈 Another Quarterback?!",
    "early_te": "🌶️ Spicy Tight End Pick",
    "rookie_hype": "🚂 Rookie Hype Train",
    "position_run": "🏃 Position Run!",
    "position_hoarder": "🛒 Position Hoarder",
    "team_stack": "🤝 Stack Attack",
    "nfl_team_homer": "📣 Homer Alert",
    "roster_need_ignored": "🙈 Roster Need? Never Heard of It",
    "late_sleeper": "🎲 Late-Round Lottery Ticket",
    "early_kicker": "🦵 Kicker Already?!",
    "early_dst": "🛡️ Defense Before Dessert",
    "kicker_run": "🦵 Kicker Run!",
    "dst_run": "🛡️ D/ST Run!",
    "special_teams_late": "✅ Special Teams Business",
    "default": "📣 Draft Room Reaction",
}

LINES = {
    "highway_robbery": ["{owner} just stole {player}. Please secure all valuables before the next pick."],
    "steal": ["{owner} lands {player}. The rest of the room may want to review how that was allowed."],
    "good_value": ["{owner} gets {player}. Sensible, efficient, irritating."],
    "minor_reach": ["{owner} takes {player}. A little early, but confidence is free."],
    "reach": ["{owner} selected {player}. Bold. Courageous. Potentially screenshot-worthy."],
    "massive_reach": ["{owner} launched {player} up the board. ADP has left the chat."],
    "early_qb": ["{owner} grabbed {player} early. Quarterback confidence is officially off the charts."],
    "qb_hoarder": ["{owner} adds another quarterback in {player}. Apparently one was not enough."],
    "early_te": ["{owner} takes {player}. Spicy. Slightly dangerous. Excellent television."],
    "rookie_hype": ["{owner} hit the rookie hype button with {player}."],
    "position_run": ["{owner} takes {player} and keeps the {position} run alive. EVERYBODY STAY CALM."],
    "position_hoarder": ["{owner} adds ANOTHER {position} with {player}. Save some for the rest of us."],
    "team_stack": ["{owner} adds {player} and completes a same-team fantasy stack."],
    "nfl_team_homer": ["{owner} adds yet another {team} player in {player}. The homer allegations now have exhibits."],
    "roster_need_ignored": ["{owner} takes {player} while another starting spot sits empty. Future {owner} can deal with that."],
    "late_sleeper": ["{owner} fires a late-round dart at {player}. May the waiver gods stay away."],
    "early_kicker": [
        "{owner} just drafted {player}. The kicker button has been pressed with plenty of draft left.",
        "{owner} takes {player}. We have apparently reached the kicking portion of the program early.",
    ],
    "early_dst": [
        "{owner} selects {player}. Streaming defenses was apparently never part of the plan.",
        "{owner} drafts {player}. Defense wins championships; timing remains under investigation.",
    ],
    "kicker_run": ["{owner} takes {player}. The kicker run is real and nobody knows how to feel about it."],
    "dst_run": ["{owner} grabs {player}. The D/ST shelves are being cleared in real time."],
    "special_teams_late": [
        "{owner} takes {player}. Responsible late-round roster maintenance has occurred.",
        "{owner} adds {player}. Not glamorous, but the lineup now has all its required parts.",
    ],
    "default": ["{owner} selected {player}. The board moves, the tension rises."],
}

OWNER_JABS = [
    "{owner}, the receipts are being saved.",
    "{owner} will be hearing about this pick at least once a week.",
    "Somewhere, {owner} is nodding like a mastermind.",
]


def _tokenize(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", str(text).lower()) if len(x) > 2}


@lru_cache(maxsize=256)
def _search_giphy(query: str, api_key: str) -> tuple[dict[str, str], ...]:
    if not query or not api_key:
        return tuple()
    try:
        response = requests.get(
            GIPHY_SEARCH_URL,
            params={"api_key": api_key, "q": query[:50], "limit": 15, "rating": "pg", "lang": "en"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return tuple()
    rows = []
    for item in payload.get("data", []):
        images = item.get("images") or {}
        image = images.get("fixed_height") or images.get("downsized") or images.get("original") or {}
        url = str(image.get("url") or "").strip()
        if url:
            rows.append({"id": str(item.get("id") or ""), "url": url, "title": str(item.get("title") or query)})
    return tuple(rows)


def _gif(category: str, api_key: str, recent: list[str], curated_bias: int) -> dict[str, str]:
    if not api_key:
        return {}
    curated = random.randint(1, 100) <= max(0, min(int(curated_bias), 100))
    pool = CURATED_MEMES if curated else FRESH_QUERIES
    queries = list(pool.get(category) or pool["default"])
    random.shuffle(queries)
    recent_set = {str(x) for x in recent}
    for query in queries[:2]:
        candidates = list(_search_giphy(query, api_key))
        if not candidates:
            continue
        q_tokens = _tokenize(query)
        scored = []
        for i, item in enumerate(candidates):
            overlap = len(q_tokens & _tokenize(item.get("title", "")))
            score = (15 - i) + 4 * overlap - (100 if item.get("id") in recent_set else 0)
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        viable = [item for score, item in scored if score > -50][:3] or [item for _, item in scored[:3]]
        if viable:
            chosen = random.choice(viable)
            return {**chosen, "query": query, "selection_mode": "curated" if curated else "fresh"}
    return {}


def _context_category(pick: dict[str, Any], history: list[dict[str, Any]], league: dict[str, Any]) -> str | None:
    pos = normalize_position(pick.get("position") or "")
    slot = int(pick.get("slot") or 0)
    round_no = int(pick.get("round") or 0)
    owner_history = [p for p in history if int(p.get("slot") or 0) == slot]
    owner_positions = [normalize_position(p.get("position") or "") for p in owner_history]

    recent_positions = [normalize_position(p.get("position") or "") for p in history[-4:]]
    if pos == "K" and recent_positions.count("K") >= 2:
        return "kicker_run"
    if pos == "DST" and recent_positions.count("DST") >= 2:
        return "dst_run"

    late_window = max(1, int(league.get("rounds") or 16) - 4)
    if pos == "K":
        return "special_teams_late" if round_no >= late_window else "early_kicker"
    if pos == "DST":
        return "special_teams_late" if round_no >= late_window else "early_dst"

    if pos == "QB" and owner_positions.count("QB") >= 2:
        return "qb_hoarder"
    if pos and owner_positions.count(pos) >= (3 if pos in {"RB", "WR"} else 2):
        return "position_hoarder"
    if pos and recent_positions.count(pos) >= 3:
        return "position_run"

    team = str(pick.get("nfl_team") or "").upper()
    owner_teams = [str(p.get("nfl_team") or "").upper() for p in owner_history]
    if team and pos in {"QB", "WR", "TE"}:
        for prior in owner_history:
            pp = normalize_position(prior.get("position") or "")
            if str(prior.get("nfl_team") or "").upper() == team and ((pos == "QB" and pp in {"WR", "TE"}) or (pp == "QB" and pos in {"WR", "TE"})):
                return "team_stack"
    if team and owner_teams.count(team) >= 2:
        return "nfl_team_homer"
    if pos == "QB" and 1 <= round_no <= 3:
        return "early_qb"
    if pos == "TE" and 1 <= round_no <= 4:
        return "early_te"
    if bool(pick.get("is_rookie")) and 1 <= round_no <= 8:
        return "rookie_hype"
    return None


def classify_pick(pick: dict[str, Any], history: list[dict[str, Any]], league: dict[str, Any], quality_mode: bool) -> str:
    contextual = _context_category(pick, history, league)
    if contextual:
        return contextual
    if quality_mode:
        deltas = []
        for key in ["rank_delta", "adp_delta"]:
            try:
                if pick.get(key) is not None:
                    deltas.append(float(pick[key]))
            except Exception:
                pass
        if deltas:
            if max(deltas) >= 25:
                return "highway_robbery"
            if min(deltas) <= -25:
                return "massive_reach"
            if max(deltas) >= 12:
                return "steal"
            if min(deltas) <= -12:
                return "reach"
            if max(deltas) >= 6:
                return "good_value"
            if min(deltas) <= -6:
                return "minor_reach"
    return "late_sleeper" if int(pick.get("round") or 0) >= 10 else "default"


def make_pick_reaction(
    pick: dict[str, Any],
    slot_to_owner: dict[int, str],
    *,
    draft_history: list[dict[str, Any]] | None = None,
    league_config: dict[str, Any] | None = None,
    owner_banter_enabled: bool = True,
    quality_mode: bool = True,
    gif_api_key: str = "",
    gif_frequency: int = 55,
    recent_gif_ids: list[str] | None = None,
    curated_gif_bias: int = 75,
) -> dict[str, str]:
    history = list(draft_history or [])
    league = dict(league_config or {})
    slot = int(pick.get("slot") or 0)
    owner = slot_to_owner.get(slot, f"Team {slot}")
    values = {
        "owner": owner,
        "player": str(pick.get("player") or "this pick"),
        "position": normalize_position(pick.get("position") or ""),
        "team": str(pick.get("nfl_team") or ""),
        "pick_no": int(pick.get("pick") or 0),
        "round_no": int(pick.get("round") or 0),
    }
    category = classify_pick(pick, history, league, quality_mode)
    line = random.choice(LINES.get(category) or LINES["default"]).format(**values)
    sub = f"{values['position']} · {values['team']} · Round {values['round_no']}, pick {values['pick_no']}."
    if owner_banter_enabled and random.random() < 0.55:
        sub += " " + random.choice(OWNER_JABS).format(owner=owner)

    selected = {}
    if gif_api_key and random.randint(1, 100) <= max(0, min(int(gif_frequency), 100)):
        selected = _gif(category, gif_api_key, list(recent_gif_ids or []), curated_gif_bias)
    return {
        "category": category,
        "kicker": TITLES.get(category, TITLES["default"]),
        "line": line,
        "sub": sub,
        "gif_id": selected.get("id", ""),
        "gif_url": selected.get("url", ""),
        "gif_title": selected.get("title", ""),
        "gif_query": selected.get("query", ""),
        "gif_selection_mode": selected.get("selection_mode", ""),
    }
