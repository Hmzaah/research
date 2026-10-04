"""Deck round-robin with the same agent kind on both sides: which deck does our policy pilot best?"""
import argparse
import glob
import itertools
import json
import multiprocessing as mp
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import arena


def job(args):
    a, b, kind, seed, n = args
    s = arena.run(f"{kind}:{a}", f"{kind}:{b}", n, 1, seed=seed, quiet=True)
    return a, b, s["W"], s["L"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="heur")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--decks", nargs="*")
    ap.add_argument("--out", default="runs/roundrobin.json")
    args = ap.parse_args()
    decks = args.decks or sorted(os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "decks/*.csv")))
    pairs = [(a, b, args.kind, i, args.n) for i, (a, b) in enumerate(itertools.combinations(decks, 2))]
    with mp.Pool(args.j) as pool:
        res = pool.map(job, pairs, chunksize=1)
    table = {d: {"W": 0, "L": 0} for d in decks}
    mat = {}
    for a, b, w, l in res:
        table[a]["W"] += w; table[a]["L"] += l; table[b]["W"] += l; table[b]["L"] += w
        mat[f"{a}|{b}"] = (w, l)
    rows = sorted(table.items(), key=lambda kv: -kv[1]["W"] / max(1, kv[1]["W"] + kv[1]["L"]))
    for d, r in rows:
        print(f"{os.path.basename(d):32s} {r['W']:4d}-{r['L']:4d}  {r['W']/max(1,r['W']+r['L']):.1%}")
    os.makedirs(os.path.dirname(os.path.join(ROOT, args.out)), exist_ok=True)
    with open(os.path.join(ROOT, args.out), "w") as f:
        json.dump({"table": table, "pairs": mat}, f, indent=1)

if __name__ == "__main__":
    main()
