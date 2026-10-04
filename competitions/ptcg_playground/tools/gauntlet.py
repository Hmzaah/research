"""Candidate deck(s) piloted by agent kind A vs every deck in decks/ piloted by kind B.

    python tools/gauntlet.py --kind ours@0.1 --opp heur --cands decks/wmh_froslass.csv decks/wmh_dragapult.csv -n 4
"""
import argparse
import glob
import json
import multiprocessing as mp
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import arena


def job(args):
    cand, opp, kind, okind, n, seed = args
    s = arena.run(f"{kind}:{cand}", f"{okind}:{opp}", n, 1, seed=seed, quiet=True)
    return cand, opp, s["W"], s["L"], s["game_wr"], s["n_errors"], s["a_time_max"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="ours@0.1")
    ap.add_argument("--opp", default="heur")
    ap.add_argument("--cands", nargs="+", required=True)
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--out", default="runs/gauntlet.json")
    args = ap.parse_args()
    opps = sorted(os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "decks/*.csv")))
    tasks = [(c, o, args.kind, args.opp, args.n, i) for i, (c, o) in enumerate((c, o) for c in args.cands for o in opps)]
    res = []
    with mp.Pool(args.j) as pool:
        for r in pool.imap_unordered(job, tasks, chunksize=1):
            res.append(r)
            print(f"[{len(res)}/{len(tasks)}] {os.path.basename(r[0])} vs {os.path.basename(r[1])}: {r[2]}-{r[3]}", flush=True)
    out = {}
    for cand, opp, w, l, gwr, err, tmax in res:
        r = out.setdefault(cand, {"W": 0, "L": 0, "err": 0, "tmax": 0.0, "per_opp": {}})
        r["W"] += w; r["L"] += l; r["err"] += err; r["tmax"] = max(r["tmax"], tmax)
        r["per_opp"][os.path.basename(opp)] = [w, l]
    for cand, r in sorted(out.items(), key=lambda kv: -kv[1]["W"] / max(1, kv[1]["W"] + kv[1]["L"])):
        worst = sorted(r["per_opp"].items(), key=lambda kv: kv[1][0] - kv[1][1])[:3]
        print(f"{os.path.basename(cand):28s} {r['W']:3d}-{r['L']:3d} {r['W']/max(1,r['W']+r['L']):.1%} err {r['err']} tmax {r['tmax']:.0f}s worst {worst}")
    os.makedirs(os.path.join(ROOT, "runs"), exist_ok=True)
    with open(os.path.join(ROOT, args.out), "w") as f:
        json.dump(out, f, indent=1)

if __name__ == "__main__":
    main()
