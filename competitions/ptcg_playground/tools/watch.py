"""Print one game's decisions in readable form (debugging the heuristic).

    python tools/watch.py decks/wmh_dragapult.csv decks/wmh_alakazam.csv --seed 3 --who 0
"""

from __future__ import annotations

import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))

from ptcg import cards as C
from ptcg.agent import Agent
from ptcg.engine import LocalBattle

CTX = {i: n for i, n in enumerate(["MAIN", "SETUP_ACTIVE", "SETUP_BENCH", "SWITCH", "TO_ACTIVE", "TO_BENCH", "TO_FIELD", "TO_HAND", "DISCARD", "TO_DECK", "TO_DECK_BOTTOM", "TO_PRIZE", "NOT_MOVE", "DAMAGE_COUNTER", "DAMAGE_COUNTER_ANY", "DAMAGE", "REMOVE_DAMAGE_COUNTER", "HEAL", "EVOLVES_FROM", "EVOLVES_TO", "DEVOLVE", "ATTACH_FROM", "ATTACH_TO", "DETACH_FROM", "LOOK", "EFFECT_TARGET", "DISCARD_ENERGY_CARD", "DISCARD_TOOL_CARD", "SWITCH_ENERGY_CARD", "DISCARD_CARD_OR_ATTACHED", "DISCARD_ENERGY", "TO_HAND_ENERGY", "TO_DECK_ENERGY", "SWITCH_ENERGY", "SKILL_ORDER", "ATTACK", "DISABLE_ATTACK", "EVOLVE", "DRAW_COUNT", "DAMAGE_COUNTER_COUNT", "REMOVE_DAMAGE_COUNTER_COUNT", "IS_FIRST", "MULLIGAN", "ACTIVATE", "FIRST_EFFECT", "MORE_DEVOLVE", "COIN_HEAD", "AFFECT_SPECIAL_CONDITION", "RECOVER_SPECIAL_CONDITION"])}
OPT = ["NUMBER", "YES", "NO", "CARD", "TOOL_CARD", "ENERGY_CARD", "ENERGY", "PLAY", "ATTACH", "EVOLVE", "ABILITY", "DISCARD", "RETREAT", "ATTACK", "END", "SKILL", "COND"]


def arena_load(path):
    with open(path) as f:
        return [int(x) for x in f.read().split()]


def name(cid):
    return C.card(cid)["name"] if cid is not None else "?"


def pk_str(p):
    if not p:
        return "-"
    return f"{name(p['id'])}({p['hp']}/{p['maxHp']} e{len(p['energies'])})"


def describe_option(cur, sel, o):
    me = cur["yourIndex"]
    t = o["type"]
    s = OPT[t]
    P = cur["players"]
    if t == 7:
        h = P[me]["hand"]
        s += " " + name(h[o["index"]]["id"]) if o.get("index", 99) < len(h) else ""
    elif t in (8, 9):
        h = P[me]["hand"]
        src = name(h[o["index"]]["id"]) if o.get("index", 99) < len(h) else "?"
        lst = P[me]["active"] if o.get("inPlayArea") == 4 else P[me]["bench"]
        tgt = pk_str(lst[o["inPlayIndex"]]) if o.get("inPlayIndex", 99) < len(lst) else "?"
        s += f" {src} -> {tgt}"
    elif t == 13:
        s += f" {C.ATTACKS.get(o.get('attackId'), {}).get('name')} ({C.est_damage(o.get('attackId', 0))})"
    elif t == 10:
        s += f" area{o.get('area')} idx{o.get('index')}"
    elif t in (3, 4, 5, 6):
        owner = o.get("playerIndex", me)
        who = "my" if owner == me else "opp"
        area = o.get("area")
        if area in (4, 5):
            lst = P[owner]["active"] if area == 4 else P[owner]["bench"]
            s += f" {who} {pk_str(lst[o['index']]) if o['index'] < len(lst) else '?'}"
        else:
            lst = {1: sel.get("deck"), 2: P[owner].get("hand"), 3: P[owner].get("discard"), 6: P[owner].get("prize"),
                   12: cur.get("looking"), 7: cur.get("stadium")}.get(area) or []
            cid = lst[o["index"]]["id"] if o.get("index", 99) < len(lst) and lst[o["index"]] else None
            s += f" {who} area{area} {name(cid)}"
    elif t == 0:
        s += f" {o.get('number')}"
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck0")
    ap.add_argument("deck1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--who", type=int, default=0)
    ap.add_argument("--search", action="store_true")
    args = ap.parse_args()
    random.seed(args.seed)
    d0, d1 = (arena_load(os.path.join(ROOT, p)) for p in (args.deck0, args.deck1))
    agents = [Agent(d0, use_search=args.search, seed=args.seed), Agent(d1, use_search=False, seed=args.seed + 1)]
    b = LocalBattle()
    obs = b.start(d0, d1)
    while obs["current"]["result"] < 0:
        cur, sel = obs["current"], obs["select"]
        who = cur["yourIndex"]
        choice = agents[who](obs)
        if who == args.who:
            P = cur["players"]
            me, op = P[who], P[1 - who]
            if sel["type"] == 0:
                print(f"\n== T{cur['turn']} p{who} prizes {len(me['prize'])}-{len(op['prize'])} hand {me['handCount']} deck {me['deckCount']} | "
                      f"me: {pk_str(me['active'][0] if me['active'] else None)} bench [{', '.join(pk_str(p) for p in me['bench'])}] | "
                      f"opp: {pk_str(op['active'][0] if op['active'] else None)} bench [{', '.join(pk_str(p) for p in op['bench'])}]")
                print("   hand:", ", ".join(name(h["id"]) for h in me["hand"]))
            sc = agents[who].policy.scores(obs)
            print(f"  [{CTX.get(sel['context'])}] min{sel['minCount']} max{sel['maxCount']} -> {choice}")
            for i, o in enumerate(sel["option"]):
                mark = "*" if i in choice else " "
                print(f"   {mark} {sc[i]:6.1f} {describe_option(cur, sel, o)}")
        obs = b.select(choice)
    print("RESULT winner", obs["current"]["result"], "turn", obs["current"]["turn"])


if __name__ == "__main__":
    main()
