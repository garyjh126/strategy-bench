"""A table: one game, a policy per seat, the hand in progress and the hands already played.

Hidden information. While a hand is in progress and at least one seat is human, the board is
shown from one human's point of view (the human to act, else the last human who acted): any
event that seat cannot observe (see ``GameEntry.observers``) is replaced by a placeholder, and
bots' action probabilities, which depend on their private information, are withheld. When the
hand ends, everything is revealed. Sessions without humans are always fully revealed.
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pyspiel

from sbgui.catalog import GameEntry, seat_name
from sbgui.policies import Decision, SeatPolicy
from sbgui.profiles import ProfileManager, guarantee_text

SEAT_KINDS = {"human": "Human", "uniform": "Uniform random", "cfr": "CFR profile", "run": "Run strategy"}
#: Finished hands included in each view (all of them are kept for export).
VIEW_HISTORY = 30
MAX_HANDS = 5000


class Conflict(Exception):
    """The request does not fit the table's current state (stale ply, not your turn, ...)."""


@dataclass
class Seat:
    kind: str
    name: str
    detail: str
    policy: SeatPolicy | None = None
    run_id: str | None = None

    @property
    def kind_name(self) -> str:
        return SEAT_KINDS[self.kind]

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "kind_name": self.kind_name, "name": self.name, "detail": self.detail}


@dataclass
class Event:
    ply: int
    kind: str  # "chance" or "move"
    player: int | None
    action: int
    text: str
    label: str | None
    observers: list[int]
    #: Probability of this outcome (chance odds, or the bot's probability of its action).
    prob: float | None = None
    #: A bot's full action distribution: [(label, probability), ...].
    probs: list[tuple[str, float]] | None = None
    #: For a human move: the CFR profile's probability of the chosen action, if it was ready.
    coach_prob: float | None = None
    note: str | None = None

    def as_dict(self, visible: bool, revealed: bool) -> dict[str, Any]:
        d: dict[str, Any] = {"ply": self.ply, "kind": self.kind, "player": self.player, "hidden": not visible}
        if visible:
            d.update(text=self.text, label=self.label, action=self.action)
            if self.kind == "chance":
                d["prob"] = self.prob
        else:
            d["text"] = self._placeholder()
        if revealed and self.probs is not None:
            d["probs"] = [{"label": lab, "p": p} for lab, p in self.probs]
            d["prob"] = self.prob
        if self.coach_prob is not None:
            d["coach_prob"] = self.coach_prob
        if self.note:
            d["note"] = self.note
        return d

    def _placeholder(self) -> str:
        who = ", ".join(seat_name(p) for p in self.observers)
        if self.kind == "move":
            return f"{seat_name(self.player)} moved (hidden from you)"
        if not self.observers:
            return "Hidden chance outcome"
        return f"Private chance outcome for {who} (hidden from you)"


