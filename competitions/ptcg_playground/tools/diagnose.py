"""Play single games heur vs X and summarize how our losses happen."""
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent")); sys.path.insert(0, os.path.join(ROOT, "tools"))
from arena import make_agent
from ptcg.engine import LocalBattle


def main(spec_a, spec_b, n):
    b = LocalBattle(); reasons = collections.Counter(); results = collections.Counter()
    for g in range(n):
        A = make_agent(spec_a, g); B = make_agent(spec_b, g + 99)
        ag = [A, B] if g % 2 == 0 else [B, A]
        me = 0 if g % 2 == 0 else 1
        obs = b.start(ag[0].deck, ag[1].deck)
        while obs["current"]["result"] < 0:
            obs = b.select(ag[obs["current"]["yourIndex"]](obs))
        c = obs["current"]; P = c["players"]
        won = c["result"] == me
        results[won] += 1
        if not won:
            mine, th = P[me], P[1 - me]
            if len(th["prize"]) == 0: r = "opp took all prizes"
            elif not mine["active"] and not mine["bench"]: r = "we had no Pokemon"
            elif mine["deckCount"] == 0: r = "we decked out"
            else: r = "other"
            reasons[r] += 1
            print(f"loss g{g} turn {c['turn']} first={c['firstPlayer']==me} prizes me {len(mine['prize'])} opp {len(th['prize'])} deck {mine['deckCount']} reason {r}")
        b.finish()
    print(results, reasons)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
