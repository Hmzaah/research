"""Local BO3 arena that mirrors kaggle_environments/envs/cabt/cabt.py.

Each match: game 1 normal start, later games ``BattleStartReverse`` when the number of
finished games is odd (exactly as the Kaggle interpreter does). Both seats are played by
swapping who is player 0 across matches. Agents get a 600 s overage clock per match;
an exception, illegal answer or clock overrun loses the match.

Usage:
    python tools/arena.py --a ours:decks/wmh_dragapult.csv --b heur:decks/wmh_alakazam.csv -n 40 -j 4
Agent specs:  ours (policy+search), heur (policy only), random, first
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))

from ptcg.agent import Agent, TimedAgent, legalize
from ptcg.engine import LocalBattle

MAX_STEPS_PER_GAME = 6000


def load_deck(path: str) -> list[int]:
    with open(path) as f:
        return [int(x) for x in f.read().split()]


class RandomAgent:
    def __init__(self, deck, seed=None):
        self.deck = deck
        self.rng = random.Random(seed)

    def __call__(self, obs):
        sel = obs["select"]
        if sel is None:
            return self.deck
        n = len(sel["option"])
        return self.rng.sample(range(n), min(sel["maxCount"], n))


class FirstAgent:
    def __init__(self, deck):
        self.deck = deck

    def __call__(self, obs):
        sel = obs["select"]
        if sel is None:
            return self.deck
        return list(range(min(sel["maxCount"], len(sel["option"]))))


def make_agent(spec: str, seed: int, search_kwargs: dict | None = None):
    kind, deck_path = spec.split(":", 1)
    deck = load_deck(os.path.join(ROOT, deck_path) if not os.path.isabs(deck_path) else deck_path)
    if kind.startswith("ours"):
        # "ours", "ours@0.8" (per-decision cap seconds), "ours2@0.8" (go second)
        kw = dict(search_kwargs or {})
        if "@" in kind:
            kw["max_decision_time"] = float(kind.split("@", 1)[1])
        if kind.startswith("oursv"):  # learned value model instead of the hand-written evaluator
            kw["use_value"] = True
        return Agent(deck, use_search=True, seed=seed, search_kwargs=kw, go_first=not kind.startswith("ours2"))
    if kind == "heur":
        return Agent(deck, use_search=False, seed=seed)
    if kind == "heur2":  # heuristic that chooses to go second
        return Agent(deck, use_search=False, seed=seed, go_first=False)
    if kind == "random":
        return RandomAgent(deck, seed)
    if kind == "first":
        return FirstAgent(deck)
    raise ValueError(spec)


def play_match(agents, bo: int = 3) -> dict:
    """agents: [p0, p1] TimedAgents. Returns {'winner': 0/1/-1, 'games': [...], 'reason': str}."""
    battle = LocalBattle()
    decks = [a.agent.deck for a in agents]
    wins = [0, 0, 0]
    games = []
    for g in range(bo):
        count = sum(wins)
        obs = battle.start(decks[0], decks[1], reverse=count % 2 != 0)
        if obs is None:
            return {"winner": -1, "games": games, "reason": "deck error"}
        steps = 0
        while obs["current"]["result"] < 0:
            who = obs["current"]["yourIndex"]
            ag = agents[who]
            try:
                choice = ag(obs)
            except Exception as e:  # noqa: BLE001
                battle.finish()
                return {"winner": 1 - who, "games": games, "reason": f"exception p{who}: {e!r}"}
            if ag.remaining < 0:
                battle.finish()
                return {"winner": 1 - who, "games": games, "reason": f"timeout p{who}"}
            if legalize(obs["select"], choice) != list(choice):
                battle.finish()
                return {"winner": 1 - who, "games": games, "reason": f"illegal p{who}: {choice}"}
            try:
                obs = battle.select(list(choice))
            except Exception as e:  # noqa: BLE001
                battle.finish()
                return {"winner": 1 - who, "games": games, "reason": f"engine rejected p{who}: {e!r}"}
            steps += 1
            if steps > MAX_STEPS_PER_GAME:
                break
        res = obs["current"]["result"]
        first = obs["current"]["firstPlayer"]
        battle.finish()
        if res in (0, 1):
            wins[res] += 1
        else:
            wins[2] += 1
        games.append({"result": res, "turns": obs["current"]["turn"], "first": first})
        remain = bo - sum(wins)
        if wins[0] > wins[1] + remain:
            return {"winner": 0, "games": games, "reason": "ok"}
        if wins[1] > wins[0] + remain:
            return {"winner": 1, "games": games, "reason": "ok"}
        if remain <= 0:
            return {"winner": -1, "games": games, "reason": "draw"}
    return {"winner": -1, "games": games, "reason": "draw"}


def _job(args):
    spec_a, spec_b, seed, swap, bo, skw = args
    random.seed(seed)
    a = TimedAgent(make_agent(spec_a, seed, skw))
    b = TimedAgent(make_agent(spec_b, seed + 7919, skw if spec_b.startswith("ours") else None))
    order = [b, a] if swap else [a, b]
    t = time.time()
    r = play_match(order, bo)
    w = r["winner"]
    a_idx = 1 if swap else 0
    a_won = None if w < 0 else (w == a_idx)
    # game-level stats from A's perspective
    gw = sum(1 for g in r["games"] if g["result"] == a_idx)
    gl = sum(1 for g in r["games"] if g["result"] == 1 - a_idx)
    a_first = sum(1 for g in r["games"] if g["first"] == a_idx and g["result"] == a_idx)
    return {
        "a_won": a_won, "reason": r["reason"], "gw": gw, "gl": gl, "secs": time.time() - t,
        "a_time": 600 - a.remaining, "a_max": a.max_step, "b_time": 600 - b.remaining, "a_first_wins": a_first,
        "games": r["games"], "a_idx": a_idx,
    }


def run(spec_a: str, spec_b: str, n: int, jobs: int, bo: int = 3, seed: int = 0, search_kwargs=None, quiet=False):
    tasks = [(spec_a, spec_b, seed * 100003 + i, i % 2 == 1, bo, search_kwargs) for i in range(n)]
    if jobs > 1:
        with mp.Pool(jobs) as pool:
            results = pool.map(_job, tasks, chunksize=1)
    else:
        results = [_job(t) for t in tasks]
    w = sum(1 for r in results if r["a_won"] is True)
    l = sum(1 for r in results if r["a_won"] is False)
    d = n - w - l
    gw = sum(r["gw"] for r in results)
    gl = sum(r["gl"] for r in results)
    bad = [r["reason"] for r in results if r["reason"] not in ("ok", "draw")]
    # first-player game stats
    first_games = [(g["first"] == r["a_idx"], g["result"] == r["a_idx"]) for r in results for g in r["games"]]
    fw = sum(1 for f, won in first_games if f and won)
    fn = sum(1 for f, _ in first_games if f)
    sw = sum(1 for f, won in first_games if not f and won)
    sn = sum(1 for f, _ in first_games if not f)
    summary = {
        "a": spec_a, "b": spec_b, "matches": n, "W": w, "L": l, "D": d,
        "match_wr": w / max(1, w + l), "game_wr": gw / max(1, gw + gl),
        "a_first_wr": fw / max(1, fn), "a_second_wr": sw / max(1, sn),
        "a_time_max": max(r["a_time"] for r in results), "a_step_max": max(r["a_max"] for r in results),
        "errors": bad[:5], "n_errors": len(bad),
    }
    if not quiet:
        print(
            f"{spec_a} vs {spec_b}: match {w}-{l}-{d} ({summary['match_wr']:.1%}), games {gw}-{gl} "
            f"({summary['game_wr']:.1%}), A first {summary['a_first_wr']:.0%}/second {summary['a_second_wr']:.0%}, "
            f"A time max {summary['a_time_max']:.1f}s step max {summary['a_step_max']:.2f}s, errors {len(bad)} {bad[:3]}"
        )
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("-j", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--bo", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--budget", type=float, default=None, help="search seconds per decision cap")
    args = ap.parse_args()
    skw = {"max_decision_time": args.budget} if args.budget else None
    run(args.a, args.b, args.n, args.j, args.bo, args.seed, skw)


if __name__ == "__main__":
    main()
