from __future__ import annotations

from functools import lru_cache
import random
import re
from typing import Any

import requests


GIPHY_SEARCH_URL = "https://api.giphy.com/v2/search"
GIPHY_CLIENT_KEY = "draftedge-public-board"

# Exact, recognizable meme families. These are searched by name rather than by
# a generic emotion so the returned GIFs are more likely to be familiar.
CURATED_MEMES: dict[str, list[str]] = {
    "highway_robbery": [
        "leonardo dicaprio cheers",
        "vince mcmahon impressed",
        "chef kiss",
        "stonks",
        "big brain galaxy brain",
    ],
    "steal": [
        "leonardo dicaprio cheers",
        "chef kiss",
        "robert redford nod",
        "well played",
        "big brain",
    ],
    "good_value": [
        "robert redford nod",
        "nice very nice",
        "leonardo dicaprio pointing",
        "approval nod",
    ],
    "minor_reach": [
        "confused nick young",
        "hmm suspicious",
        "side eye monkey puppet",
        "interesting choice",
    ],
    "reach": [
        "confused nick young",
        "awkward monkey puppet",
        "facepalm",
        "bold strategy cotton",
        "shocked pikachu",
    ],
    "massive_reach": [
        "michael scott no god please no",
        "shocked pikachu",
        "facepalm",
        "confused nick young",
        "what are you doing",
    ],
    "early_qb": [
        "bold strategy cotton",
        "big brain",
        "vince mcmahon impressed",
        "power move",
    ],
    "qb_hoarder": [
        "another one dj khaled",
        "more kylo ren",
        "collect them all",
        "why not both",
    ],
    "early_te": [
        "interesting choice",
        "spicy",
        "hmm suspicious",
        "bold strategy cotton",
    ],
    "rookie_hype": [
        "hype train",
        "lets go",
        "vince mcmahon excited",
        "crowd cheering",
    ],
    "early_k_dst": [
        "michael jackson popcorn",
        "confused nick young",
        "this is fine",
        "what are you doing",
    ],
    "position_run": [
        "panic everybody stay calm office",
        "here we go again cj",
        "rush hour",
        "everybody panic",
    ],
    "position_hoarder": [
        "another one dj khaled",
        "gotta catch em all",
        "more kylo ren",
        "hoarding",
    ],
    "team_stack": [
        "avengers assemble",
        "dynamic duo",
        "perfectly balanced thanos",
        "teamwork makes dream work",
    ],
    "nfl_team_homer": [
        "one of us one of us",
        "fanboy",
        "another one dj khaled",
        "loyalty",
    ],
    "roster_need_ignored": [
        "this is fine",
        "michael jackson popcorn",
        "bold strategy cotton",
        "ignore problem",
    ],
    "late_sleeper": [
        "lottery ticket",
        "fingers crossed",
        "let him cook",
        "diamond in the rough",
    ],
    "splash": [
        "mind blown",
        "vince mcmahon excited",
        "shocked reaction",
        "lets go",
    ],
    "safe": [
        "robert redford nod",
        "respect",
        "solid choice",
        "approval nod",
    ],
    "default": [
        "leonardo dicaprio pointing",
        "michael jackson popcorn",
        "robert redford nod",
        "funny sports reaction",
    ],
}

# Fresh searches keep some variety. The hybrid selector uses these roughly 25%
# of the time by default.
FRESH_QUERIES: dict[str, list[str]] = {
    "highway_robbery": ["fantasy football steal reaction", "amazing value reaction"],
    "steal": ["great pick reaction", "smart move reaction"],
    "good_value": ["nice pick reaction", "good choice reaction"],
    "minor_reach": ["questionable decision reaction", "hmm reaction"],
    "reach": ["bad decision reaction", "are you serious reaction"],
    "massive_reach": ["disaster reaction", "what just happened reaction"],
    "early_qb": ["bold move reaction", "quarterback hype reaction"],
    "qb_hoarder": ["another one reaction", "too many reaction"],
    "early_te": ["spicy choice reaction", "interesting reaction"],
    "rookie_hype": ["hype reaction", "future star reaction"],
    "early_k_dst": ["chaos reaction", "why reaction"],
    "position_run": ["panic buying reaction", "everybody panic reaction"],
    "position_hoarder": ["hoarding reaction", "more more more reaction"],
    "team_stack": ["team up reaction", "perfect combo reaction"],
    "nfl_team_homer": ["superfan reaction", "loyal fan reaction"],
    "roster_need_ignored": ["ignore the problem reaction", "this is fine reaction"],
    "late_sleeper": ["lottery ticket reaction", "sleeper pick reaction"],
    "splash": ["mind blown reaction", "huge pick reaction"],
    "safe": ["respect reaction", "good pick reaction"],
    "default": ["funny draft reaction", "sports reaction"],
}

