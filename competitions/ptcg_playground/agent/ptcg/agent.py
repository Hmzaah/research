"""Agent entry: deck selection, policy/search dispatch, and a legality guard that never raises."""

from __future__ import annotations

import json
import os
import random
import time
import traceback

from .policy import Policy


def load_meta_decks() -> dict[str, list[int]]:
    """Known meta decklists (ptcg/meta_decks.json) used to guess the opponent's hidden cards."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meta_decks.json")
    try:
        with open(path) as f:
            data = json.load(f)
        return {k: [int(c) for c in v] for k, v in data.items() if len(v) == 60}
    except (OSError, ValueError):
        return {}


def legalize(sel: dict, choice) -> list[int]:
    """Coerce any answer into a legal selection (distinct ints in range, min<=len<=max)."""
    n = len(sel["option"])
    lo = max(0, min(sel["minCount"], n))
    hi = max(lo, min(sel["maxCount"], n))
    out: list[int] = []
    if isinstance(choice, (list, tuple)):
        for c in choice:
            if isinstance(c, bool):
                continue
            try:
                c = int(c)
            except (TypeError, ValueError):
                continue
            if 0 <= c < n and c not in out:
                out.append(c)
    out = out[:hi]
    i = 0
    while len(out) < lo and i < n:
        if i not in out:
            out.append(i)
        i += 1
    return out


class Agent:
    def __init__(self, deck: list[int], use_search: bool = True, go_first: bool = True, seed: int | None = None,
                 search_kwargs: dict | None = None) -> None:
        self.deck = list(deck)
        self.policy = Policy(self.deck, go_first=go_first)
        self.rng = random.Random(seed)
        self.search = None
        if use_search:
            try:
                from .search import RolloutSearch

                kw = dict(search_kwargs or {})
                kw.setdefault("opponent_library", load_meta_decks())
                self.search = RolloutSearch(self.policy, self.deck, rng=self.rng, **kw)
            except Exception:  # engine missing or ABI problem: heuristic only
                traceback.print_exc()
                self.search = None
        self.errors = 0

    def __call__(self, obs: dict) -> list[int]:
        sel = obs.get("select")
        if sel is None:
            return list(self.deck)
        if not sel.get("option"):
            return []
        try:
            choice = None
            if self.search is not None:
                choice = self.search.choose(obs)
            if choice is None:
                choice = self.policy.choose(obs)
        except Exception:
            self.errors += 1
            traceback.print_exc()
            try:
                choice = self.policy.choose(obs)
            except Exception:
                choice = []
        return legalize(sel, choice)


class TimedAgent:
    """Wraps an agent with a Kaggle-style overage clock (used by the local arena)."""

    def __init__(self, agent, budget: float = 600.0) -> None:
        self.agent = agent
        self.remaining = budget
        self.max_step = 0.0

    def __call__(self, obs: dict) -> list[int]:
        obs = dict(obs)
        obs["remainingOverageTime"] = self.remaining
        t = time.perf_counter()
        out = self.agent(obs)
        dt = time.perf_counter() - t
        self.remaining -= dt
        self.max_step = max(self.max_step, dt)
        return out
