from __future__ import annotations

import random
from typing import Any


GIF_QUERIES: dict[str, list[str]] = {
    "steal": [
        "big brain meme",
        "leonardo dicaprio cheers meme",
        "chef kiss reaction meme",
        "stonks meme",
    ],
    "reach": [
        "facepalm meme",
        "confused nick young meme",
        "awkward monkey puppet meme",
        "what are you doing reaction meme",
    ],
    "splash": [
        "mind blown meme",
        "shocked pikachu meme",
        "vince mcmahon reaction meme",
        "no way reaction meme",
    ],
    "safe": [
        "approval nod meme",
        "respect reaction meme",
        "solid choice reaction meme",
    ],
    "qb_early": [
        "bold strategy cotton meme",
        "big brain meme",
        "power move reaction meme",
    ],
    "te_early": [
        "interesting choice meme",
        "spicy reaction meme",
        "hmm reaction meme",
    ],
    "rookie_hype": [
        "hype train meme",
        "lets go reaction meme",
        "crowd cheering meme",
    ],
    "chaos": [
        "michael jackson popcorn meme",
        "this is fine meme",
        "chaos reaction meme",
    ],
    "dart_throw": [
        "lottery ticket meme",
        "fingers crossed meme",
        "why not reaction meme",
    ],
    "default": [
        "funny sports reaction meme",
        "celebration reaction meme",
        "funny reaction meme",
    ],
}

