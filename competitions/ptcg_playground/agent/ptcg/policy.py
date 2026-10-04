"""Deck-agnostic heuristic policy for every SelectContext of the CABT engine.

The policy scores each legal option and takes the best ``k`` (``minCount <= k <= maxCount``).
It is fast (pure dict access, no engine calls) so it can drive rollouts inside the search.
Everything card-specific is derived from the engine's card database (``cards.py``).
"""

from __future__ import annotations

from collections import Counter

from . import cards as C

# SelectType
T_MAIN, T_CARD, T_ATTACHED, T_CARD_OR_ATTACHED, T_ENERGY, T_SKILL, T_ATTACK, T_EVOLVE, T_COUNT, T_YESNO, T_COND = range(11)
# OptionType
O_NUMBER, O_YES, O_NO, O_CARD, O_TOOL_CARD, O_ENERGY_CARD, O_ENERGY, O_PLAY, O_ATTACH, O_EVOLVE = range(10)
O_ABILITY, O_DISCARD, O_RETREAT, O_ATTACK, O_END, O_SKILL, O_COND = range(10, 17)
# AreaType
A_DECK, A_HAND, A_DISCARD, A_ACTIVE, A_BENCH, A_PRIZE, A_STADIUM = 1, 2, 3, 4, 5, 6, 7
A_ENERGY, A_TOOL, A_PRE, A_PLAYER, A_LOOKING = 8, 9, 10, 11, 12
# SelectContext
(
    X_MAIN, X_SETUP_ACTIVE, X_SETUP_BENCH, X_SWITCH, X_TO_ACTIVE, X_TO_BENCH, X_TO_FIELD, X_TO_HAND,
    X_DISCARD, X_TO_DECK, X_TO_DECK_BOTTOM, X_TO_PRIZE, X_NOT_MOVE, X_DAMAGE_COUNTER, X_DAMAGE_COUNTER_ANY,
    X_DAMAGE, X_REMOVE_DAMAGE_COUNTER, X_HEAL, X_EVOLVES_FROM, X_EVOLVES_TO, X_DEVOLVE, X_ATTACH_FROM,
    X_ATTACH_TO, X_DETACH_FROM, X_LOOK, X_EFFECT_TARGET, X_DISCARD_ENERGY_CARD, X_DISCARD_TOOL_CARD,
    X_SWITCH_ENERGY_CARD, X_DISCARD_CARD_OR_ATTACHED, X_DISCARD_ENERGY, X_TO_HAND_ENERGY, X_TO_DECK_ENERGY,
    X_SWITCH_ENERGY, X_SKILL_ORDER, X_ATTACK, X_DISABLE_ATTACK, X_EVOLVE, X_DRAW_COUNT, X_DAMAGE_COUNTER_COUNT,
    X_REMOVE_DAMAGE_COUNTER_COUNT, X_IS_FIRST, X_MULLIGAN, X_ACTIVATE, X_FIRST_EFFECT, X_MORE_DEVOLVE,
    X_COIN_HEAD, X_AFFECT_COND, X_RECOVER_COND,
) = range(49)

# Contexts where moving one of OUR cards is a gain (search, recover, put into play).
GAIN_CONTEXTS = {X_TO_HAND, X_TO_BENCH, X_TO_FIELD, X_TO_HAND_ENERGY, X_SETUP_BENCH}
# Contexts where moving one of OUR cards is a loss.
LOSS_CONTEXTS = {
    X_DISCARD, X_TO_DECK_BOTTOM, X_TO_PRIZE, X_DISCARD_ENERGY_CARD, X_DISCARD_TOOL_CARD,
    X_DISCARD_CARD_OR_ATTACHED, X_DISCARD_ENERGY, X_TO_DECK_ENERGY, X_DETACH_FROM,
}
# Contexts that hurt the targeted Pokémon (we want THEIR best targets, OUR least valuable).
HARM_CONTEXTS = {X_DAMAGE_COUNTER, X_DAMAGE_COUNTER_ANY, X_DAMAGE, X_EFFECT_TARGET, X_AFFECT_COND, X_DEVOLVE}
HELP_CONTEXTS = {X_REMOVE_DAMAGE_COUNTER, X_HEAL, X_RECOVER_COND}

GUST_WORDS = ("Switch in 1 of your opponent", "switch it with their Active", "Switch 1 of your opponent")
SWITCH_WORDS = ("Switch your Active Pokémon with 1 of your Benched",)


