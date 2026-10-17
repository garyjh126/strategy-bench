"""``play`` mode: the subject plays complete hands against a fixed opponent policy.

Used to cross-check the direct-mode estimate (head-to-head value by simulation) and to record
hand histories for replays. Seats alternate (hand ``h``: subject in seat ``h % 2``). Chance
and the opponent are sampled from a per-hand RNG, so a match is reproducible from its seed
and the call cache.

Each subject decision is a fresh query with its own sample key (``play:<seed>:<hand>:<n>``),
independent of the direct-mode samples. If every attempt fails, the subject's action is drawn
uniformly from the legal actions and flagged as a fallback; fallbacks are counted and
reported, never hidden.
"""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from open_spiel.python import policy as policy_lib

from strategybench.adapters.base import DistributionClient, Prompt, TextClient
from strategybench.adapters.cache import CallCache, cache_key
from strategybench.estimation.direct import CallBudget, CallLog, Reliability, TextQuerier, tally
from strategybench.games.base import GameSpec
from strategybench.prompts.base import PromptTemplate


@dataclass
class PlayResult:
    opponent: str
    n_hands: int
    seed: int
    #: Per seat (subject in seat i): number of hands, mean subject payoff, standard error.
    seat_hands: list[int]
    seat_mean: list[float]
    seat_stderr: list[float]
    subject_decisions: int = 0
    fallbacks: int = 0
    reliability: Reliability = field(default_factory=Reliability)

    def ci95(self, seat: int) -> tuple[float, float]:
        m, se = self.seat_mean[seat], self.seat_stderr[seat]
        return m - 1.96 * se, m + 1.96 * se

    def as_dict(self) -> dict[str, Any]:
        return {
            "opponent": self.opponent,
            "n_hands": self.n_hands,
            "seed": self.seed,
            "seat_hands": self.seat_hands,
            "seat_mean": self.seat_mean,
            "seat_stderr": self.seat_stderr,
            "seat_ci95": [self.ci95(i) for i in range(2)],
            "subject_decisions": self.subject_decisions,
            "fallbacks": self.fallbacks,
            "fallback_rate": self.fallbacks / max(self.subject_decisions, 1),
        }


class _DistributionQuerier:
    """One cached call per distinct prompt (a distribution client's answer is deterministic)."""

    def __init__(self, client: DistributionClient, cache: CallCache | None, budget: CallBudget) -> None:
        self.client, self.cache, self.budget = client, cache, budget
        self._memo: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def probabilities(self, prompt: Prompt, labels: dict[int, str]) -> dict[int, float] | None:
        c = self.client
        key = cache_key(c.provider, c.model_id, c.params, prompt.hash, 0, 0)
        with self._lock:
            record = self._memo.get(key) or (self.cache.get(key) if self.cache else None)
            if record is None:
                self.budget.charge()
                reply = c.distribution(prompt)
                self.budget.record(reply.input_tokens, reply.output_tokens)
                record = {
                    "dist": reply.probs,
                    "input_tokens": reply.input_tokens,
                    "output_tokens": reply.output_tokens,
                    "extra": reply.extra,
                    "latency_s": 0.0,
                    "timestamp": "",
                }
                if self.cache:
                    self.cache.put(key, record)
            self._memo[key] = record
        dist = record["dist"]
        if set(dist) != set(labels.values()) or abs(sum(dist.values()) - 1.0) > 1e-6:
            return None
        return {a: float(dist[lab]) for a, lab in labels.items()}


def expected_subject_decisions(game: Any, subject: policy_lib.Policy, opponent: policy_lib.Policy) -> float:
    """Expected number of subject decisions per hand, averaged over the two seats (exact)."""
    total = 0.0
    for seat in range(game.num_players()):

        def walk(state, p: float, seat: int = seat) -> float:
            if state.is_terminal() or p == 0.0:
                return 0.0
            if state.is_chance_node():
                outcomes = state.chance_outcomes()
                here = 0.0
            else:
                mover = subject if state.current_player() == seat else opponent
                outcomes = list(mover.action_probabilities(state).items())
                here = p if state.current_player() == seat else 0.0
            return here + sum(walk(state.child(a), p * q) for a, q in outcomes)

        total += walk(game.new_initial_state(), 1.0)
    return total / game.num_players()


