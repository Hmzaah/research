"""Generate (features, outcome) pairs from heuristic self-play for the value model.

    python tools/gen_data.py --games 20000 -j 4 --out runs/value_data.npz

Every game draws a random deck pair from decks/*.csv. Both sides follow the heuristic policy,
with epsilon-random MAIN actions for diversity. At the first decision of every turn the
features from the mover's perspective are recorded; the label is 1 if the mover wins.
"""

from __future__ import annotations

import argparse
import glob
import multiprocessing as mp
import os
import random
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))

from ptcg.engine import LocalBattle
from ptcg.features import features
from ptcg.policy import Policy


def load_decks():
    decks = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "decks", "*.csv"))):
        with open(p) as f:
            decks[os.path.basename(p)[:-4]] = [int(x) for x in f.read().split()]
    return decks


def worker(args):
    seed, n_games, eps = args
    rng = random.Random(seed)
    random.seed(seed)
    decks = load_decks()
    names = list(decks)
    pols = {}
    X, Y, G = [], [], []
    b = LocalBattle()
    for g in range(n_games):
        a, c = rng.choice(names), rng.choice(names)
        for nm in (a, c):
            if (nm, True) not in pols:
                pols[(nm, True)] = Policy(decks[nm], go_first=True)
                pols[(nm, False)] = Policy(decks[nm], go_first=False)
        players = [pols[(a, rng.random() < 0.5)], pols[(c, rng.random() < 0.5)]]
        obs = b.start(decks[a], decks[c])
        if obs is None:
            continue
        rows = []
        last_turn = -1
        steps = 0
        while obs["current"]["result"] < 0 and steps < 5000:
            cur, sel = obs["current"], obs["select"]
            who = cur["yourIndex"]
            if cur["turn"] != last_turn and sel["type"] == 0 and cur["turn"] >= 1:
                last_turn = cur["turn"]
                rows.append((features(cur, who), who))
            if sel["type"] == 0 and rng.random() < eps:
                n = len(sel["option"])
                choice = [rng.randrange(n)]
            else:
                choice = players[who].choose(obs)
            obs = b.select(choice)
            steps += 1
        res = obs["current"]["result"]
        b.finish()
        if res not in (0, 1):
            continue
        gid = seed * 1_000_000 + g
        for f, who in rows:
            X.append(f)
            Y.append(1.0 if who == res else 0.0)
            G.append(gid)
    return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32), np.array(G, dtype=np.int64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--eps", type=float, default=0.08)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(ROOT, "runs", "value_data.npz"))
    args = ap.parse_args()
    chunks = max(args.j * 4, 1)
    per = args.games // chunks
    tasks = [(args.seed * 1000 + i, per, args.eps) for i in range(chunks)]
    with mp.Pool(args.j) as pool:
        parts = pool.map(worker, tasks)
    X = np.concatenate([p[0] for p in parts])
    Y = np.concatenate([p[1] for p in parts])
    G = np.concatenate([p[2] for p in parts])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    np.savez_compressed(args.out, X=X, Y=Y, G=G)
    print(f"saved {len(X)} rows from {len(set(G.tolist()))} games -> {args.out}; mover win rate {Y.mean():.3f}")


if __name__ == "__main__":
    main()
