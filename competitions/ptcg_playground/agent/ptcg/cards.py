"""Static card knowledge derived from the engine's card database (no hand-written card lists)."""

from __future__ import annotations

import re
from functools import cache, lru_cache

from .engine import ATTACKS, CARDS

# CardType
POKEMON, ITEM, TOOL, SUPPORTER, STADIUM, BASIC_ENERGY, SPECIAL_ENERGY = range(7)
# EnergyType
COLORLESS, RAINBOW, TEAM_ROCKET = 0, 10, 11
PSYCHIC, DARKNESS = 5, 7

_SCALING = re.compile(r"(\d+) (?:more )?damage for each")
_DRAW = re.compile(r"[Dd]raw (\d+|a) cards?")


def card(card_id: int) -> dict:
    return CARDS.get(card_id) or {
        "cardId": card_id,
        "name": "?",
        "cardType": ITEM,
        "retreatCost": 0,
        "hp": 0,
        "weakness": None,
        "resistance": None,
        "energyType": 0,
        "basic": False,
        "stage1": False,
        "stage2": False,
        "ex": False,
        "megaEx": False,
        "tera": False,
        "aceSpec": False,
        "evolvesFrom": None,
        "skills": [],
        "attacks": [],
    }


def is_pokemon(card_id: int) -> bool:
    return card(card_id)["cardType"] == POKEMON


def is_energy(card_id: int) -> bool:
    return card(card_id)["cardType"] in (BASIC_ENERGY, SPECIAL_ENERGY)


def prize_value(card_id: int) -> int:
    c = card(card_id)
    if c["megaEx"]:
        return 3
    if c["ex"]:
        return 2
    return 1


def stage(card_id: int) -> int:
    c = card(card_id)
    return 2 if c["stage2"] else 1 if c["stage1"] else 0


@cache
def est_damage(attack_id: int) -> int:
    """Printed damage, with a rough estimate for "N damage for each ..." attacks."""
    a = ATTACKS.get(attack_id)
    if a is None:
        return 0
    dmg = a["damage"]
    m = _SCALING.search(a["text"])
    if m:
        per = int(m.group(1))
        if "heads" in a["text"]:
            # flip-until-tails or N coins: about one head on average
            dmg += per
        else:
            dmg += 2 * per
    return dmg


@cache
def attack_cost(attack_id: int) -> tuple[int, ...]:
    a = ATTACKS.get(attack_id)
    return tuple(a["energies"]) if a else ()


def missing_energy(provided: list[int], cost: tuple[int, ...]) -> int:
    """How many more energies are needed to pay `cost` with `provided` (greedy, exact for basics)."""
    return _missing(tuple(provided), cost)


@lru_cache(maxsize=65536)
def _missing(provided: tuple[int, ...], cost: tuple[int, ...]) -> int:
    pool = list(provided)
    missing = 0
    specific = [t for t in cost if t != COLORLESS]
    colorless = len(cost) - len(specific)
    wild: list[int] = []
    for t in specific:
        if t in pool:
            pool.remove(t)
        else:
            wild.append(t)
    for t in wild:
        if RAINBOW in pool:
            pool.remove(RAINBOW)
        elif TEAM_ROCKET in pool and t in (PSYCHIC, DARKNESS):
            pool.remove(TEAM_ROCKET)
        else:
            missing += 1
    return missing + max(0, colorless - len(pool))


def needs_type(provided: list[int], cost: tuple[int, ...], etype: int) -> bool:
    """Would attaching one energy of `etype` reduce the missing count for `cost`?"""
    return missing_energy(provided + [etype], cost) < missing_energy(provided, cost)


@cache
def draw_amount(card_id: int) -> int:
    c = card(card_id)
    texts = [s["text"] for s in c["skills"]]
    best = 0
    for t in texts:
        for m in _DRAW.finditer(t):
            n = 1 if m.group(1) == "a" else int(m.group(1))
            best = max(best, n)
    return best


@cache
def card_text(card_id: int) -> str:
    c = card(card_id)
    return " ".join(s["text"] for s in c["skills"])


@cache
def best_attack_damage(card_id: int) -> int:
    return max((est_damage(a) for a in card(card_id)["attacks"]), default=0)


def evolves_from(card_id: int) -> str | None:
    return card(card_id)["evolvesFrom"]
