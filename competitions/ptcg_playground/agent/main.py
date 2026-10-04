"""Kaggle entry point for the PTCG AI Battle Challenge (CABT engine).

kaggle_environments exec()s this file and calls the LAST callable defined in it, so
`agent` must stay the final top-level definition. `__file__` is not set under exec(),
so the agent directory is located by looking for deck.csv + the ptcg package.
"""

import os
import sys


def _agent_dir():
    cands = []
    here = globals().get("__file__")
    if here:
        cands.append(os.path.dirname(os.path.abspath(here)))
    cands += ["/kaggle_simulations/agent", os.getcwd()]
    cands += list(reversed(sys.path))
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "deck.csv")) and os.path.isdir(os.path.join(d, "ptcg")):
            return d
    return os.getcwd()


_DIR = _agent_dir()
# kaggle_environments appends the agent dir to sys.path only while exec()ing this file and
# pops it afterwards, so insert our own entry unconditionally and import eagerly.
sys.path.insert(0, _DIR)
try:
    from ptcg.agent import Agent as _Agent
except Exception:  # keep loading: agent() falls back to a trivial legal policy
    import traceback

    traceback.print_exc()
    _Agent = None


def _read_deck():
    with open(os.path.join(_DIR, "deck.csv")) as f:
        return [int(x) for x in f.read().split() if x.strip()]


_STATE = {"agent": None, "deck": None}


def agent(obs, config=None):
    if _STATE["deck"] is None:
        _STATE["deck"] = _read_deck()
    select = obs.get("select") if hasattr(obs, "get") else obs["select"]
    if select is None:
        return list(_STATE["deck"])
    if _STATE["agent"] is None:
        try:
            if _Agent is None:
                raise ImportError("ptcg package failed to import")
            _STATE["agent"] = _Agent(_STATE["deck"], use_search=True)
        except Exception:
            import traceback

            traceback.print_exc()
            _STATE["agent"] = False
    if _STATE["agent"]:
        return _STATE["agent"](obs)
    # last-resort legal answer if the package could not be loaded
    n = len(select["option"])
    return list(range(min(max(select["minCount"], 1 if n else 0), n)))