TITLES = {
    "highway_robbery": "🚨 HIGHWAY ROBBERY",
    "steal": "💰 Steal Alert",
    "good_value": "📈 Nice Value",
    "minor_reach": "🤨 A Little Spicy",
    "reach": "😂 Reach Watch",
    "massive_reach": "🚨 We Need to Talk",
    "early_qb": "🧠 Early QB Energy",
    "qb_hoarder": "🏈 Another Quarterback?!",
    "early_te": "🌶️ Spicy Tight End Pick",
    "rookie_hype": "🚂 Rookie Hype Train",
    "early_k_dst": "🍿 Chaos Pick",
    "position_run": "🏃 Position Run!",
    "position_hoarder": "🛒 Position Hoarder",
    "team_stack": "🤝 Stack Attack",
    "nfl_team_homer": "📣 Homer Alert",
    "roster_need_ignored": "🙈 Roster Need? Never Heard of It",
    "late_sleeper": "🎲 Late-Round Lottery Ticket",
    "splash": "🤯 Big Splash Pick",
    "safe": "👏 Respectable Business",
    "default": "📣 Draft Room Reaction",
}

LINES: dict[str, list[str]] = {
    "highway_robbery": [
        "{owner} just got {player} at pick {pick_no}. Someone check whether trades are happening under the table.",
        "{owner} lands {player}. The rest of the room may want to review how this was allowed.",
        "{owner} just stole {player}. Please secure all valuables before the next pick.",
    ],
    "steal": [
        "{owner} may have just robbed the room with {player}.",
        "{owner} grabbed {player} and the rest of the league immediately got quieter.",
        "{owner} lands {player}. Annoyingly good value.",
    ],
    "good_value": [
        "{owner} gets {player}. That's the kind of value nobody enjoys seeing an opponent get.",
        "{owner} takes {player}. Sensible, efficient, irritating.",
        "{owner} adds {player}. The value spreadsheet approves.",
    ],
    "minor_reach": [
        "{owner} goes with {player}. A little early, but confidence is free.",
        "{owner} takes {player}. Not outrageous... but the eyebrow has been raised.",
        "{owner} selects {player}. Spicy enough to get the room talking.",
    ],
    "reach": [
        "{owner} selected {player}. Bold. Courageous. Potentially screenshot-worthy.",
        "{owner} went with {player}. The group chat is now conducting peer review.",
        "{owner} just took {player}. That's either visionary or future roast material.",
    ],
    "massive_reach": [
        "{owner} took {player} WAY ahead of schedule. The draft board has requested a wellness check.",
        "{owner} just launched {player} up the board. ADP has left the chat.",
        "{owner} picked {player}. We respect the conviction. The numbers are filing an appeal.",
    ],
    "early_qb": [
        "{owner} grabbed {player} early. Quarterback confidence levels are officially off the charts.",
        "{owner} drafted {player}. Early-QB truthers, your moment has arrived.",
        "{owner} takes {player}. Heroic music has started playing for some reason.",
    ],
    "qb_hoarder": [
        "{owner} drafts another quarterback in {player}. Apparently one was simply not enough.",
        "{owner} adds {player}. The QB room now requires its own parking lot.",
        "{owner} takes {player}. Quarterbacks are being collected like infinity stones.",
    ],
    "early_te": [
        "{owner} goes for {player}. Tight-end premium or just premium confidence?",
        "{owner} takes {player}. Spicy. Slightly dangerous. Excellent television.",
        "{owner} selected {player}. The room has questions, but also curiosity.",
    ],
    "rookie_hype": [
        "{owner} hit the rookie hype button with {player}.",
        "{owner} chose {player}. Hope, upside, and highlight-reel dreams are now in play.",
        "{owner} drafted {player}. The rookie propaganda has worked.",
    ],
    "early_k_dst": [
        "{owner} selected {player}. We appear to have entered the chaos portion of the draft early.",
        "{owner} takes {player}. Kicker/defense truthers have breached the perimeter.",
        "{owner} drafted {player}. The room is now legally required to react.",
    ],
    "position_run": [
        "{owner} takes {player} and keeps the {position} run alive. EVERYBODY STAY CALM.",
        "Another {position}! {owner} joins the stampede with {player}.",
        "{owner} drafts {player}. The {position} shelves are being cleared in real time.",
    ],
    "position_hoarder": [
        "{owner} adds ANOTHER {position} with {player}. Save some for the rest of us.",
        "{owner} drafts {player}. At this point the {position} room has a waiting list.",
        "{owner} takes {player}. Apparently the roster strategy is 'all of them.'",
    ],
    "team_stack": [
        "{owner} adds {player} and completes a same-team fantasy stack. Chemistry experiment underway.",
        "{owner} drafts {player}. The stack is assembled; now we wait for touchdowns.",
        "{owner} pairs up with {player}. Correlated scoring enthusiasts are nodding approvingly.",
    ],
    "nfl_team_homer": [
        "{owner} adds yet another {team} player in {player}. The homer allegations now have exhibits.",
        "{owner} drafts {player}. At this rate, just buy a {team} season ticket.",
        "{owner} takes {player}. The {team} fan club has apparently sponsored this roster.",
    ],
    "roster_need_ignored": [
        "{owner} takes {player} while another starting spot sits empty. Future {owner} can deal with that.",
        "{owner} drafts {player}. Roster construction has been politely asked to wait outside.",
        "{owner} adds {player}. Needs are temporary; vibes are forever.",
    ],
    "late_sleeper": [
        "{owner} fires a late-round dart at {player}. May the waiver gods stay away.",
        "{owner} selected {player}. We're officially buying lottery tickets with roster spots.",
        "{owner} adds {player}. Low cost, high imagination.",
    ],
    "splash": [
        "{owner} just sent the room into orbit with {player}.",
        "{owner} slammed the button on {player}. That pick has main-character energy.",
        "{owner} gets {player}. The room is reacting in real time.",
    ],
    "safe": [
        "{owner} took {player}. Clean pick. Strong pick. Very little for the haters to work with.",
        "{owner} picked {player}. Nobody is shocked, but everybody respects it.",
        "{owner} adds {player}. A sturdy, annoyingly sensible move.",
    ],
    "default": [
        "{owner} selected {player}. The board moves, the tension rises.",
        "{owner} drafted {player}. The room reacts, as it should.",
        "{owner} adds {player}. Another piece has hit the board.",
    ],
}

