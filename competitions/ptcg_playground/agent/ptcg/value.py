"""Learned value function: P(player `me` wins | position at the start of me's turn).

Weights come from tools/train_value.py (value_weights.json next to this file).
Inference uses numpy when present, otherwise a pure-Python fallback.
"""

from __future__ import annotations

import json
import math
import os

from .features import N_FEATURES, features

try:
    import numpy as _np
except Exception:  # pragma: no cover - numpy is present on Kaggle
    _np = None

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "value_weights.json")


class ValueModel:
    def __init__(self, path: str = _PATH) -> None:
        with open(path) as f:
            d = json.load(f)
        if d["n_features"] != N_FEATURES:
            raise ValueError(f"value weights expect {d['n_features']} features, code has {N_FEATURES}")
        self.mu = d["mu"]
        self.sd = d["sd"]
        self.layers = [(l["W"], l["b"]) for l in d["layers"]]
        if _np is not None:
            self.np_mu = _np.array(self.mu, dtype=_np.float64)
            self.np_sd = _np.array(self.sd, dtype=_np.float64)
            self.np_layers = [(_np.array(W, dtype=_np.float64), _np.array(b, dtype=_np.float64)) for W, b in self.layers]

    def predict(self, cur: dict, me: int) -> float:
        x = features(cur, me)
        if _np is not None:
            h = (_np.array(x, dtype=_np.float64) - self.np_mu) / self.np_sd
            last = len(self.np_layers) - 1
            for i, (W, b) in enumerate(self.np_layers):
                h = h @ W + b
                if i < last:
                    h = _np.tanh(h)
            z = float(h[0])
        else:
            h = [(v - m) / s for v, m, s in zip(x, self.mu, self.sd)]
            last = len(self.layers) - 1
            for i, (W, b) in enumerate(self.layers):
                out = list(b)
                for j, hv in enumerate(h):
                    if hv:
                        row = W[j]
                        for k in range(len(out)):
                            out[k] += hv * row[k]
                h = [math.tanh(v) for v in out] if i < last else out
            z = h[0]
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))


def load() -> ValueModel | None:
    try:
        return ValueModel()
    except Exception:
        return None
