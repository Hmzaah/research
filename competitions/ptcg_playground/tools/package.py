"""Build the Kaggle submission archive.

    python tools/package.py --deck decks/wmh_dragapult.csv --out build/submission.tar.gz

Layout at the archive root (Kaggle runs it from /kaggle_simulations/agent/):
    main.py  deck.csv  ptcg/*.py  cg/ (engine: libcg.so etc., from vendor/cg)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_BYTES = int(197.7 * 1024 * 1024)


def validate_deck(path: str) -> list[int]:
    sys.path.insert(0, os.path.join(ROOT, "agent"))
    from ptcg.engine import CARDS, LocalBattle

    with open(path) as f:
        deck = [int(x) for x in f.read().split() if x.strip()]
    if len(deck) != 60:
        raise SystemExit(f"deck has {len(deck)} cards, expected 60")
    unknown = [c for c in deck if c not in CARDS]
    if unknown:
        raise SystemExit(f"unknown card ids: {unknown}")
    b = LocalBattle()
    if b.start(deck, deck) is None:
        raise SystemExit("engine rejected the deck (BattleStart errorPlayer >= 0)")
    b.finish()
    return deck


def build(deck_path: str, out: str) -> str:
    deck = validate_deck(deck_path)
    stage = os.path.join(ROOT, "build", "submission")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(os.path.join(stage, "ptcg"))
    shutil.copy(os.path.join(ROOT, "agent", "main.py"), stage)
    for f in sorted(os.listdir(os.path.join(ROOT, "agent", "ptcg"))):
        if f.endswith((".py", ".json")):
            shutil.copy(os.path.join(ROOT, "agent", "ptcg", f), os.path.join(stage, "ptcg", f))
    with open(os.path.join(stage, "deck.csv"), "w") as f:
        f.write("\n".join(str(c) for c in deck) + "\n")
    cg_src = os.path.join(ROOT, "vendor", "cg")
    if not os.path.isdir(cg_src):
        raise SystemExit("vendor/cg missing: run tools/fetch_engine.sh")
    shutil.copytree(cg_src, os.path.join(stage, "cg"))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        for name in sorted(os.listdir(stage)):
            tar.add(os.path.join(stage, name), arcname=name)
    size = os.path.getsize(out)
    if size > MAX_BYTES:
        raise SystemExit(f"archive {size} bytes exceeds the 197.7 MiB limit")
    print(f"wrote {out} ({size / 1024 / 1024:.2f} MiB)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "submission.tar.gz"))
    args = ap.parse_args()
    build(os.path.join(ROOT, args.deck) if not os.path.isabs(args.deck) else args.deck, args.out)


if __name__ == "__main__":
    main()