SUBLINES: dict[str, list[str]] = {
    category: [
        "{position} · {team} · Round {round_no}, pick {pick_no}.",
        "The draft board will remember this.",
    ]
    for category in TITLES
}
SUBLINES.update({
    "highway_robbery": ["The value meter just broke.", "Somewhere, an ADP list is crying."],
    "massive_reach": ["We respect the bravery. The receipts are being laminated.", "This pick has future group-chat potential."],
    "position_run": ["The positional run alarm is officially sounding.", "Scarcity panic has entered the room."],
    "position_hoarder": ["Roster diversification has left the building.", "Depth chart: yes."],
    "team_stack": ["Same-team correlation unlocked.", "If the offense hits, the victory lap will be unbearable."],
    "nfl_team_homer": ["Team loyalty: elite. Objectivity: under investigation.", "The fandom is no longer subtle."],
    "roster_need_ignored": ["Needs can wait. Apparently.", "The roster puzzle is getting interesting."],
    "late_sleeper": ["Late-round dreams are free.", "This is where legends—or waiver drops—are born."],
})

OWNER_JABS = [
    "{owner}, the receipts are being saved.",
    "{owner} will be hearing about this pick at least once a week.",
    "{owner}'s confidence is currently measurable from space.",
    "Somewhere, {owner} is nodding like a mastermind.",
]


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _owner_history(draft_history: list[dict[str, Any]], slot: int) -> list[dict[str, Any]]:
    return [p for p in draft_history if int(p.get("slot") or 0) == slot]