def _draw(rng: np.random.Generator, probs: dict[int, float]) -> int:
    actions = list(probs)
    p = np.array([probs[a] for a in actions], dtype=float)
    return int(actions[rng.choice(len(actions), p=p / p.sum())])


def play_match(
    spec: GameSpec,
    template: PromptTemplate,
    client: TextClient | DistributionClient,
    opponent: policy_lib.Policy,
    opponent_name: str,
    n_hands: int,
    seed: int = 0,
    max_retries: int = 2,
    cache: CallCache | None = None,
    log: CallLog | None = None,
    hand_log: CallLog | None = None,
    budget: CallBudget | None = None,
    concurrency: int = 1,
) -> PlayResult:
    game = spec.load()
    log, hand_log, budget = log or CallLog(None), hand_log or CallLog(None), budget or CallBudget()
    is_text = isinstance(client, TextClient)
    text_q = TextQuerier(client, spec.vocabulary(), max_retries, cache, budget) if is_text else None
    dist_q = None if is_text else _DistributionQuerier(client, cache, budget)

    def play_hand(hand: int):
        rng = np.random.default_rng([seed, hand])
        seat = hand % 2
        state = game.new_initial_state()
        events, attempts, n = [], [], 0
        while not state.is_terminal():
            if state.is_chance_node():
                action = _draw(rng, dict(state.chance_outcomes()))
                events.append({"chance": action})
            else:
                player = state.current_player()
                labels = spec.action_labels(state)
                infostate = state.information_state_string()
                fallback = False
                if player == seat:
                    prompt = template.render(spec, state)
                    if text_q is not None:
                        records, action = text_q.sample(
                            prompt, labels, infostate, seat, f"play:{seed}:{hand}:{n}"
                        )
                        attempts.append((records, action))
                    else:
                        probs = dist_q.probabilities(prompt, labels)
                        action = _draw(rng, probs) if probs else None
                    if action is None:
                        action, fallback = int(rng.choice(state.legal_actions())), True
                    n += 1
                else:
                    action = _draw(rng, opponent.action_probabilities(state))
                events.append(
                    {
                        "player": player,
                        "subject": player == seat,
                        "infostate": infostate,
                        "action": action,
                        "label": labels[action],
                        "fallback": fallback,
                    }
                )
            state.apply_action(action)
        return hand, seat, float(state.returns()[seat]), events, attempts

    payoffs: list[list[float]] = [[], []]
    result = PlayResult(opponent_name, n_hands, seed, [0, 0], [0.0, 0.0], [0.0, 0.0])
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(play_hand, h) for h in range(n_hands)]
        try:
            for future in as_completed(futures):
                hand, seat, payoff, events, attempts = future.result()
                payoffs[seat].append(payoff)
                for records, action in attempts:
                    for r in records:
                        log.write({**r, "mode": "play", "hand": hand})
                    tally(result.reliability, records, action, budget.cost_fn)
                subject_events = [e for e in events if e.get("subject")]
                result.subject_decisions += len(subject_events)
                result.fallbacks += sum(e["fallback"] for e in subject_events)
                hand_log.write(
                    {"hand": hand, "subject_seat": seat, "subject_payoff": payoff, "events": events}
                )
        except BaseException:
            pool.shutdown(wait=True, cancel_futures=True)
            raise

    for seat in range(2):
        x = np.array(payoffs[seat])
        result.seat_hands[seat] = len(x)
        result.seat_mean[seat] = float(x.mean()) if len(x) else math.nan
        result.seat_stderr[seat] = float(x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 1 else math.nan
    return result