class Policy:
    def __init__(self, deck: list[int], go_first: bool = True) -> None:
        self.deck = list(deck)
        self.go_first = go_first
        self.deck_count = Counter(deck)
        ids = set(deck)
        # evolution graph within our deck, by name
        self.names_in_deck = {C.card(i)["name"] for i in ids}
        self.evolutions: dict[str, list[int]] = {}
        for i in ids:
            ef = C.evolves_from(i)
            if ef:
                self.evolutions.setdefault(ef, []).append(i)
        self.top_damage = max((C.best_attack_damage(i) for i in ids if C.is_pokemon(i)), default=0)
        self.attackers = {i for i in ids if C.is_pokemon(i) and C.best_attack_damage(i) >= 0.6 * self.top_damage}
        # energy types our attackers ask for
        need = Counter()
        for i in self.attackers:
            for a in C.card(i)["attacks"]:
                for t in C.attack_cost(a):
                    if t != C.COLORLESS:
                        need[t] += 1
        self.energy_need = need

    # ------------------------------------------------------------------ helpers
    def choose(self, obs: dict) -> list[int]:
        sel = obs["select"]
        n = len(sel["option"])
        if n == 0:
            return []
        scores = self.scores(obs)
        return self.pick(sel, scores)

    @staticmethod
    def pick(sel: dict, scores: list[float]) -> list[int]:
        n = len(sel["option"])
        lo = max(0, min(sel["minCount"], n))
        hi = max(lo, min(sel["maxCount"], n))
        order = sorted(range(n), key=lambda i: (-scores[i], i))
        take = lo
        while take < hi and scores[order[take]] > 0:
            take += 1
        return order[:take]

    def scores(self, obs: dict) -> list[float]:
        sel, cur = obs["select"], obs["current"]
        st = _State(cur)
        t, ctx = sel["type"], sel["context"]
        opts = sel["option"]
        if t == T_MAIN:
            return self._main(st, opts)
        if t == T_YESNO:
            return [self._yes_no(st, ctx, sel) if o["type"] == O_YES else 0.0 for o in opts]
        if t == T_COUNT:
            return self._count(st, ctx, opts)
        if ctx == X_SKILL_ORDER:
            return [1.0] * len(opts)
        if t == T_ATTACK or ctx in (X_ATTACK, X_DISABLE_ATTACK):
            return [10.0 + C.est_damage(o.get("attackId", 0)) / 10 for o in opts]
        if t == T_COND:
            order = {3: 5, 2: 4, 4: 3, 1: 2, 0: 1}  # paralyze > sleep > confuse > burn > poison
            sign = -1.0 if ctx == X_RECOVER_COND else 1.0
            return [sign * order.get(o.get("specialConditionType", 0), 0) + 6 for o in opts]
        return [self._option_value(st, sel, o) for o in opts]

    # ------------------------------------------------------------------ MAIN
    def _main(self, st: _State, opts: list[dict]) -> list[float]:
        runaway = (st.cur.get("turnActionCount") or 0) > 80
        out = []
        for o in opts:
            ty = o["type"]
            if runaway:
                out.append(5.0 if ty == O_ATTACK else 1.0 if ty == O_END else -50.0)
                continue
            if ty == O_END:
                out.append(0.0)
            elif ty == O_ATTACK:
                out.append(self._attack_score(st, o.get("attackId", 0)))
            elif ty == O_EVOLVE:
                out.append(self._evolve_score(st, o))
            elif ty == O_ATTACH:
                out.append(self._attach_score(st, o))
            elif ty == O_PLAY:
                out.append(self._play_score(st, o))
            elif ty == O_ABILITY:
                out.append(self._ability_score(st, o))
            elif ty == O_RETREAT:
                out.append(self._retreat_score(st))
            elif ty == O_DISCARD:
                out.append(-5.0)
            else:
                out.append(-1.0)
        return out

    def _ability_score(self, st: _State, o: dict) -> float:
        base = 30.0 if o.get("area") == A_STADIUM else 55.0
        src = None
        if o.get("area") in (A_ACTIVE, A_BENCH):
            pk = st.my_pokemon(o.get("area"), o.get("index"))
            src = pk["id"] if pk else None
        elif o.get("area") == A_STADIUM:
            stad = st.cur.get("stadium") or []
            src = stad[0]["id"] if stad else None
        text = C.card_text(src) if src is not None else ""
        if _draws_cards(text):
            return base * self._draw_ok(st)
        return base

    def _draw_ok(self, st: _State) -> float:
        """Multiplier for card-draw actions: avoid decking ourselves out."""
        deck = st.me_p["deckCount"]
        if deck <= 2:
            return -0.5
        if deck <= 6:
            return 0.15
        if deck <= 10:
            return 0.5
        return 1.0

    def _attack_score(self, st: _State, attack_id: int) -> float:
        act = st.my_active
        opp = st.opp_active
        dmg = C.est_damage(attack_id)
        if act is not None and opp is not None:
            dmg = _apply_wr(dmg, act["id"], opp["id"])
            if dmg >= opp["hp"] > 0:
                return 30.0 + 20 * C.prize_value(opp["id"]) + dmg / 100
        return 20.0 + dmg / 10

    def _evolve_score(self, st: _State, o: dict) -> float:
        evo = st.hand_card(o.get("index", -1))
        target = st.my_pokemon(o.get("inPlayArea"), o.get("inPlayIndex"))
        s = 80.0
        if evo is not None:
            s += 5 * C.stage(evo) + C.best_attack_damage(evo) / 50
        if target is not None and o.get("inPlayArea") == A_ACTIVE:
            s += 3
        return s

    def _attach_score(self, st: _State, o: dict) -> float:
        energy = st.hand_card(o.get("index", -1))
        target = st.my_pokemon(o.get("inPlayArea"), o.get("inPlayIndex"))
        if energy is None or target is None:
            return 10.0
        if not C.is_energy(energy):  # attaching a non-energy card (rare)
            return 20.0
        is_active = o.get("inPlayArea") == A_ACTIVE
        v = 25.0 + self._energy_target_value(st, target, C.card(energy)["energyType"], is_active)
        if is_active and not st.cur.get("retreated") and not self._can_attack(target):
            # stuck active: one more energy lets it retreat into a ready benched attacker
            rc = C.card(target["id"])["retreatCost"]
            if len(target["energies"]) + 1 >= rc > len(target["energies"]) and any(
                self._can_attack(p) for p in st.me_p["bench"]
            ):
                v = max(v, 66.0)
        return v

    def _energy_target_value(self, st: _State, pk: dict, etype: int, is_active: bool) -> float:
        best_gain = 0.0
        provided = pk["energies"]
        cid = pk["id"]
        line_top = self._line_top(cid)
        attacks = list(C.card(cid)["attacks"])
        if line_top != cid:
            attacks += C.card(line_top)["attacks"]
        for a in attacks:
            cost = C.attack_cost(a)
            if not cost:
                continue
            miss = C.missing_energy(provided, cost)
            if miss == 0:
                continue
            if C.needs_type(provided, cost, etype if etype not in (0,) else C.COLORLESS) or etype == C.RAINBOW:
                gain = C.est_damage(a) / 8 + (12 if miss == 1 else 4)
                best_gain = max(best_gain, gain)
        if best_gain == 0:
            return -10.0
        if is_active:
            best_gain += 6
        if cid in self.attackers or line_top in self.attackers:
            best_gain += 8
        return best_gain

    def _basic_of(self, stage1_name: str | None) -> str | None:
        """Name of the Basic a Stage 1 (given by name) evolves from, looked up in our deck."""
        for i in self.deck_count:
            c = C.card(i)
            if c["name"] == stage1_name:
                return c["evolvesFrom"]
        return None

    def _line_top(self, cid: int) -> int:
        """Most evolved card in our deck that this Pokémon can become."""
        name = C.card(cid)["name"]
        best = cid
        for _ in range(2):
            nxt = self.evolutions.get(name)
            if not nxt:
                break
            best = max(nxt, key=C.best_attack_damage)
            name = C.card(best)["name"]
        return best

    def _play_score(self, st: _State, o: dict) -> float:
        cid = st.hand_card(o.get("index", -1))
        if cid is None:
            return 10.0
        c = C.card(cid)
        ct = c["cardType"]
        hand_n = st.me_p["handCount"]
        if ct == C.POKEMON:
            if not c["basic"]:
                return 30.0
            bench = len(st.me_p["bench"])
            if bench >= st.me_p["benchMax"]:
                return -20.0
            evolves = c["name"] in self.evolutions
            if bench < 2:
                return 72.0 + (5 if evolves else 0)
            if evolves:
                return 60.0
            return 35.0 if bench < 4 else 10.0
        text = C.card_text(cid)
        if ct == C.SUPPORTER:
            if any(w in text for w in GUST_WORDS):
                return 74.0 if self._gust_ko_possible(st) else -5.0
            draw = C.draw_amount(cid)
            if draw:
                if "Shuffle your hand" in text or "shuffle your hand" in text:
                    gain = draw - hand_n
                    return (30.0 + 6 * gain) * self._draw_ok(st) if gain > 0 else -2.0
                return (62.0 if hand_n <= 4 else 45.0 if hand_n <= 7 else 15.0) * self._draw_ok(st)
            if "Search your deck" in text:
                return 55.0 * (1.0 if st.me_p["deckCount"] > 2 else 0.2)
            return 40.0
        if ct == C.ITEM:
            if "Rare Candy" in c["name"] or "Stage 2 card in your hand" in text:
                return 85.0
            if any(w in text for w in SWITCH_WORDS):
                return self._switch_value(st)
            if any(w in text for w in GUST_WORDS):
                return 74.0 if self._gust_ko_possible(st) else -5.0
            if "discard 2 other cards" in text or "discard 3 other cards" in text:
                return 30.0 if hand_n >= 5 else 12.0
            if "Search your deck" in text:
                return 58.0
            if "from your discard pile" in text:
                return 32.0 if st.me_p["discard"] else -5.0
            return 42.0
        if ct == C.TOOL:
            return 36.0
        if ct == C.STADIUM:
            stad = st.cur.get("stadium") or []
            if stad and stad[0].get("playerIndex") == st.me:
                return -5.0
            return 30.0
        return 20.0

    def _switch_value(self, st: _State) -> float:
        act = st.my_active
        if act is None or not st.me_p["bench"]:
            return -10.0
        if self._can_attack(act):
            return -5.0
        if any(self._can_attack(p) for p in st.me_p["bench"]):
            return 64.0
        return 5.0

    def _retreat_score(self, st: _State) -> float:
        act = st.my_active
        if act is None or not st.me_p["bench"]:
            return -100.0
        act_ready = self._can_attack(act)
        best_bench = max(st.me_p["bench"], key=lambda p: self._active_value(st, p))
        if not act_ready and self._can_attack(best_bench):
            return 50.0
        opp = st.opp_active
        if opp is not None and act_ready is False and act["hp"] <= 60 and C.prize_value(act["id"]) >= 2:
            return 20.0
        return -40.0

    def _can_attack(self, pk: dict) -> bool:
        return any(C.missing_energy(pk["energies"], C.attack_cost(a)) == 0 for a in C.card(pk["id"])["attacks"])

    def _gust_ko_possible(self, st: _State) -> bool:
        act = st.my_active
        if act is None:
            return False
        dmg = self._ready_damage(act)
        if dmg <= 0:
            return False
        for p in st.op_p["bench"]:
            if _apply_wr(dmg, act["id"], p["id"]) >= p["hp"] and C.prize_value(p["id"]) >= 1:
                opp = st.opp_active
                if opp is None or _apply_wr(dmg, act["id"], opp["id"]) < opp["hp"] or C.prize_value(p["id"]) > C.prize_value(opp["id"]):
                    return True
        return False

    def _ready_damage(self, pk: dict, extra: int = 0) -> int:
        best = 0
        for a in C.card(pk["id"])["attacks"]:
            if C.missing_energy(pk["energies"], C.attack_cost(a)) <= extra:
                best = max(best, C.est_damage(a))
        return best

    # ------------------------------------------------------------------ yes / no / counts
    def _yes_no(self, st: _State, ctx: int, sel: dict) -> float:
        if ctx == X_IS_FIRST:
            return 1.0 if self.go_first else -1.0
        return 1.0  # mulligan draw, optional effects, coin choices: take them

    def _count(self, st: _State, ctx: int, opts: list[dict]) -> list[float]:
        nums = [o.get("number", 0) for o in opts]
        if ctx == X_DRAW_COUNT:
            deck = st.me_p["deckCount"]
            return [float(n) if n <= max(0, deck - 3) else -float(n) for n in nums]
        return [float(n) for n in nums]

    # ------------------------------------------------------------------ generic option valuation
    def _option_value(self, st: _State, sel: dict, o: dict) -> float:
        ctx = sel["context"]
        ty = o["type"]
        if ty in (O_YES, O_NO):
            return 1.0 if ty == O_YES else 0.0
        if ty == O_NUMBER:
            return float(o.get("number", 0))
        if ty == O_EVOLVE:
            return self._evolve_score(st, o)
        if ty == O_ATTACK:
            return 10 + C.est_damage(o.get("attackId", 0)) / 10
        if ty == O_SKILL:
            return 1.0
        owner = o.get("playerIndex", st.me)
        mine = owner == st.me
        area = o.get("area")
        if ty == O_ENERGY or ty == O_ENERGY_CARD:
            return self._attached_energy_value(st, sel, o, mine)
        if ty == O_TOOL_CARD:
            return (-1.0 if mine else 1.0) * 5
        # O_CARD
        if area in (A_ACTIVE, A_BENCH):
            pk = st.pokemon(owner, area, o.get("index", 0))
            if pk is None:
                return 0.0
            return self._pokemon_target_value(st, sel, pk, mine, area)
        cid = st.card_at(owner, area, o.get("index", 0), sel)
        if cid is None:
            # face-down prize or unknown: neutral but positive in gain contexts
            return 1.0
        if ctx == X_SETUP_ACTIVE:
            return self._starter_value(cid)
        if ctx in GAIN_CONTEXTS or ctx in (X_ATTACH_FROM, X_ATTACH_TO, X_LOOK, X_NOT_MOVE):
            v = self._need(st, cid, sel)
            return v if mine else -v
        if ctx == X_TO_DECK:
            # recovering cards from discard into deck is usually a gain; from hand a loss
            v = self._need(st, cid, sel)
            if area == A_DISCARD:
                return v if mine else -v
            return -v if mine else v
        if ctx in LOSS_CONTEXTS:
            v = self._keep(st, cid)
            return -v if mine else v
        return self._need(st, cid, sel) if mine else 0.0

    def _starter_value(self, cid: int) -> float:
        c = C.card(cid)
        if not c["basic"]:
            return -100.0
        v = c["hp"] / 20 - 3 * c["retreatCost"]
        if c["name"] in self.evolutions:
            v -= 2  # prefer to keep evolving basics safe on the bench
        if cid in self.attackers:
            v += 4
        if c["ex"]:
            v -= 3
        return v + 50

    def _pokemon_target_value(self, st: _State, sel: dict, pk: dict, mine: bool, area: int) -> float:
        ctx = sel["context"]
        if ctx in (X_SWITCH, X_TO_ACTIVE):
            if mine:
                return 50 + self._active_value(st, pk)
            return 50 + self._gust_value(st, pk)
        if ctx in HARM_CONTEXTS:
            v = self._harm_value(st, pk, sel)
            return v if not mine else -v
        if ctx in HELP_CONTEXTS:
            dmg = pk["maxHp"] - pk["hp"]
            v = dmg / 10 + 5 * C.prize_value(pk["id"]) if dmg > 0 else -1
            return v if mine else -v
        if ctx in (X_ATTACH_FROM, X_ATTACH_TO):
            if not mine:
                return -5.0
            etype = None
            card_ref = sel.get("contextCard") or None
            if card_ref is not None and C.is_energy(card_ref["id"]):
                etype = C.card(card_ref["id"])["energyType"]
            v = self._energy_target_value(st, pk, etype if etype is not None else C.COLORLESS, area == A_ACTIVE)
            return 30 + v
        if ctx in (X_EVOLVES_FROM, X_EVOLVES_TO, X_EVOLVE):
            return 10 + C.stage(pk["id"]) if mine else 1
        if ctx in LOSS_CONTEXTS or ctx == X_TO_HAND or ctx == X_TO_DECK:
            # bouncing / discarding a Pokémon in play: ours is a loss, theirs a gain
            v = self._board_value(pk)
            return -v if mine else v
        v = self._board_value(pk)
        return v if mine else -v

    def _active_value(self, st: _State, pk: dict) -> float:
        opp = st.opp_active
        v = 0.0
        dmg = self._ready_damage(pk)
        if dmg > 0:
            v += 20 + dmg / 10
            if opp is not None and _apply_wr(dmg, pk["id"], opp["id"]) >= opp["hp"]:
                v += 25
        else:
            v += max(0, 10 - 4 * C.missing_energy(pk["energies"], _cheapest_cost(pk["id"])))
        v += pk["hp"] / 40
        v -= 2 * C.card(pk["id"])["retreatCost"]
        if opp is not None:
            od = C.best_attack_damage(opp["id"])
            if _apply_wr(od, opp["id"], pk["id"]) >= pk["hp"]:
                v -= 6 * C.prize_value(pk["id"])
        return v

    def _gust_value(self, st: _State, pk: dict) -> float:
        act = st.my_active
        v = 2.0 * C.prize_value(pk["id"])
        if act is not None:
            dmg = self._ready_damage(act)
            if dmg > 0 and _apply_wr(dmg, act["id"], pk["id"]) >= pk["hp"]:
                v += 30 + 10 * C.prize_value(pk["id"])
        # strand something that cannot attack and is costly to retreat
        if not self._can_attack(pk):
            v += C.card(pk["id"])["retreatCost"]
        v += (pk["maxHp"] - pk["hp"]) / 30
        return v

    def _harm_value(self, st: _State, pk: dict, sel: dict) -> float:
        counters = sel.get("remainDamageCounter") or 1
        dmg = 10 * counters if sel["context"] != X_DAMAGE else 30
        v = C.prize_value(pk["id"]) * 3 + (pk["maxHp"] - pk["hp"]) / 20
        if pk["hp"] <= dmg:
            v += 20 * C.prize_value(pk["id"])
        if C.card(pk["id"])["tera"]:
            v -= 1
        return v + 5

    def _board_value(self, pk: dict) -> float:
        return 5 + 5 * C.prize_value(pk["id"]) + 3 * len(pk["energies"]) + pk["hp"] / 50

    def _attached_energy_value(self, st: _State, sel: dict, o: dict, mine: bool) -> float:
        pk = st.pokemon(o.get("playerIndex", st.me), o.get("area"), o.get("index", 0))
        ctx = sel["context"]
        base = 3.0
        if pk is not None:
            base += 2 * C.prize_value(pk["id"])
            if o.get("area") == A_ACTIVE:
                base += 2
        if ctx in (X_SWITCH_ENERGY_CARD, X_SWITCH_ENERGY) and mine:
            # move energy away from a Pokémon that does not need it
            if pk is not None and not self._can_attack(pk):
                return 4.0
            return 1.0
        if ctx in LOSS_CONTEXTS or ctx == X_SWITCH_ENERGY or ctx == X_DISCARD_ENERGY:
            return -base if mine else base
        return base if mine else -base

    # ------------------------------------------------------------------ card desirability
    def _need(self, st: _State, cid: int, sel: dict) -> float:
        """How much we want this card (to hand / into play)."""
        c = C.card(cid)
        ct = c["cardType"]
        in_hand = st.hand_ids.count(cid)
        in_play_names = st.my_inplay_names
        dup = 0.6 ** in_hand
        if ct == C.POKEMON:
            if c["basic"]:
                bench_room = st.me_p["benchMax"] - len(st.me_p["bench"])
                base = 30.0 if c["name"] in self.evolutions else 18.0
                if len(in_play_names) <= 2:
                    base += 15
                if bench_room <= 0 and sel["context"] in (X_TO_BENCH, X_TO_FIELD):
                    return -5.0
                return base * dup + (3 if cid in self.attackers else 0)
            pre = c["evolvesFrom"]
            base = 20.0
            if pre in in_play_names:
                base = 45.0 + 5 * C.stage(cid)
            elif c["stage2"] and self._basic_of(pre) in in_play_names and st.has_rare_candy:
                base = 56.0
            elif pre in st.hand_names:
                base = 30.0
            elif c["stage2"] and self._basic_of(pre) in in_play_names:
                base = 32.0
            if cid in self.attackers:
                base += 8 + 6 * (C.best_attack_damage(cid) >= self.top_damage)
            return base * dup
        if ct in (C.BASIC_ENERGY, C.SPECIAL_ENERGY):
            et = c["energyType"]
            hand_energy = sum(1 for h in st.hand_ids if C.is_energy(h))
            base = 16.0 + (6 if self.energy_need.get(et) else 0) + (10 if hand_energy == 0 else 0)
            return base * (0.8 ** hand_energy)
        if ct == C.SUPPORTER:
            has_sup = any(C.card(h)["cardType"] == C.SUPPORTER for h in st.hand_ids)
            return (32.0 if not has_sup else 14.0) * dup
        if ct == C.ITEM:
            if "Rare Candy" in c["name"]:
                return 28.0 * dup
            return 20.0 * dup
        if ct == C.TOOL:
            return 12.0 * dup
        if ct == C.STADIUM:
            return 10.0 * dup
        return 8.0

    def _keep(self, st: _State, cid: int) -> float:
        """How much we want to keep this card (inverse discard priority)."""
        c = C.card(cid)
        ct = c["cardType"]
        same = st.hand_ids.count(cid)
        v = 10.0
        if ct == C.POKEMON:
            v = 22.0
            if not c["basic"] and c["evolvesFrom"] in st.my_inplay_names:
                v = 34.0
            if cid in self.attackers:
                v += 6
        elif ct in (C.BASIC_ENERGY, C.SPECIAL_ENERGY):
            hand_energy = sum(1 for h in st.hand_ids if C.is_energy(h))
            v = 20.0 if hand_energy <= 1 else 9.0
            if ct == C.SPECIAL_ENERGY:
                v += 4
        elif ct == C.SUPPORTER:
            v = 24.0
        elif ct == C.ITEM:
            v = 18.0 if "Rare Candy" not in c["name"] else 26.0
        elif ct == C.TOOL:
            v = 12.0
        elif ct == C.STADIUM:
            v = 8.0
        if c["aceSpec"]:
            v += 8
        return v - 3 * max(0, same - 1)