def _detect_context_category(
    pick: dict[str, Any],
    draft_history: list[dict[str, Any]],
    league_config: dict[str, Any] | None,
) -> str | None:
    slot = int(pick.get("slot") or 0)
    position = str(pick.get("position") or "").upper()
    nfl_team = str(pick.get("nfl_team") or "").upper()
    round_no = int(pick.get("round") or 0)
    owner_history = _owner_history(draft_history, slot)

    owner_positions = [str(p.get("position") or "").upper() for p in owner_history]
    owner_teams = [str(p.get("nfl_team") or "").upper() for p in owner_history]

    # Same-team QB + pass-catcher stack.
    if nfl_team and position in {"QB", "WR", "TE"}:
        for prior in owner_history:
            prior_pos = str(prior.get("position") or "").upper()
            prior_team = str(prior.get("nfl_team") or "").upper()
            if prior_team != nfl_team:
                continue
            if position == "QB" and prior_pos in {"WR", "TE"}:
                return "team_stack"
            if position in {"WR", "TE"} and prior_pos == "QB":
                return "team_stack"

    # Third player from one NFL team = homer alert (unless stack got priority).
    if nfl_team and owner_teams.count(nfl_team) >= 2:
        return "nfl_team_homer"

    # A fourth RB/WR or third QB/TE is enough to trigger a hoarder joke.
    hoard_threshold = 3 if position in {"RB", "WR"} else 2
    if position and owner_positions.count(position) >= hoard_threshold:
        if position == "QB":
            return "qb_hoarder"
        return "position_hoarder"

    # Position run: current pick makes 4 of the last 5 picks at one position.
    recent = draft_history[-4:]
    if position and len(recent) >= 3:
        recent_positions = [str(p.get("position") or "").upper() for p in recent]
        if recent_positions.count(position) >= 3:
            return "position_run"

    if position in {"K", "DST", "DEF"} and 1 <= round_no <= 11:
        return "early_k_dst"
    if position == "QB" and 1 <= round_no <= 3:
        return "early_qb"
    if position == "TE" and 1 <= round_no <= 4:
        return "early_te"

    is_rookie = bool(pick.get("is_rookie") or pick.get("rookie"))
    if is_rookie and 1 <= round_no <= 8:
        return "rookie_hype"

    # Lightweight roster-need detector: taking extra depth while a common core
    # starting position is still empty. It is intentionally conservative.
    cfg = league_config or {}
    if 4 <= round_no <= 9 and position in {"RB", "WR", "TE", "QB"}:
        required = {
            "QB": int(cfg.get("qb") or 0),
            "RB": int(cfg.get("rb") or 0),
            "WR": int(cfg.get("wr") or 0),
            "TE": int(cfg.get("te") or 0),
        }
        missing_core = [pos for pos, need in required.items() if need > 0 and owner_positions.count(pos) < need]
        current_need = required.get(position, 0)
        if missing_core and owner_positions.count(position) >= max(2, current_need + 1):
            return "roster_need_ignored"

    return None


def classify_pick(
    pick: dict[str, Any],
    *,
    draft_history: list[dict[str, Any]] | None = None,
    league_config: dict[str, Any] | None = None,
    quality_mode: bool = True,
) -> str:
    history = list(draft_history or [])

    # Contextual jokes get priority because they are more specific to what is
    # actually happening in the room.
    contextual = _detect_context_category(pick, history, league_config)
    if contextual:
        return contextual

    round_no = int(pick.get("round") or 0)
    rank_delta = _float(pick.get("rank_delta"))
    adp_delta = _float(pick.get("adp_delta"))

    if quality_mode:
        deltas = [d for d in (rank_delta, adp_delta) if d is not None]
        if deltas:
            best = max(deltas)
            worst = min(deltas)
            if best >= 25:
                return "highway_robbery"
            if worst <= -25:
                return "massive_reach"
            if best >= 12:
                return "steal"
            if worst <= -12:
                return "reach"
            if best >= 6:
                return "good_value"
            if worst <= -6:
                return "minor_reach"

    if round_no >= 10:
        return "late_sleeper"
    if 1 <= round_no <= 2:
        return "splash"
    if 3 <= round_no <= 8:
        return "safe"
    return "default"


def _tokenize(text: str) -> set[str]:
    stop = {"meme", "gif", "reaction", "the", "a", "an", "and", "of", "to", "is"}
    return {t for t in re.findall(r"[a-z0-9]+", str(text).lower()) if len(t) > 2 and t not in stop}


def _score_gif_candidate(item: dict[str, Any], query: str, index: int, recent_ids: set[str]) -> float:
    gif_id = str(item.get("id") or "")
    desc = str(item.get("content_description") or item.get("title") or "")
    query_tokens = _tokenize(query)
    desc_tokens = _tokenize(desc)
    overlap = len(query_tokens & desc_tokens)

    # GIPHY's search order is useful, so start with a rank bonus and then add
    # title/description relevance. Recently used GIFs receive a large penalty.
    score = max(0.0, 12.0 - float(index)) + (overlap * 4.0)
    if gif_id and gif_id in recent_ids:
        score -= 100.0
    if not desc.strip():
        score -= 1.0
    return score


