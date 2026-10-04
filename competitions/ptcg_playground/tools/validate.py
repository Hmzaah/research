"""Reproduce Kaggle's validation episode: the packaged agent plays itself in kaggle_environments.

Run with a Python that has kaggle-environments installed (e.g. a venv):
    python tools/validate.py build/submission.tar.gz [--opponent random]

The archive is extracted to a temp dir and main.py is loaded exactly the way Kaggle does
(exec of the file, last callable), then a full BO3 episode is played with the real
interpreter, overage clock included. Exits non-zero on any agent error/invalid status.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
import time


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--opponent", default=None, help="'random' or 'first' builtin; default: self-play")
    ap.add_argument("--episodes", type=int, default=1)
    args = ap.parse_args()

    from kaggle_environments import make

    tmp = tempfile.mkdtemp(prefix="ptcg_validate_")
    with tarfile.open(args.archive) as tar:
        tar.extractall(tmp)
    main_py = os.path.join(tmp, "main.py")
    assert os.path.isfile(main_py) and os.path.isfile(os.path.join(tmp, "deck.csv")), "main.py/deck.csv not at archive root"
    os.chdir(tmp)
    ok = True
    for ep in range(args.episodes):
        env = make("cabt", debug=False)
        opp = args.opponent or main_py
        t = time.time()
        steps = env.run([main_py, opp])
        last = steps[-1]
        statuses = [s["status"] for s in last]
        rewards = [s["reward"] for s in last]
        remaining = [s["observation"].get("remainingOverageTime") for s in last]
        err = env.steps[0][0].get("error") if env.steps and env.steps[0] else None
        durations = [0.0, 0.0]
        stderr = set()
        for st in env.logs:
            for i, log in enumerate(st or []):
                if log:
                    durations[i] += log.get("duration", 0.0)
                    if log.get("stderr"):
                        stderr.add(log["stderr"][:800])
        for e in sorted(stderr)[:5]:
            print("AGENT STDERR:", e)
        print(json.dumps({"episode": ep, "statuses": statuses, "rewards": rewards, "result": getattr(env, "result", None),
                          "remainingOverageTime": remaining, "steps": len(steps), "seconds": round(time.time() - t, 1),
                          "agent_seconds": [round(d, 1) for d in durations],
                          "error": err}))
        if any(s not in ("DONE",) for s in statuses) or stderr:
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