LINES: dict[str, list[str]] = {
    "steal": [
        "{owner} may have just robbed the room with {player}.",
        "{owner} grabbed {player} and the rest of the league immediately got quieter.",
        "{owner} lands {player}. That one feels annoyingly sharp.",
    ],
    "reach": [
        "{owner} selected {player}. Bold. Courageous. Potentially screenshot-worthy.",
        "{owner} went with {player}. The draft chat is now entering its analysis phase.",
        "{owner} just took {player}. That's either visionary or a future group-chat meme.",
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
    "qb_early": [
        "{owner} took {player} early. Quarterback confidence levels are officially off the charts.",
        "{owner} drafted {player}. Early-QB truthers, this is your Super Bowl.",
        "{owner} grabbed {player}. The heroic music started playing immediately.",
    ],
    "te_early": [
        "{owner} went for {player}. Tight-end premium or just premium confidence?",
        "{owner} took {player}. Spicy. Slightly dangerous. Excellent television.",
        "{owner} selected {player}. The room has questions, but also curiosity.",
    ],
    "rookie_hype": [
        "{owner} hit the rookie hype button with {player}.",
        "{owner} chose {player}. Hope, upside, and highlight-reel dreams are now in play.",
        "{owner} drafted {player}. The dynasty manager inside them is showing.",
    ],
    "chaos": [
        "{owner} picked {player}. Chaos has entered the draft room and it brought snacks.",
        "{owner} just selected {player}. We are no longer pretending this draft is predictable.",
        "{owner} made the {player} pick. The popcorn meme has been activated.",
    ],
    "dart_throw": [
        "{owner} fires a late-round dart at {player}. May the waiver gods stay away.",
        "{owner} selected {player}. At this point we're buying lottery tickets with roster spots.",
        "{owner} adds {player}. Upside has entered the chat.",
    ],
    "default": [
        "{owner} selected {player}. The board moves, the tension rises.",
        "{owner} drafted {player}. The room reacts, as it should.",
        "{owner} adds {player}. Another piece has hit the board.",
    ],
}

SUBLINES: dict[str, list[str]] = {
    "steal": [
        "{position} · {team} · Round {round_no}, pick {pick_no}. This might age very well.",
        "A value-hungry room did not love seeing that one.",
    ],
    "reach": [
        "{position} · {team} · Round {round_no}, pick {pick_no}. We respect the bravery.",
        "If confidence scored fantasy points, this roster is already a contender.",
    ],
    "splash": [
        "{position} · {team} · Round {round_no}, pick {pick_no}. Cameras would have cut to gasps.",
        "The draft board is still standing, but emotionally it took damage.",
    ],
    "safe": [
        "{position} · {team} · Round {round_no}, pick {pick_no}. Quietly excellent business.",
        "No notes. Well, maybe a few notes. But not many.",
    ],
    "qb_early": [
        "{position} · {team}. Early quarterback commitment has been logged.",
        "The positional run alarm may be warming up.",
    ],
    "te_early": [
        "{position} · {team}. This pick came with seasoning.",
        "A little risk, a little swagger, a lot of entertainment.",
    ],
    "rookie_hype": [
        "{position} · {team}. Ceiling chasers nod approvingly.",
        "Nobody can accuse this pick of lacking optimism.",
    ],
    "chaos": [
        "{position} · {team}. The room is now fully seated for the drama.",
        "This draft has officially become content.",
    ],
    "dart_throw": [
        "{position} · {team}. Late-round dreams are free.",
        "Low cost. High imagination. Let's see what happens.",
    ],
    "default": [
        "{position} · {team} · Round {round_no}, pick {pick_no}.",
        "The draft board remains undefeated.",
    ],
}

OWNER_JABS = [
    "{owner}, the receipts are being saved.",
    "{owner} will be hearing about this pick at least once a week.",
    "{owner}'s confidence is currently measurable from space.",
    "Somewhere, {owner} is nodding like a mastermind.",
]

TITLES = {
    "steal": "🚨 Value Alert",
    "reach": "😂 Reach Watch",
    "splash": "🤯 Big Splash Pick",
    "safe": "👏 Respectable Business",
    "qb_early": "🧠 Early QB Energy",
    "te_early": "🌶️ Spicy Tight End Pick",
    "rookie_hype": "📈 Rookie Hype Activated",
    "chaos": "🍿 Chaos Pick",
    "dart_throw": "🎲 Late-Round Dart",
    "default": "📣 Draft Room Reaction",
}


def _pick_category(pick: dict[str, Any]) -> str:
    position = str(pick.get("position") or "").upper()
    round_no = int(pick.get("round") or 0)
    rank_delta = pick.get("rank_delta")
    adp_delta = pick.get("adp_delta")
    is_rookie = bool(pick.get("is_rookie") or pick.get("rookie"))

    deltas = []
    for value in (rank_delta, adp_delta):
        try:
            if value is not None:
                deltas.append(float(value))
        except Exception:
            pass
    if deltas:
        strongest = max(deltas)
        weakest = min(deltas)
        if strongest >= 12:
            return "steal"
        if weakest <= -12:
            return "reach"

    if position == "QB" and 1 <= round_no <= 3:
        return "qb_early"
    if position == "TE" and 1 <= round_no <= 4:
        return "te_early"
    if position in {"K", "DST", "DEF"} and 1 <= round_no <= 11:
        return "chaos"
    if is_rookie and 1 <= round_no <= 8:
        return "rookie_hype"
    if 1 <= round_no <= 2:
        return "splash"
    if 3 <= round_no <= 8:
        return "safe"
    if round_no >= 10:
        return "dart_throw"
    return "default"


def make_pick_reaction(
    pick: dict[str, Any],
    slot_to_owner: dict[int, str],
    *,
    owner_banter_enabled: bool = True,
    quality_mode: bool = True,
) -> dict[str, str]:
    slot = int(pick.get("slot") or 0)
    owner = slot_to_owner.get(slot, f"Team {slot}")
    player = str(pick.get("player") or "this player")
    position = str(pick.get("position") or "")
    team = str(pick.get("nfl_team") or "")
    pick_no = int(pick.get("pick") or 0)
    round_no = int(pick.get("round") or 0)

    category = _pick_category(pick) if quality_mode else "default"
    template_values = {
        "owner": owner,
        "player": player,
        "position": position,
        "team": team,
        "pick_no": pick_no,
        "round_no": round_no,
    }
    line = random.choice(LINES.get(category) or LINES["default"]).format(**template_values)
    sub = random.choice(SUBLINES.get(category) or SUBLINES["default"]).format(**template_values)
    if owner_banter_enabled and random.random() < 0.75:
        sub = f"{sub} {random.choice(OWNER_JABS).format(owner=owner)}".strip()

    return {
        "category": category,
        "kicker": TITLES.get(category, TITLES["default"]),
        "line": line,
        "sub": sub,
        "gif_query": random.choice(GIF_QUERIES.get(category) or GIF_QUERIES["default"]),
    }