@lru_cache(maxsize=256)
def search_giphy_candidates(query: str, api_key: str) -> tuple[dict[str, str], ...]:
    """Fetch a small ranked GIPHY candidate set using its Tenor-compatible API."""
    if not str(api_key or "").strip() or not str(query or "").strip():
        return tuple()
    params = {
        "key": api_key,
        "q": str(query)[:50],
        "client_key": GIPHY_CLIENT_KEY,
        "limit": 16,
        "contentfilter": "medium",
        "media_filter": "gif,tinygif",
        "country": "US",
        "locale": "en_US",
    }
    try:
        response = requests.get(GIPHY_SEARCH_URL, params=params, timeout=8)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return tuple()

    choices: list[dict[str, str]] = []
    for item in payload.get("results", []):
        media_formats = item.get("media_formats") or {}
        media = media_formats.get("gif") or media_formats.get("tinygif") or {}
        url = str(media.get("url") or "").strip()
        if not url:
            continue
        choices.append({
            "id": str(item.get("id") or ""),
            "url": url,
            "title": str(item.get("content_description") or item.get("title") or query),
        })
    return tuple(choices)


def select_reaction_gif(
    category: str,
    api_key: str,
    *,
    recent_gif_ids: list[str] | None = None,
    curated_bias: int = 75,
) -> dict[str, str]:
    if not str(api_key or "").strip():
        return {}

    curated_bias = max(0, min(int(curated_bias), 100))
    use_curated = random.randint(1, 100) <= curated_bias
    query_pool = CURATED_MEMES if use_curated else FRESH_QUERIES
    queries = list(query_pool.get(category) or query_pool["default"])
    random.shuffle(queries)
    recent = {str(x) for x in (recent_gif_ids or []) if str(x)}

    # Try two different meme families before giving up. This improves relevance
    # without burning excessive API calls (results are cached per query/key).
    for query in queries[:2]:
        candidates = list(search_giphy_candidates(query, api_key))
        if not candidates:
            continue

        scored: list[tuple[float, dict[str, str]]] = []
        for idx, item in enumerate(candidates):
            score = _score_gif_candidate(item, query, idx, recent)
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        # Select from the best three non-recent results so the same query still
        # has visual variety across a long draft.
        viable = [item for score, item in scored if score > -50][:3]
        if not viable:
            viable = [item for _, item in scored[:3]]
        if viable:
            selected = random.choice(viable)
            return {
                **selected,
                "query": query,
                "selection_mode": "curated" if use_curated else "fresh",
            }
    return {}


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
    slot = int(pick.get("slot") or 0)
    owner = slot_to_owner.get(slot, f"Team {slot}")
    player = str(pick.get("player") or "this player")
    position = str(pick.get("position") or "")
    team = str(pick.get("nfl_team") or "")
    pick_no = int(pick.get("pick") or 0)
    round_no = int(pick.get("round") or 0)

    category = classify_pick(
        pick,
        draft_history=draft_history,
        league_config=league_config,
        quality_mode=quality_mode,
    )
    values = {
        "owner": owner,
        "player": player,
        "position": position,
        "team": team,
        "pick_no": pick_no,
        "round_no": round_no,
    }
    line = random.choice(LINES.get(category) or LINES["default"]).format(**values)
    sub = random.choice(SUBLINES.get(category) or SUBLINES["default"]).format(**values)
    if owner_banter_enabled and random.random() < 0.65:
        sub = f"{sub} {random.choice(OWNER_JABS).format(owner=owner)}".strip()

    gif: dict[str, str] = {}
    if str(gif_api_key or "").strip() and random.randint(1, 100) <= max(0, min(int(gif_frequency), 100)):
        gif = select_reaction_gif(
            category,
            gif_api_key,
            recent_gif_ids=recent_gif_ids,
            curated_bias=curated_gif_bias,
        )

    return {
        "category": category,
        "kicker": TITLES.get(category, TITLES["default"]),
        "line": line,
        "sub": sub,
        "gif_query": gif.get("query", ""),
        "gif_id": gif.get("id", ""),
        "gif_url": gif.get("url", ""),
        "gif_title": gif.get("title", ""),
        "gif_selection_mode": gif.get("selection_mode", ""),
    }
