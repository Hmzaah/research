"""Native CABT engine access: card database and the forward-search API.

The kaggle-environments copy of ``cg/sim.py`` only declares the battle ABI, so the
search/card exports are declared here. The library is looked up in this order:

1. ``<agent dir>/cg`` (bundled with the submission archive),
2. the installed ``kaggle_environments`` package (located without importing it,
   because its ``__init__`` pulls in every environment and is slow).
"""

from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import platform

_INT_P = ctypes.POINTER(ctypes.c_int)


def _lib_name() -> str:
    system = platform.system()
    if system == "Windows":
        return "cg.dll"
    if system == "Darwin":
        return "libcg.dylib"
    if platform.machine() in ("arm64", "aarch64"):
        return "libcg-arm64.so"
    return "libcg.so"


def _candidate_dirs() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = [os.path.join(os.path.dirname(here), "cg"), os.path.join(here, "cg")]
    spec = importlib.util.find_spec("kaggle_environments")
    if spec is not None and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            dirs.append(os.path.join(loc, "envs", "cabt", "cg"))
    extra = os.environ.get("PTCG_CG_DIR")
    if extra:
        dirs.insert(0, extra)
    return dirs


def _load() -> ctypes.CDLL:
    name = _lib_name()
    for d in _candidate_dirs():
        path = os.path.join(d, name)
        if os.path.exists(path):
            return ctypes.cdll.LoadLibrary(path)
    raise OSError(f"CABT engine library {name} not found in {_candidate_dirs()}")


class SerialData(ctypes.Structure):
    _fields_ = [
        ("json", ctypes.c_char_p),
        ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ("count", ctypes.c_int),
        ("selectPlayer", ctypes.c_int),
    ]


class StartData(ctypes.Structure):
    _fields_ = [
        ("battlePtr", ctypes.c_void_p),
        ("errorPlayer", ctypes.c_int),
        ("errorType", ctypes.c_int),
    ]


def _declare(lib: ctypes.CDLL) -> ctypes.CDLL:
    lib.GameInitialize()
    lib.AllCard.restype = ctypes.c_char_p
    lib.AllAttack.restype = ctypes.c_char_p
    lib.AgentStart.restype = ctypes.c_void_p
    lib.AgentStart.argtypes = []
    lib.SearchBegin.restype = ctypes.c_char_p
    lib.SearchBegin.argtypes = [
        ctypes.c_void_p,  # agent handle
        ctypes.c_char_p,  # observation["search_begin_input"]
        ctypes.c_int,  # its length
        _INT_P,  # your deck
        _INT_P,  # your prizes
        _INT_P,  # opponent deck
        _INT_P,  # opponent prizes
        _INT_P,  # opponent hand
        _INT_P,  # opponent face-down active
        ctypes.c_int,  # manual coin
    ]
    lib.SearchStep.restype = ctypes.c_char_p
    lib.SearchStep.argtypes = [ctypes.c_void_p, ctypes.c_int64, _INT_P, ctypes.c_int]
    lib.SearchEnd.restype = None
    lib.SearchEnd.argtypes = [ctypes.c_void_p]
    lib.SearchRelease.restype = None
    lib.SearchRelease.argtypes = [ctypes.c_void_p, ctypes.c_int64]
    # battle ABI (local arena only; the Kaggle env drives battles itself)
    lib.BattleStart.restype = StartData
    lib.BattleStart.argtypes = [_INT_P]
    lib.BattleStartReverse.restype = StartData
    lib.BattleStartReverse.argtypes = [_INT_P]
    lib.BattleFinish.argtypes = [ctypes.c_void_p]
    lib.GetBattleData.restype = SerialData
    lib.GetBattleData.argtypes = [ctypes.c_void_p]
    lib.Select.restype = ctypes.c_int
    lib.Select.argtypes = [ctypes.c_void_p, _INT_P, ctypes.c_int]
    return lib


LIB = _declare(_load())
CARDS: dict[int, dict] = {c["cardId"]: c for c in json.loads(LIB.AllCard())}
ATTACKS: dict[int, dict] = {a["attackId"]: a for a in json.loads(LIB.AllAttack())}


def ints(values: list[int]) -> ctypes.Array:
    return (ctypes.c_int * max(1, len(values)))(*values)


_HANDLE = None


def _shared_handle():
    """One native search handle per process: AgentStart() allocations are never freed,
    and searches never interleave (begin..end runs synchronously inside one decision)."""
    global _HANDLE
    if _HANDLE is None:
        _HANDLE = LIB.AgentStart()
    return _HANDLE


class Searcher:
    """Thin wrapper over SearchBegin/SearchStep (shares the per-process handle)."""

    def __init__(self) -> None:
        self.handle = _shared_handle()

    def begin(
        self,
        serialized: str,
        my_deck: list[int],
        my_prize: list[int],
        opp_deck: list[int],
        opp_prize: list[int],
        opp_hand: list[int],
        opp_active: list[int],
        manual_coin: bool = False,
    ) -> dict | None:
        payload = serialized.encode("ascii")
        raw = LIB.SearchBegin(
            self.handle,
            payload,
            len(payload),
            ints(my_deck),
            ints(my_prize),
            ints(opp_deck),
            ints(opp_prize),
            ints(opp_hand),
            ints(opp_active),
            1 if manual_coin else 0,
        )
        res = json.loads(raw)
        if res.get("error", 1) != 0:
            return None
        return res["state"]

    def step(self, search_id: int, select: list[int]) -> dict | None:
        raw = LIB.SearchStep(self.handle, search_id, ints(select), len(select))
        res = json.loads(raw)
        if res.get("error", 1) != 0:
            return None
        return res["state"]

    def end(self) -> None:
        LIB.SearchEnd(self.handle)


class LocalBattle:
    """Local battle driver mirroring kaggle_environments/envs/cabt/cg/game.py."""

    def __init__(self) -> None:
        self.ptr = None

    def start(self, deck0: list[int], deck1: list[int], reverse: bool = False) -> dict | None:
        arg = ints(deck0 + deck1)
        sd = LIB.BattleStartReverse(arg) if reverse else LIB.BattleStart(arg)
        if not sd.battlePtr or sd.errorPlayer >= 0:
            self.ptr = None
            return None
        self.ptr = sd.battlePtr
        return self._data()

    def _data(self) -> dict:
        sd = LIB.GetBattleData(self.ptr)
        obs = json.loads(sd.json.decode())
        obs["search_begin_input"] = ctypes.string_at(sd.data, sd.count).decode("ascii")
        return obs

    def select(self, choice: list[int]) -> dict:
        err = LIB.Select(self.ptr, ints(choice), len(choice))
        if err != 0:
            raise IndexError(f"illegal selection {choice} (err={err})")
        return self._data()

    def finish(self) -> None:
        if self.ptr:
            LIB.BattleFinish(self.ptr)
            self.ptr = None
