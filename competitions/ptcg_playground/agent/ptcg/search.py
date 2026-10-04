"""Determinized rollout search on the native engine (SearchBegin / SearchStep).

At a searchable decision every hidden card (our deck order and face-down prizes, the
opponent's deck, hand and prizes) is sampled consistently with what has been seen. Each
candidate answer is played through the engine, then both sides follow the heuristic
policy until the start of our next turn (or the end of the game), and the resulting
position is scored. Candidates share the same samples (common random numbers) and the
weakest half is dropped at fixed fractions of the time budget (successive halving).

Time management: Kaggle gives each agent a single 600 s overage pool for the whole BO3
episode (actTimeout = 0). The per-decision budget is derived from the remaining pool.
"""

from __future__ import annotations

import math
import random
import time
from collections import Counter

from . import cards as C
from .engine import Searcher
from .policy import (
    O_END,
    O_PLAY,
    T_MAIN,
    X_SWITCH,
    X_TO_ACTIVE,
    X_TO_BENCH,
    X_TO_HAND,
    Policy,
)
from .value import load as load_value

WIN = 10000.0
STEP_LIMIT = 500
SEARCH_CONTEXTS = {X_SWITCH, X_TO_ACTIVE, X_TO_HAND, X_TO_BENCH}


class RolloutSearch:
    def __init__(
        self,
        policy: Policy,
        deck: list[int],
        rng: random.Random | None = None,
        max_decision_time: float = 0.3,
        reserve: float = 45.0,
        decisions_per_game: int = 70,
        games: int = 3,
        max_candidates: int = 10,
        opponent_library: dict[str, list[int]] | None = None,
        use_value: bool = False,
    ) -> None:
        self.policy = policy
        self.rollout_policy = Policy(deck, go_first=policy.go_first)
        self.deck = list(deck)
        self.deck_counter = Counter(deck)
        self.rng = rng or random.Random()
        self.engine = Searcher()
        self.max_decision_time = max_decision_time
        self.reserve = reserve
        self.decisions_per_game = decisions_per_game
        self.games = games
        self.max_candidates = max_candidates
        self.library = opponent_library or {}
        self.rivals: dict[tuple[int, ...], Policy] = {}
        self.stats = Counter()
        self.value = load_value() if use_value else None
        # the opponent plays the same 60 cards in every game of the match: remember the
        # highest count of each card id we have seen them reveal so far
        self.opp_known: Counter = Counter()

    # ------------------------------------------------------------------ public
    def choose(self, obs: dict) -> list[int] | None:
        sel, cur = obs.get("select"), obs.get("current")
        serialized = obs.get("search_begin_input")
        if sel is None or cur is None or not serialized:
            return None
        if cur["turn"] < 1:
            return None
        if sel["type"] != T_MAIN and (sel["context"] not in SEARCH_CONTEXTS or sel["maxCount"] != 1):
            return None
        opp = cur["players"][1 - cur["yourIndex"]]
        self._remember(opp)
        if any(p is None for p in opp["active"]):
            return None
        candidates = self._candidates(obs)
        if len(candidates) < 2:
            return candidates[0] if candidates else None
        budget = self._budget(obs)
        if budget < 0.03:
            return None
        return self._search(obs, candidates, budget)

    def _remember(self, theirs: dict) -> None:
        try:
            for cid, n in Counter(seen_ids(theirs)).items():
                self.opp_known[cid] = max(self.opp_known[cid], n)
        except (KeyError, TypeError):
            pass

    # ------------------------------------------------------------------ budget
    def _budget(self, obs: dict) -> float:
        remaining = obs.get("remainingOverageTime")
        if remaining is None:
            return self.max_decision_time
        rnd = obs["current"].get("round") or 1
        games_left = max(1, self.games - rnd + 1)
        turn = obs["current"]["turn"]
        # decisions left in this game shrink as the game goes on; never below a floor
        left_this_game = max(20, self.decisions_per_game - 2 * turn)
        expected = left_this_game + (games_left - 1) * self.decisions_per_game
        return max(0.0, min(self.max_decision_time, (float(remaining) - self.reserve) / expected))

    # ------------------------------------------------------------------ candidates
    def _candidates(self, obs: dict) -> list[list[int]]:
        sel, cur = obs["select"], obs["current"]
        scores = self.policy.scores(obs) if sel["type"] != T_MAIN else self.rollout_policy.scores(obs)
        me = cur["yourIndex"]
        hand = cur["players"][me].get("hand") or []
        seen_keys = set()
        order = sorted(range(len(sel["option"])), key=lambda i: (-scores[i], i))
        out: list[list[int]] = []
        for i in order:
            o = sel["option"][i]
            key = self._equiv_key(o, hand, sel, cur)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append([i])
        # keep END / pass options available; cap the field
        if len(out) > self.max_candidates:
            keep = out[: self.max_candidates]
            for c in out[self.max_candidates:]:
                if sel["option"][c[0]]["type"] == O_END:
                    keep.append(c)
            out = keep
        if sel["type"] != T_MAIN and sel["minCount"] == 0:
            out.append([])
        return out

    @staticmethod
    def _equiv_key(o: dict, hand: list[dict], sel: dict, cur: dict) -> tuple:
        ty = o["type"]
        cid = None
        idx = o.get("index")
        area = o.get("area")
        if area == 6:  # face-down prize cards are interchangeable
            return (ty, "prize", o.get("playerIndex"))
        if ty == O_PLAY or (area == 2 and idx is not None):
            cid = hand[idx]["id"] if idx is not None and idx < len(hand) else None
        elif area == 1 and sel.get("deck") and idx is not None and idx < len(sel["deck"]):
            cid = sel["deck"][idx]["id"]
        target = None
        ia, ii = o.get("inPlayArea"), o.get("inPlayIndex")
        if ia is not None:
            target = (ia, ii)
        if area in (4, 5) and ty in (3,):
            target = (o.get("playerIndex"), area, idx)
        if cid is not None:
            return (ty, cid, target, o.get("playerIndex"))
        return (ty, tuple(sorted((k, v) for k, v in o.items() if k != "type")))

    # ------------------------------------------------------------------ search loop
    def _search(self, obs: dict, candidates: list[list[int]], budget: float) -> list[int]:
        cur = obs["current"]
        me = cur["yourIndex"]
        start_turn = cur["turn"]
        alive = list(range(len(candidates)))
        totals = [0.0] * len(candidates)
        counts = [0] * len(candidates)
        rounds = max(1, math.ceil(math.log2(len(alive))))
        stage = 0
        t0 = time.perf_counter()
        samples = 0
        try:
            while True:
                elapsed = time.perf_counter() - t0
                if elapsed >= budget:
                    break
                if stage < rounds and len(alive) > 2 and elapsed >= budget * (stage + 1) / (rounds + 1) and samples >= 2:
                    alive.sort(key=lambda i: -totals[i] / max(1, counts[i]))
                    alive = alive[: max(2, math.ceil(len(alive) / 2))]
                    stage += 1
                det = self._determinize(obs)
                if det is None:
                    break
                root = self.engine.begin(obs["search_begin_input"], *det)
                if root is None:
                    self.stats["begin_fail"] += 1
                    break
                rival = self._rival(det, cur)
                for i in alive:
                    totals[i] += self._rollout(root["searchId"], candidates[i], me, start_turn, rival)
                    counts[i] += 1
                samples += 1
        finally:
            self.engine.end()
        self.stats["searches"] += 1
        self.stats["samples"] += samples
        if samples == 0:
            return candidates[0]
        best = max(alive, key=lambda i: (totals[i] / max(1, counts[i]), -i))
        return candidates[best]

    def _rollout(self, root_id: int, first: list[int], me: int, start_turn: int, rival: Policy) -> float:
        st = self.engine.step(root_id, first)
        if st is None:
            return self._worst()
        o = st["observation"]
        for _ in range(STEP_LIMIT):
            c, s = o["current"], o["select"]
            if c is None or s is None or c["result"] >= 0:
                break
            if c["turn"] >= start_turn + 2 and c["yourIndex"] == me:
                break
            actor = self.rollout_policy if c["yourIndex"] == me else rival
            choice = actor.choose(o)
            st = self.engine.step(st["searchId"], choice)
            if st is None:
                self.stats["step_fail"] += 1
                return self._worst()
            o = st["observation"]
        return self._evaluate(o["current"], me)

    def _evaluate(self, cur: dict | None, me: int) -> float:
        if cur is None:
            return 0.5 if self.value is not None else 0.0
        if self.value is None:
            return evaluate(cur, me)
        res = cur["result"]
        if res >= 0:
            return 1.0 if res == me else 0.0 if res == 1 - me else 0.5
        p = self.value.predict(cur, me)
        # the model is trained for the player to move; flip when evaluating the other side's turn
        return p

    def _worst(self) -> float:
        return 0.0 if self.value is not None else -WIN

    # ------------------------------------------------------------------ hidden information
    def _determinize(self, obs: dict):
        cur = obs["current"]
        me = cur["yourIndex"]
        mine, theirs = cur["players"][me], cur["players"][1 - me]
        own_unseen = list((self.deck_counter - Counter(seen_ids(mine))).elements())
        self.rng.shuffle(own_unseen)
        n_prize = sum(1 for p in mine["prize"] if p is None)
        need = n_prize + mine["deckCount"]
        if len(own_unseen) < need:
            own_unseen += [self.deck[0]] * (need - len(own_unseen))
        my_prize = own_unseen[:n_prize]
        my_deck = own_unseen[n_prize:need]

        o_seen = Counter(seen_ids(theirs))
        o_need_prize = sum(1 for p in theirs["prize"] if p is None)
        o_hand = theirs["handCount"]
        o_deck = theirs["deckCount"]
        total = o_need_prize + o_hand + o_deck
        pool = self._opponent_pool(o_seen, theirs, total)
        self.rng.shuffle(pool)
        return (
            my_deck,
            my_prize,
            pool[o_need_prize + o_hand: total],
            pool[:o_need_prize],
            pool[o_need_prize: o_need_prize + o_hand],
            [],
        )

    def _opponent_pool(self, seen: Counter, theirs: dict, total: int) -> list[int]:
        """Hidden opponent cards: a known list matching what they revealed, else rebuilt from sightings."""
        known = Counter(self.opp_known)
        for cid, n in seen.items():
            known[cid] = max(known[cid], n)
        best, best_hit = None, 0
        for deck in self.library.values():
            dc = Counter(deck)
            hit = sum(min(n, dc[c]) for c, n in known.items())
            miss = sum(max(0, n - dc[c]) for c, n in known.items())
            if miss <= 2 and hit > best_hit:
                best, best_hit = dc, hit
        if best is not None and best_hit >= 3:
            pool = list((best - seen).elements())
        else:
            # cards revealed in earlier games but not (yet) in this one are certainly hidden
            pool = list((known - seen).elements())
            for cid in known:
                if C.is_energy(cid) or C.card(cid)["aceSpec"]:
                    continue
                pool.extend([cid] * max(0, 2 - known[cid]))
        self.rng.shuffle(pool)
        pool = pool[:total]
        if len(pool) < total:
            pool.extend([self._filler_energy(theirs)] * (total - len(pool)))
        self.rng.shuffle(pool)
        return pool

    @staticmethod
    def _filler_energy(theirs: dict) -> int:
        types = Counter()
        for p in theirs["active"] + theirs["bench"]:
            if p:
                for e in p["energyCards"]:
                    if C.card(e["id"])["cardType"] == C.BASIC_ENERGY:
                        types[e["id"]] += 1
        for d in theirs["discard"]:
            if C.card(d["id"])["cardType"] == C.BASIC_ENERGY:
                types[d["id"]] += 1
        return types.most_common(1)[0][0] if types else 5

    def _rival(self, det, cur: dict) -> Policy:
        theirs = cur["players"][1 - cur["yourIndex"]]
        deck = seen_ids(theirs) + det[2] + det[3] + det[4]
        key = tuple(sorted(deck))
        pol = self.rivals.get(key)
        if pol is None:
            if len(self.rivals) > 64:
                self.rivals.clear()
            pol = self.rivals[key] = Policy(deck)
        return pol