class Session:
    def __init__(
        self,
        sid: str,
        entry: GameEntry,
        seats: list[Seat],
        profiles: ProfileManager,
        seed: int,
    ) -> None:
        self.id = sid
        self.entry = entry
        self.seats = seats
        self.profiles = profiles
        self.seed = seed
        self.rng = random.Random(seed)
        self.lock = threading.RLock()
        self.created = datetime.now(UTC).isoformat(timespec="seconds")
        self.totals = [0.0] * entry.num_players
        self.finished: list[dict[str, Any]] = []
        self.hint_cache: dict[Any, Any] = {}
        self.hand = 0
        self._deal()

    # State

    def _deal(self) -> None:
        self.hand += 1
        self.state = self.entry.game.new_initial_state()
        self.events: list[Event] = []
        self.returns: list[float] | None = None

    @property
    def ply(self) -> int:
        return len(self.state.history())

    @property
    def humans(self) -> list[int]:
        return [i for i, s in enumerate(self.seats) if s.kind == "human"]

    def phase(self) -> str:
        if self.state.is_terminal():
            return "terminal"
        if self.state.is_chance_node():
            return "chance"
        return "human" if self.seats[self.state.current_player()].kind == "human" else "bot"

    def _check_ply(self, ply: Any) -> None:
        if not isinstance(ply, int) or isinstance(ply, bool):
            raise ValueError("ply must be an integer")
        if ply != self.ply:
            raise Conflict(f"the table has moved on (ply {self.ply}, request was for ply {ply})")

    # Moves

    def act(self, action: Any, ply: Any) -> None:
        """A human seat's move."""
        with self.lock:
            self._check_ply(ply)
            if self.phase() != "human":
                raise Conflict("it is not a human seat's turn")
            if not isinstance(action, int) or isinstance(action, bool):
                raise ValueError("action must be an integer")
            if action not in self.state.legal_actions():
                raise ValueError(f"action {action} is not legal here")
            coach = self._coach_probs(self.state)
            self._apply(action, coach_prob=coach.get(action) if coach is not None else None)

    def step(self, ply: Any) -> bool:
        """Advance one chance event or bot move; False if the bot is waiting for its profile."""
        with self.lock:
            self._check_ply(ply)
            phase = self.phase()
            if phase == "chance":
                outcomes = self.state.chance_outcomes()
                action = self._draw(dict(outcomes))
                self._apply(action)
                return True
            if phase != "bot":
                waiting_for = "a human move" if phase == "human" else "a new hand"
                raise Conflict(f"nothing to step: the table is waiting for {waiting_for}")
            decision = self.seats[self.state.current_player()].policy.decide(self.state)
            if decision is None:
                return False
            self._apply(self._draw(decision.probs), decision=decision)
            return True

    def next_hand(self, hand: Any) -> None:
        with self.lock:
            if hand != self.hand:
                raise Conflict(f"hand {self.hand} is in progress, not hand {hand}")
            if not self.state.is_terminal():
                raise Conflict("finish the current hand first")
            if len(self.finished) >= MAX_HANDS:
                raise Conflict(f"this table has played {MAX_HANDS} hands; export them and start a new table")
            self._deal()

    def _draw(self, probs: dict[int, float]) -> int:
        actions = sorted(probs)
        total = sum(probs[a] for a in actions)
        r = self.rng.random() * total
        for a in actions:
            r -= probs[a]
            if r < 0:
                return a
        return actions[-1]

    def _apply(self, action: int, decision: Decision | None = None, coach_prob: float | None = None) -> None:
        state, entry = self.state, self.entry
        observers = entry.observers(state, action)
        if state.is_chance_node():
            event = Event(
                ply=self.ply,
                kind="chance",
                player=None,
                action=action,
                text=entry.describe_chance(state, action),
                label=None,
                observers=observers,
                prob=dict(state.chance_outcomes())[action],
            )
        else:
            player = state.current_player()
            labels = entry.action_labels(state)
            event = Event(
                ply=self.ply,
                kind="move",
                player=player,
                action=action,
                text=f"{seat_name(player)}: {labels[action]}",
                label=labels[action],
                observers=observers,
                coach_prob=coach_prob,
            )
            if decision is not None:
                event.prob = decision.probs.get(action)
                event.probs = [(labels[a], decision.probs.get(a, 0.0)) for a in state.legal_actions()]
                event.note = decision.note
        state.apply_action(action)
        self.events.append(event)
        if state.is_terminal():
            self.returns = [float(r) for r in state.returns()]
            for i, r in enumerate(self.returns):
                self.totals[i] += r
            self.finished.append(self._hand_record())

    def _hand_record(self) -> dict[str, Any]:
        return {
            "hand": self.hand,
            "returns": self.returns,
            "history": list(self.state.history()),
            "events": [e.as_dict(visible=True, revealed=True) for e in self.events],
        }

    # Coach

    def _coach_probs(self, state: pyspiel.State) -> dict[int, float] | None:
        if not self.entry.has_infostates:
            return None
        profile = self.profiles.get(self.entry)
        if profile is None:
            return None
        return profile.table.get(state.information_state_string())

    def coach(self) -> dict[str, Any]:
        state = self.state
        labels = self.entry.action_labels(state)
        status = self.profiles.status(self.entry)
        out: dict[str, Any] = {"status": status["state"], "guarantee": status["guarantee"]}
        if status["state"] != "ready":
            return out
        probs = self._coach_probs(state)
        out["profile"] = status["profile"]
        if probs is None:
            out["missing"] = True
            return out
        out["actions"] = [
            {"action": a, "label": labels[a], "p": probs.get(a, 0.0)} for a in state.legal_actions()
        ]
        return out

    # Views

    def viewer(self) -> int | None:
        humans = self.humans
        if not humans:
            return None
        if self.phase() == "human":
            return self.state.current_player()
        for event in reversed(self.events):
            if event.kind == "move" and event.player in humans:
                return event.player
        return humans[0]

    def view(self, reveal: bool = False) -> dict[str, Any]:
        with self.lock:
            phase = self.phase()
            viewer = self.viewer()
            revealed = reveal or phase == "terminal" or viewer is None
            to_act = self.state.current_player() if phase in ("human", "bot") else None
            profile = self.profiles.status(self.entry) if self.entry.has_infostates else None

            waiting = None
            profile_ready = profile is not None and profile["state"] == "ready"
            if phase == "bot" and self.seats[to_act].kind == "cfr" and not profile_ready:
                waiting = {"seat": to_act, "reason": "profile"}

            decision = None
            if phase == "human":
                situation, plain = self.entry.situation(self.state)
                labels = self.entry.action_labels(self.state)
                decision = {
                    "player": to_act,
                    "situation": situation,
                    "plain": plain,
                    "actions": [{"action": a, "label": labels[a]} for a in self.state.legal_actions()],
                    "coach": self.coach() if self.entry.has_infostates else None,
                }

            n = len(self.finished)
            return {
                "id": self.id,
                "game": self.entry.info(),
                "seed": self.seed,
                "hand": self.hand,
                "ply": self.ply,
                "phase": phase,
                "to_act": to_act,
                "viewer": viewer,
                "revealed": revealed,
                "seats": [
                    {
                        **seat.as_dict(),
                        "index": i,
                        "seat": seat_name(i),
                        "total": self.totals[i],
                        "mean": self.totals[i] / n if n else None,
                        "payoff": self.returns[i] if self.returns else None,
                    }
                    for i, seat in enumerate(self.seats)
                ],
                "hands_played": n,
                "waiting": waiting,
                "decision": decision,
                "log": [e.as_dict(revealed or viewer in e.observers, revealed) for e in self.events],
                "returns": self.returns,
                "history": [
                    {"hand": h["hand"], "returns": h["returns"], "events": h["events"]}
                    for h in reversed(self.finished[-VIEW_HISTORY:])
                ],
                "profile": profile,
                "guarantee": guarantee_text(self.entry.num_players, self.entry.two_player_zero_sum),
            }

    def export(self) -> dict[str, Any]:
        info = self.entry.info()
        with self.lock:
            return {
                "format": "strategybench-gui-hands/1",
                "exported": datetime.now(UTC).isoformat(timespec="seconds"),
                "created": self.created,
                "game": {k: info[k] for k in ("ref", "key", "load_string", "title", "players", "unit")},
                "seats": [
                    {**seat.as_dict(), "seat": seat_name(i), "run_id": seat.run_id}
                    for i, seat in enumerate(self.seats)
                ],
                "seed": self.seed,
                "hands_played": len(self.finished),
                "totals": self.totals,
                "hands": self.finished,
            }
