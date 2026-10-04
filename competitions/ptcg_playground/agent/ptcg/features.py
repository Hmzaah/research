"""State features for the learned value function (perspective of player `me`).

Shared by data generation (tools/gen_data.py), training (tools/train_value.py) and
inference inside the search, so it must stay deterministic and cheap.
"""

from __future__ import annotations

from . import cards as C


def _side(p: dict, opp_active: dict | None) -> list[float]:
    mons = [x for x in p["active"] + p["bench"] if x]
    act = p["active"][0] if p["active"] and p["active"][0] else None
    n = len(mons)
    hp = sum(x["hp"] for x in mons)
    energy = sum(len(x["energies"]) for x in mons)
    ex_n = sum(1 for x in mons if C.prize_value(x["id"]) >= 2)
    liability = sum(C.prize_value(x["id"]) for x in mons)
    s1 = sum(1 for x in mons if C.stage(x["id"]) == 1)
    s2 = sum(1 for x in mons if C.stage(x["id"]) == 2)
    ready = 0
    ready_dmg = 0
    for x in mons:
        d = _ready(x)
        if d > 0:
            ready += 1
            ready_dmg = max(ready_dmg, d)
    tools = sum(len(x["tools"]) for x in mons)
    if act is not None:
        a_hp = act["hp"]
        a_frac = act["hp"] / max(1, act["maxHp"])
        a_dmg = _ready(act)
        a_e = len(act["energies"])
        a_pv = C.prize_value(act["id"])
        a_retreat = C.card(act["id"])["retreatCost"]
        ko = 0.0
        if opp_active is not None and a_dmg > 0:
            ko = 1.0 if _wr(a_dmg, act["id"], opp_active["id"]) >= opp_active["hp"] else 0.0
        # how many more energies the active needs for its strongest attack
        miss = min((C.missing_energy(act["energies"], C.attack_cost(a)) for a in C.card(act["id"])["attacks"]), default=3)
    else:
        a_hp = a_frac = a_dmg = a_e = a_pv = a_retreat = ko = 0.0
        miss = 3
    cond = sum(1 for k in ("poisoned", "burned", "asleep", "paralyzed", "confused") if p.get(k))
    return [
        len(p["prize"]) / 6, p["deckCount"] / 60, min(p["handCount"], 15) / 15, len(p["discard"]) / 60,
        n / 6, hp / 1000, energy / 15, ex_n / 4, liability / 10, s1 / 4, s2 / 3, ready / 4, ready_dmg / 300,
        tools / 4, a_hp / 350, a_frac, a_dmg / 300, a_e / 5, a_pv / 3, a_retreat / 4, ko, min(miss, 4) / 4,
        cond / 2, 1.0 if p["deckCount"] <= 5 else 0.0, 1.0 if n <= 1 else 0.0,
    ]


def _ready(pk: dict) -> int:
    best = 0
    for a in C.card(pk["id"])["attacks"]:
        if C.missing_energy(pk["energies"], C.attack_cost(a)) == 0:
            best = max(best, C.est_damage(a))
    return best


def _wr(dmg: int, a: int, d: int) -> int:
    at = C.card(a)["energyType"]
    dc = C.card(d)
    if dc["weakness"] is not None and dc["weakness"] == at:
        dmg *= 2
    if dc["resistance"] is not None and dc["resistance"] == at:
        dmg -= 30
    return dmg


N_SIDE = 25


def features(cur: dict, me: int) -> list[float]:
    mine, theirs = cur["players"][me], cur["players"][1 - me]
    ma = mine["active"][0] if mine["active"] and mine["active"][0] else None
    oa = theirs["active"][0] if theirs["active"] and theirs["active"][0] else None
    a = _side(mine, oa)
    b = _side(theirs, ma)
    diff = [x - y for x, y in zip(a, b)]
    glob = [
        min(cur["turn"], 60) / 60,
        1.0 if cur["yourIndex"] == me else 0.0,
        1.0 if cur.get("firstPlayer") == me else 0.0,
    ]
    return a + b + diff + glob


N_FEATURES = 3 * N_SIDE + 3