def seen_ids(p: dict) -> list[int]:
    ids = [c["id"] for c in (p.get("hand") or [])]
    ids += [c["id"] for c in p["discard"]]
    ids += [c["id"] for c in p["prize"] if c]
    for pk in p["active"] + p["bench"]:
        if not pk:
            continue
        ids.append(pk["id"])
        ids += [c["id"] for c in pk["energyCards"]]
        ids += [c["id"] for c in pk["tools"]]
        ids += [c["id"] for c in pk["preEvolution"]]
    return ids


def _pokemon_value(pk: dict) -> float:
    c = C.card(pk["id"])
    pv = C.prize_value(pk["id"])
    v = 12.0 + 6 * C.stage(pk["id"]) + 4 * pv
    v += 9 * min(len(pk["energies"]), 4)
    frac = pk["hp"] / max(1, pk["maxHp"])
    v *= 0.5 + 0.5 * frac
    # damage this Pokémon can deal right now
    best = 0
    for a in c["attacks"]:
        if C.missing_energy(pk["energies"], C.attack_cost(a)) == 0:
            best = max(best, C.est_damage(a))
    v += best / 12
    return v


def evaluate(cur: dict | None, me: int) -> float:
    if cur is None:
        return 0.0
    res = cur["result"]
    if res >= 0:
        if res == me:
            return WIN
        if res == 1 - me:
            return -WIN
        return 0.0
    mine, theirs = cur["players"][me], cur["players"][1 - me]
    my_taken = 6 - len(mine["prize"])
    op_taken = 6 - len(theirs["prize"])
    v = 120.0 * (my_taken - op_taken)
    # being close to winning is worth more than the linear count
    v += 60.0 * (max(0, my_taken - 3) - max(0, op_taken - 3))
    for pk in mine["active"] + mine["bench"]:
        if pk:
            v += _pokemon_value(pk)
    for pk in theirs["active"] + theirs["bench"]:
        if pk:
            v -= _pokemon_value(pk)
    if not mine["bench"]:
        v -= 40
    if not theirs["bench"]:
        v += 40
    v += 2.5 * min(mine["handCount"], 10) - 1.5 * min(theirs["handCount"], 10)
    if mine["deckCount"] < 6:
        v -= 15 * (6 - mine["deckCount"])
    return v
