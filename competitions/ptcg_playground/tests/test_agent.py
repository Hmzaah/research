"""Robustness tests: the agent must never crash or answer illegally.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import glob
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))

from ptcg.agent import Agent, legalize
from ptcg.engine import CARDS, LocalBattle


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


DECKS = {
    os.path.basename(p)[:-4]: [int(x) for x in _read(p).split()]
    for p in sorted(glob.glob(os.path.join(ROOT, "decks", "*.csv")))
}


def _sel(n, lo, hi):
    return {"option": [{"type": 3}] * n, "minCount": lo, "maxCount": hi}


class LegalizeTest(unittest.TestCase):
    def test_trims_dedupes_and_fills(self):
        self.assertEqual(legalize(_sel(3, 1, 1), [2, 2, 1]), [2])
        self.assertEqual(legalize(_sel(3, 2, 2), [5, -1]), [0, 1])
        self.assertEqual(legalize(_sel(3, 0, 2), []), [])
        self.assertEqual(legalize(_sel(3, 1, 3), "garbage"), [0])
        self.assertEqual(legalize(_sel(4, 2, 4), [3, True, 3.0, "1"]), [3, 1])
        self.assertEqual(legalize(_sel(0, 0, 0), [0]), [])


class DeckTest(unittest.TestCase):
    def test_all_pool_decks_are_legal(self):
        b = LocalBattle()
        for name, deck in DECKS.items():
            self.assertEqual(len(deck), 60, name)
            self.assertTrue(all(c in CARDS for c in deck), name)
            self.assertIsNotNone(b.start(deck, deck), name)
            b.finish()

    def test_submission_deck_is_legal(self):
        path = os.path.join(ROOT, "agent", "deck.csv")
        deck = [int(x) for x in _read(path).split()]
        self.assertEqual(len(deck), 60)
        b = LocalBattle()
        self.assertIsNotNone(b.start(deck, deck))
        b.finish()


def _play(agents, decks, max_steps=6000):
    b = LocalBattle()
    obs = b.start(decks[0], decks[1])
    steps = 0
    while obs["current"]["result"] < 0 and steps < max_steps:
        sel = obs["select"]
        who = obs["current"]["yourIndex"]
        choice = agents[who](obs)
        assert choice == legalize(sel, choice), (choice, sel)
        obs = b.select(choice)  # raises if the engine rejects it
        steps += 1
    b.finish()
    return obs["current"]["result"], steps


class GameplayTest(unittest.TestCase):
    def test_heuristic_every_deck_pair_sample(self):
        rng = random.Random(0)
        names = list(DECKS)
        for i in range(60):
            a, c = rng.choice(names), rng.choice(names)
            agents = [Agent(DECKS[a], use_search=False), Agent(DECKS[c], use_search=False)]
            res, steps = _play(agents, [DECKS[a], DECKS[c]])
            self.assertIn(res, (0, 1, 2), f"{a} vs {c} did not finish in {steps} steps")
            self.assertEqual(agents[0].errors + agents[1].errors, 0)

    def test_search_agent_games(self):
        rng = random.Random(1)
        names = list(DECKS)
        for i in range(3):
            a, c = rng.choice(names), rng.choice(names)
            agents = [
                Agent(DECKS[a], use_search=True, search_kwargs={"max_decision_time": 0.03}),
                Agent(DECKS[c], use_search=True, search_kwargs={"max_decision_time": 0.03}),
            ]
            res, _ = _play(agents, [DECKS[a], DECKS[c]])
            self.assertIn(res, (0, 1, 2))
            self.assertEqual(agents[0].errors + agents[1].errors, 0)
            self.assertGreater(agents[0].search.stats["searches"], 0)


class KaggleLoadingTest(unittest.TestCase):
    """main.py is exec()'d by kaggle_environments; the last callable must be the agent."""

    def test_last_callable_and_deck(self):
        path = os.path.join(ROOT, "agent", "main.py")
        src = _read(path)
        env: dict = {}
        sys.path.append(os.path.dirname(path))
        try:
            exec(compile(src, path, "exec"), env)
        finally:
            sys.path.pop()
        fn = [v for v in env.values() if callable(v)][-1]
        self.assertEqual(fn.__name__, "agent")
        deck = fn({"select": None, "logs": [], "current": None, "search_begin_input": None, "remainingOverageTime": 600}, {})
        self.assertEqual(len(deck), 60)
        b = LocalBattle()
        obs = b.start(deck, deck)
        obs["remainingOverageTime"] = 600.0
        choice = fn(obs, {})
        self.assertEqual(choice, legalize(obs["select"], choice))
        b.finish()


class KaggleSubprocessLoadingTest(unittest.TestCase):
    """Fresh interpreter, foreign cwd, sys.path entry popped after exec (kaggle_environments behaviour)."""

    def test_package_imports_after_sys_path_pop(self):
        import subprocess
        import tempfile

        script = r"""
import os, sys, json
path = sys.argv[1]
src = open(path).read()
env = {}
sys.path.append(os.path.dirname(path))
exec(compile(src, path, "exec"), env)
sys.path.pop()
fn = [v for v in env.values() if callable(v)][-1]
deck = fn({"select": None}, {})
sys.path.insert(0, os.path.join(os.path.dirname(path)))
from ptcg.engine import LocalBattle
b = LocalBattle()
obs = b.start(deck, deck)
obs["remainingOverageTime"] = 600.0
fn(obs, {})
st = env["_STATE"]["agent"]
print(json.dumps({"fn": fn.__name__, "agent": type(st).__name__, "search": st.search is not None}))
"""
        with tempfile.TemporaryDirectory() as cwd:
            out = subprocess.run(
                [sys.executable, "-c", script, os.path.join(ROOT, "agent", "main.py")],
                cwd=cwd, capture_output=True, text=True, timeout=120, check=False,
            )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("Traceback", out.stderr, out.stderr)
        self.assertIn('"agent": "Agent"', out.stdout)
        self.assertIn('"search": true', out.stdout)
        self.assertIn('"fn": "agent"', out.stdout)


if __name__ == "__main__":
    unittest.main()
