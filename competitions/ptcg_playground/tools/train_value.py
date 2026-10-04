"""Train the value model (win probability of the player to move) with numpy.

    python tools/train_value.py runs/value_v1.npz --out agent/ptcg/value_weights.json

MLP: N_FEATURES -> H1 -> H2 -> 1 (tanh hidden, sigmoid out), Adam, game-level split.
Prints validation log-loss / accuracy next to a logistic-regression and prize-diff baseline.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def init(rng, sizes):
    params = []
    for a, b in itertools.pairwise(sizes):
        params.append([rng.normal(0, np.sqrt(1 / a), (a, b)).astype(np.float32), np.zeros(b, np.float32)])
    return params


def forward(params, X):
    acts = [X]
    h = X
    for i, (W, b) in enumerate(params):
        z = h @ W + b
        h = np.tanh(z) if i < len(params) - 1 else sigmoid(z)
        acts.append(h)
    return acts


def train(X, Y, Xv, Yv, sizes, epochs=12, lr=2e-3, batch=2048, l2=1e-5, seed=0):
    rng = np.random.default_rng(seed)
    params = init(rng, sizes)
    m = [[np.zeros_like(W), np.zeros_like(b)] for W, b in params]
    v = [[np.zeros_like(W), np.zeros_like(b)] for W, b in params]
    t = 0
    b1, b2, eps = 0.9, 0.999, 1e-8
    best = (9.9, None)
    for ep in range(epochs):
        idx = rng.permutation(len(X))
        for s in range(0, len(X), batch):
            bi = idx[s:s + batch]
            acts = forward(params, X[bi])
            y = Y[bi][:, None]
            delta = (acts[-1] - y) / len(bi)
            grads = []
            for i in range(len(params) - 1, -1, -1):
                W, _ = params[i]
                gW = acts[i].T @ delta + l2 * W
                gb = delta.sum(0)
                grads.append((gW, gb))
                if i > 0:
                    delta = (delta @ W.T) * (1 - acts[i] ** 2)
            grads.reverse()
            t += 1
            for i, (gW, gb) in enumerate(grads):
                for j, g in enumerate((gW, gb)):
                    m[i][j] = b1 * m[i][j] + (1 - b1) * g
                    v[i][j] = b2 * v[i][j] + (1 - b2) * g * g
                    mh = m[i][j] / (1 - b1 ** t)
                    vh = v[i][j] / (1 - b2 ** t)
                    params[i][j] -= lr * mh / (np.sqrt(vh) + eps)
        pv = forward(params, Xv)[-1][:, 0]
        ll = logloss(pv, Yv)
        acc = float(np.mean((pv > 0.5) == (Yv > 0.5)))
        print(f"  epoch {ep}: val logloss {ll:.4f} acc {acc:.3f}")
        if ll < best[0]:
            best = (ll, [[W.copy(), b.copy()] for W, b in params])
        lr *= 0.8
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="+")
    ap.add_argument("--out", default=os.path.join(ROOT, "agent", "ptcg", "value_weights.json"))
    ap.add_argument("--hidden", default="64,32")
    ap.add_argument("--epochs", type=int, default=12)
    args = ap.parse_args()
    Xs, Ys, Gs = [], [], []
    for path in args.data:
        d = np.load(path)
        Xs.append(d["X"]); Ys.append(d["Y"]); Gs.append(d["G"])
    X = np.concatenate(Xs).astype(np.float32)
    Y = np.concatenate(Ys).astype(np.float32)
    G = np.concatenate(Gs)
    games = np.unique(G)
    rng = np.random.default_rng(0)
    val_games = set(rng.choice(games, size=max(1, len(games) // 10), replace=False).tolist())
    vmask = np.array([g in val_games for g in G])
    Xt, Yt, Xv, Yv = X[~vmask], Y[~vmask], X[vmask], Y[vmask]
    mu = Xt.mean(0)
    sd = Xt.std(0) + 1e-6
    Xt = (Xt - mu) / sd
    Xv = (Xv - mu) / sd
    print(f"train {len(Xt)} val {len(Xv)} features {X.shape[1]}")
    # baselines
    print(f"constant: logloss {logloss(np.full(len(Yv), Yt.mean()), Yv):.4f}")
    print("logistic regression:")
    lr_best = train(Xt, Yt, Xv, Yv, [X.shape[1], 1], epochs=4, lr=5e-3)
    sizes = [X.shape[1]] + [int(h) for h in args.hidden.split(",") if h] + [1]
    print(f"MLP {sizes}:")
    best_ll, params = train(Xt, Yt, Xv, Yv, sizes, epochs=args.epochs)
    print(f"best MLP val logloss {best_ll:.4f} (logreg {lr_best[0]:.4f})")
    out = {
        "mu": mu.tolist(), "sd": sd.tolist(),
        "layers": [{"W": W.tolist(), "b": b.tolist()} for W, b in params],
        "val_logloss": best_ll, "n_features": int(X.shape[1]), "rows": len(X),
    }
    with open(args.out, "w") as f:
        json.dump(out, f)
    print(f"wrote {args.out} ({os.path.getsize(args.out) / 1024:.0f} KiB)")


if __name__ == "__main__":
    sys.exit(main())