def _draws_cards(text: str) -> bool:
    t = text.lower()
    return "draw" in t or "search your deck" in t or "top card" in t or "top 2 cards" in t or "look at the top" in t


def _apply_wr(dmg: int, attacker_id: int, defender_id: int) -> int:
    if dmg <= 0:
        return dmg
    at = C.card(attacker_id)["energyType"]
    d = C.card(defender_id)
    if d["weakness"] is not None and d["weakness"] == at:
        dmg *= 2
    if d["resistance"] is not None and d["resistance"] == at:
        dmg -= 30
    return dmg


def _cheapest_cost(cid: int) -> tuple[int, ...]:
    atks = C.card(cid)["attacks"]
    if not atks:
        return ()
    return min((C.attack_cost(a) for a in atks), key=len)


class _State:
    """Convenience view of `current` from the deciding player's perspective."""

    __slots__ = ("cur", "hand_ids", "hand_names", "has_rare_candy", "me", "me_p", "my_inplay_names", "op_p")

    def __init__(self, cur: dict) -> None:
        self.cur = cur
        self.me = cur["yourIndex"]
        self.me_p = cur["players"][self.me]
        self.op_p = cur["players"][1 - self.me]
        hand = self.me_p.get("hand") or []
        self.hand_ids = [h["id"] for h in hand]
        self.hand_names = {C.card(i)["name"] for i in self.hand_ids}
        self.my_inplay_names = {C.card(p["id"])["name"] for p in self.me_p["active"] + self.me_p["bench"] if p}
        self.has_rare_candy = any("Rare Candy" in n for n in self.hand_names)

    @property
    def my_active(self) -> dict | None:
        a = self.me_p["active"]
        return a[0] if a and a[0] else None

    @property
    def opp_active(self) -> dict | None:
        a = self.op_p["active"]
        return a[0] if a and a[0] else None

    def hand_card(self, index: int) -> int | None:
        hand = self.me_p.get("hand") or []
        if 0 <= index < len(hand):
            return hand[index]["id"]
        return None

    def my_pokemon(self, area: int | None, index: int | None) -> dict | None:
        return self.pokemon(self.me, area, index or 0)

    def pokemon(self, owner: int, area: int | None, index: int) -> dict | None:
        p = self.cur["players"][owner]
        lst = p["active"] if area == A_ACTIVE else p["bench"] if area == A_BENCH else None
        if lst and 0 <= index < len(lst):
            return lst[index]
        return None

    def card_at(self, owner: int, area: int | None, index: int, sel: dict) -> int | None:
        p = self.cur["players"][owner]
        lst = None
        if area == A_DECK:
            lst = sel.get("deck")
        elif area == A_HAND:
            lst = p.get("hand")
        elif area == A_DISCARD:
            lst = p.get("discard")
        elif area == A_PRIZE:
            lst = p.get("prize")
        elif area == A_LOOKING:
            lst = self.cur.get("looking")
        elif area == A_STADIUM:
            lst = self.cur.get("stadium")
        if lst and 0 <= index < len(lst) and lst[index]:
            return lst[index]["id"]
        return None
