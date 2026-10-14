"""The JSON API, independent of HTTP so it can be tested directly.

Every public method takes plain values (a parsed JSON body or query parameters) and returns a
JSON-serialisable dict, or raises ``ApiError`` with an HTTP status.
"""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from sbgui import explorer, hints
from sbgui.catalog import ENUMERATE_LIMIT, SOLVE_LIMIT, Catalog, GameEntry, GameError
from sbgui.policies import PendingTablePolicy, RunPolicy, UniformPolicy
from sbgui.profiles import ProfileManager
from sbgui.runs import RunLibrary
from sbgui.session import SEAT_KINDS, Conflict, Seat, Session

#: Shown under the custom game box; each is a turn-based OpenSpiel game string.
EXAMPLES = [
    {"ref": "kuhn_poker(players=3)", "note": "3-player Kuhn: 48 infostates, solves in a second"},
    {"ref": "leduc_poker(players=3)", "note": "3-player Leduc: 25,800 infostates, CFR takes minutes"},
    {"ref": "liars_dice(numdice=1,dice_sides=6)", "note": "Liar's Dice with six-sided dice"},
    {"ref": "tic_tac_toe", "note": "perfect information, no chance"},
]
MAX_SESSIONS = 64


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _int(value: Any, name: str, default: int | None = None) -> int:
    if value is None or value == "":
        if default is None:
            raise ApiError(400, f"{name} is required")
        return default
    if isinstance(value, bool):
        raise ApiError(400, f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be an integer") from None


class App:
    def __init__(self, runs_dir: str | Path, cache_dir: str | Path | None = None) -> None:
        runs_dir = Path(runs_dir)
        self.catalog = Catalog()
        self.runs = RunLibrary(runs_dir)
        self.profiles = ProfileManager(
            cache_dir if cache_dir is not None else runs_dir / "gui_cache", runs_dir / "equilibria"
        )
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()

    def close(self) -> None:
        self.profiles.shutdown()

    # Games

    def entry(self, ref: Any) -> GameEntry:
        try:
            return self.catalog.resolve(ref)
        except GameError as e:
            raise ApiError(400, str(e)) from None

    def games(self) -> dict[str, Any]:
        registered = []
        for entry in self.catalog.registered():
            registered.append(entry.info())
        return {
            "registered": registered,
            "examples": EXAMPLES,
            "registry_error": self.catalog.registry_error,
            "limits": {"solve": SOLVE_LIMIT, "enumerate": ENUMERATE_LIMIT},
        }

    def inspect(self, body: dict[str, Any]) -> dict[str, Any]:
        entry = self.entry(body.get("game"))
        status = self.profiles.status(entry)
        if status["state"] == "idle" and status["plan"]["quick"]:
            status = self.profiles.start(entry)
        runs = self.runs.list(entry.key) if entry.spec is not None else []
        return {
            "game": entry.info(),
            "profile": status,
            "runs": [r.as_dict() for r in runs],
            "seat_kinds": SEAT_KINDS,
            "hints": entry.num_players == 2 and entry.has_infostates and entry.size.enumerable,
            "explorer": entry.has_infostates and entry.size.enumerable,
        }

    # Profiles

    def _start_profile(self, entry: GameEntry) -> dict[str, Any]:
        try:
            return self.profiles.start(entry)
        except RuntimeError as e:
            raise ApiError(409, str(e)) from None

    def profile(self, game: Any) -> dict[str, Any]:
        return self.profiles.status(self.entry(game))

    def profile_start(self, body: dict[str, Any]) -> dict[str, Any]:
        entry = self.entry(body.get("game"))
        status = self._start_profile(entry)
        if status["state"] == "refused":
            raise ApiError(400, f"no CFR profile for this game: {status['reason']}")
        return status

    def profile_cancel(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.profiles.cancel(self.entry(body.get("game")))

    # Sessions

    def create_session(self, body: dict[str, Any]) -> dict[str, Any]:
        entry = self.entry(body.get("game"))
        specs = body.get("seats")
        if not isinstance(specs, list) or len(specs) != entry.num_players:
            raise ApiError(400, f"seats must be a list with one entry per player ({entry.num_players})")
        seats = [self._seat(entry, i, spec) for i, spec in enumerate(specs)]
        if any(s.kind == "cfr" for s in seats):
            status = self._start_profile(entry)
            if status["state"] == "refused":
                raise ApiError(400, f"no CFR seat for this game: {status['reason']}")
        seed = _int(body.get("seed"), "seed", default=secrets.randbelow(2**31))
        session = Session(secrets.token_urlsafe(9), entry, seats, self.profiles, seed)
        with self._lock:
            self._sessions[session.id] = session
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
        return session.view(reveal=bool(body.get("reveal")))

    def _seat(self, entry: GameEntry, index: int, spec: Any) -> Seat:
        if not isinstance(spec, dict) or spec.get("kind") not in SEAT_KINDS:
            raise ApiError(400, f"seat {index + 1}: kind must be one of {', '.join(SEAT_KINDS)}")
        kind = spec["kind"]
        if kind == "human":
            return Seat("human", "Human", "Moves chosen on this screen")
        if kind == "uniform":
            return Seat("uniform", "Uniform random", "Every legal action equally likely", UniformPolicy())
        if kind == "cfr":
            if not entry.has_infostates:
                raise ApiError(400, f"seat {index + 1}: no CFR profile for games without information states")
            return Seat(
                "cfr",
                "CFR profile",
                "Samples the CFR average strategy",
                PendingTablePolicy(lambda: self.profiles.get(entry)),
            )
        if entry.spec is None:
            raise ApiError(400, f"seat {index + 1}: runs exist only for registered games")
        try:
            run = self.runs.get(spec.get("run"), entry.key)
            strategy = self.runs.strategy(run)
        except KeyError as e:
            raise ApiError(400, f"seat {index + 1}: {e.args[0]}") from None
        except (OSError, ValueError) as e:
            raise ApiError(400, f"seat {index + 1}: could not read the run's strategy: {e}") from None
        detail = f"{run.description} · N={run.n_samples} · {run.prompt_version} · {run.run_id}"
        if run.smoke_test:
            detail += " · smoke test"
        return Seat("run", run.display_name, detail, RunPolicy(strategy, entry.action_labels), run.run_id)

    def session(self, sid: Any) -> Session:
        with self._lock:
            session = self._sessions.get(sid) if isinstance(sid, str) else None
        if session is None:
            raise ApiError(404, "no such table (the server may have restarted)")
        return session

    def _run(self, fn, *args) -> None:
        try:
            fn(*args)
        except Conflict as e:
            raise ApiError(409, str(e)) from None
        except ValueError as e:
            raise ApiError(400, str(e)) from None

    def view(self, sid: Any, reveal: bool = False) -> dict[str, Any]:
        return self.session(sid).view(reveal)

    def act(self, sid: Any, body: dict[str, Any]) -> dict[str, Any]:
        session = self.session(sid)
        self._run(session.act, body.get("action"), body.get("ply"))
        return session.view(bool(body.get("reveal")))

    def step(self, sid: Any, body: dict[str, Any]) -> dict[str, Any]:
        session = self.session(sid)
        self._run(session.step, body.get("ply"))
        return session.view(bool(body.get("reveal")))

    def next_hand(self, sid: Any, body: dict[str, Any]) -> dict[str, Any]:
        session = self.session(sid)
        self._run(session.next_hand, body.get("hand"))
        return session.view(bool(body.get("reveal")))

    def export(self, sid: Any) -> dict[str, Any]:
        return self.session(sid).export()

    def hint(self, sid: Any, ply: Any) -> dict[str, Any]:
        session = self.session(sid)
        if _int(ply, "ply") != session.ply:
            raise ApiError(409, "the table has moved on")
        return hints.best_response_hint(session)

    # Explorer

    def explore(self, query: dict[str, Any]) -> dict[str, Any]:
        entry = self.entry(query.get("game"))
        if not entry.has_infostates:
            raise ApiError(400, "OpenSpiel gives no information states for this game")
        if not entry.size.enumerable:
            raise ApiError(
                400, f"too large to list every situation (the limit is {ENUMERATE_LIMIT:,} decision nodes)"
            )
        run = strategy = None
        run_id = query.get("run") or None
        if run_id is not None:
            try:
                run = self.runs.get(run_id, entry.key)
                strategy = self.runs.strategy(run)
            except KeyError as e:
                raise ApiError(400, e.args[0]) from None
        profile = self.profiles.get(entry)
        rows = explorer.build_rows(entry, run, strategy, profile)
        player = query.get("player")
        result = explorer.page(
            rows,
            player=None if player in (None, "", "all") else _int(player, "player"),
            query=str(query.get("q") or "")[:100],
            hide_forced=str(query.get("forced", "hide")) != "show",
            offset=_int(query.get("offset"), "offset", 0),
            limit=_int(query.get("limit"), "limit", 50),
        )
        return {
            **result,
            "game": entry.info(),
            "run": run.as_dict() if run else None,
            "profile": self.profiles.status(entry),
            "weighting": "run" if run else ("cfr" if profile else "uniform"),
        }
