"""CFR profiles for the coach panel and CFR seats, computed in background processes.

* Registered two-player zero-sum games use the project's reference equilibrium,
  ``solve_equilibrium(load_string, 2000, runs/equilibria)`` (OpenSpiel C++ CFR+, cached on disk).
* Any other game gets an OpenSpiel C++ CFR average policy (CFR+ for two-player zero-sum games,
  vanilla CFR otherwise) with an iteration budget sized to the game.

OpenSpiel's C++ solver holds the GIL for a whole iteration (about 3.7 s in three-player Leduc),
so solving runs in a separate process and reports progress over a queue; the server only reads
the queue. Results are cached as JSON under ``runs/gui_cache/profiles/`` and reused.

Every profile records how far it is from a Nash equilibrium: NashConv (the total gain available
to players deviating one at a time, 0 at a Nash equilibrium) and, for two-player games, the
exploitability NashConv / 2 used throughout StrategyBench.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import multiprocessing as mp
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyspiel

from sbgui.catalog import SOLVE_LIMIT, GameEntry

#: Iterations for registered two-player zero-sum games (the project's equilibrium reference).
EQUILIBRIUM_ITERATIONS = 2000
#: Node-iterations of work for other games: iterations = budget / decision nodes, clamped.
NODE_ITERATION_BUDGET = 1e8
MIN_ITERATIONS, MAX_ITERATIONS = 100, 2000
#: Rough C++ CFR cost per decision node per iteration on a laptop (3-player Leduc: ~4.7 us).
SECONDS_PER_NODE_ITERATION = 4.5e-6
#: A job expected to finish within this many seconds starts as soon as its game is chosen.
QUICK_SECONDS = 15.0
CACHE_VERSION = 1
METHOD_NAMES = {"equilibrium": "CFR+", "cfr+": "CFR+", "cfr": "CFR"}


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", text)[:80]


def equilibrium_cache_path(load_string: str, iterations: int, cache_dir: Path) -> Path:
    """Where ``solve_equilibrium`` caches its result.

    Mirrors the naming in ``strategybench.analysis.metrics.solve_equilibrium``. Only used to
    decide whether loading is quick; if the naming changes, the app just asks before loading.
    """
    version = importlib.metadata.version("open_spiel")
    tag = hashlib.sha256(f"{load_string}|cfr+|{iterations}|{version}".encode()).hexdigest()[:12]
    return cache_dir / f"{_slug(load_string)}_{tag}.npz"


@dataclass
class Plan:
    method: str  # "equilibrium", "cfr+" or "cfr"
    iterations: int
    allowed: bool
    reason: str | None
    est_seconds: float | None
    cache_path: Path
    #: The equilibrium is already in ``runs/equilibria`` (loading takes seconds).
    equilibrium_cached: bool = False

    @property
    def quick(self) -> bool:
        return self.allowed and (
            self.equilibrium_cached or self.cache_path.exists() or (self.est_seconds or 0) <= QUICK_SECONDS
        )

    @property
    def method_name(self) -> str:
        return METHOD_NAMES[self.method]

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "method_name": self.method_name,
            "iterations": self.iterations,
            "allowed": self.allowed,
            "reason": self.reason,
            "est_seconds": self.est_seconds,
            "quick": self.quick,
            "cached": self.cache_path.exists(),
            "equilibrium_cached": self.equilibrium_cached,
        }


@dataclass
class Profile:
    table: dict[str, dict[int, float]]
    meta: dict[str, Any]


def guarantee_text(players: int, two_player_zero_sum: bool) -> dict[str, str]:
    """How to read a CFR profile, stated honestly for the game's player count and payoffs."""
    if two_player_zero_sum:
        return {
            "kind": "nash",
            "title": "Approximate Nash equilibrium",
            "text": (
                "In two-player zero-sum games the CFR average strategy converges to a Nash "
                "equilibrium; the exploitability shown is how far this one still is."
            ),
        }
    who = f"{players} players" if players >= 3 else "a general-sum game"
    return {
        "kind": "no-guarantee",
        "title": "No equilibrium guarantee",
        "text": (
            f"With {who}, CFR has no Nash-equilibrium guarantee. Its no-regret property only "
            "means the empirical distribution of joint play converges to a coarse correlated "
            "equilibrium; the average strategy shown here, played independently by each seat, is "
            "not guaranteed to be an equilibrium of any kind. NashConv measures how much players "
            "could gain by deviating one at a time."
        ),
    }


def _table_from_tabular(policy) -> dict[str, list[list[float]]]:
    """``{infostate: [[action, prob], ...]}`` from an OpenSpiel Python TabularPolicy."""
    out = {}
    for key, row in policy.state_lookup.items():
        legal = policy.legal_actions_mask[row]
        probs = policy.action_probability_array[row]
        out[key] = [[a, float(probs[a])] for a in range(len(legal)) if legal[a]]
    return out


def _solve(job: dict[str, Any], progress) -> None:
    """Child process: compute a profile and write it to ``job['cache_path']``."""
    try:
        start = time.monotonic()
        game = pyspiel.load_game(job["load_string"])
        meta: dict[str, Any] = {}
        if job["method"] == "equilibrium":
            from strategybench.analysis.metrics import solve_equilibrium

            progress.put(("phase", "loading" if job["equilibrium_cached"] else "solving"))
            eq = solve_equilibrium(job["load_string"], job["iterations"], job["equilibria_dir"])
            table = _table_from_tabular(eq.policy)
            meta.update(
                exploitability=eq.exploitability,
                nash_conv=2 * eq.exploitability,
                values=eq.values,
                source="strategybench solve_equilibrium (OpenSpiel C++ CFR+), cached in runs/equilibria",
            )
        else:
            solver = pyspiel.CFRPlusSolver(game) if job["method"] == "cfr+" else pyspiel.CFRSolver(game)
            total, last = job["iterations"], 0.0
            progress.put(("progress", 0, total))
            for i in range(1, total + 1):
                solver.evaluate_and_update_policy()
                now = time.monotonic()
                if i == total or now - last >= 0.25:
                    progress.put(("progress", i, total))
                    last = now
            progress.put(("phase", "measuring"))
            average = solver.tabular_average_policy()
            table = {k: [[a, p] for a, p in v] for k, v in average.policy_table().items()}
            nash_conv = float(pyspiel.nash_conv(game, average))
            values = pyspiel.expected_returns(game.new_initial_state(), average, -1, True)
            meta.update(
                nash_conv=nash_conv,
                exploitability=nash_conv / 2 if game.num_players() == 2 else None,
                values=[float(v) for v in values],
                source=f"OpenSpiel C++ {'CFR+' if job['method'] == 'cfr+' else 'CFR'} average policy",
            )
        meta.update(
            version=CACHE_VERSION,
            game=job["load_string"],
            key=job["key"],
            method=job["method"],
            iterations=job["iterations"],
            seconds=round(time.monotonic() - start, 2),
            players=game.num_players(),
            open_spiel=importlib.metadata.version("open_spiel"),
            created=datetime.now(UTC).isoformat(timespec="seconds"),
            infostates=len(table),
        )
        path = Path(job["cache_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"meta": meta, "policy": table}))
        os.replace(tmp, path)
        progress.put(("done", str(path)))
    except BaseException as e:  # report everything, including KeyboardInterrupt, to the parent
        progress.put(("error", f"{type(e).__name__}: {e}"))


@dataclass
class Job:
    process: Any
    queue: Any
    total: int
    #: Expected to take seconds; does not count towards the limit on concurrent jobs.
    quick: bool = False
    started: float = field(default_factory=time.monotonic)
    state: str = "running"  # running, done, error, cancelled
    iteration: int = 0
    phase: str = "starting"
    error: str | None = None
    finished: float | None = None

    def as_dict(self) -> dict[str, Any]:
        elapsed = (self.finished or time.monotonic()) - self.started
        return {
            "state": self.state,
            "iteration": self.iteration,
            "total": self.total,
            "fraction": self.iteration / self.total if self.total else None,
            "phase": self.phase,
            "elapsed": round(elapsed, 1),
            "error": self.error,
        }


def load_profile(path: Path) -> Profile:
    data = json.loads(path.read_text())
    table = {k: {int(a): float(p) for a, p in v} for k, v in data["policy"].items()}
    return Profile(table, data["meta"])


class ProfileManager:
    def __init__(self, cache_dir: str | Path, equilibria_dir: str | Path, max_running: int = 2) -> None:
        self.cache_dir = Path(cache_dir) / "profiles"
        self.equilibria_dir = Path(equilibria_dir)
        self.max_running = max_running
        self._ctx = mp.get_context("spawn")
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._profiles: dict[str, Profile] = {}
        self._load_errors: dict[str, str] = {}

    # Planning

    def plan(self, entry: GameEntry) -> Plan:
        size = entry.size
        if entry.registered and entry.two_player_zero_sum:
            method, iterations = "equilibrium", EQUILIBRIUM_ITERATIONS
        else:
            method = "cfr+" if entry.two_player_zero_sum else "cfr"
            budget = NODE_ITERATION_BUDGET / max(size.decision_nodes, 1.0)
            iterations = int(min(MAX_ITERATIONS, max(MIN_ITERATIONS, budget)))
        version = importlib.metadata.version("open_spiel")
        tag = hashlib.sha256(
            f"{entry.key}|{method}|{iterations}|{version}|v{CACHE_VERSION}".encode()
        ).hexdigest()[:12]
        cache_path = self.cache_dir / f"{_slug(entry.key)}_{tag}.json"

        reason = None
        if not entry.has_infostates:
            reason = "OpenSpiel gives no information-state strings for this game, so CFR cannot run"
        elif not size.solvable:
            n = size.decision_nodes
            nodes = "more than 10 billion" if n == float("inf") else f"about {n:,.0f}"
            reason = f"too large to solve here ({nodes} decision nodes; the limit is {SOLVE_LIMIT:,})"
        est = None if reason else iterations * size.decision_nodes * SECONDS_PER_NODE_ITERATION
        eq_cached = (
            method == "equilibrium"
            and equilibrium_cache_path(entry.load_string, iterations, self.equilibria_dir).exists()
        )
        return Plan(method, iterations, reason is None, reason, est, cache_path, eq_cached)

    # Results

    def get(self, entry: GameEntry) -> Profile | None:
        """The finished profile for ``entry`` if it is in memory or in the cache, else None."""
        with self._lock:
            profile = self._profiles.get(entry.key)
        if profile is not None:
            return profile
        plan = self.plan(entry)
        if not plan.allowed or not plan.cache_path.exists():
            return None
        try:
            profile = load_profile(plan.cache_path)
        except (OSError, ValueError, KeyError) as e:
            with self._lock:
                self._load_errors[entry.key] = f"cached profile unreadable: {e}"
            return None
        with self._lock:
            return self._profiles.setdefault(entry.key, profile)

    def status(self, entry: GameEntry) -> dict[str, Any]:
        plan = self.plan(entry)
        out: dict[str, Any] = {
            "plan": plan.as_dict(),
            "guarantee": guarantee_text(entry.num_players, entry.two_player_zero_sum),
        }
        if not plan.allowed:
            return {**out, "state": "refused", "reason": plan.reason}
        profile = self.get(entry)
        if profile is not None:
            return {**out, "state": "ready", "profile": self.describe(entry, profile)}
        with self._lock:
            job = self._jobs.get(entry.key)
            load_error = self._load_errors.get(entry.key)
        if job is not None and job.state in ("running", "error"):
            return {**out, "state": job.state, "job": job.as_dict()}
        if load_error:
            return {**out, "state": "error", "job": {"error": load_error}}
        return {**out, "state": "idle"}

    def describe(self, entry: GameEntry, profile: Profile) -> dict[str, Any]:
        meta = profile.meta
        unit = entry.unit_size or 1.0
        exploit = meta.get("exploitability")
        return {
            "method": meta.get("method"),
            "method_name": METHOD_NAMES.get(meta.get("method"), "CFR"),
            "iterations": meta.get("iterations"),
            "seconds": meta.get("seconds"),
            "source": meta.get("source"),
            "created": meta.get("created"),
            "infostates": meta.get("infostates"),
            "nash_conv": meta.get("nash_conv"),
            "exploitability": exploit,
            "exploitability_norm": exploit / unit if exploit is not None else None,
            "values": meta.get("values"),
            "unit": entry.unit,
            "cache_file": self.plan(entry).cache_path.name,
        }

    # Jobs

    def start(self, entry: GameEntry) -> dict[str, Any]:
        plan = self.plan(entry)
        if not plan.allowed or self.get(entry) is not None:
            return self.status(entry)
        with self._lock:
            job = self._jobs.get(entry.key)
            if job is None or job.state != "running":
                running = sum(1 for j in self._jobs.values() if j.state == "running" and not j.quick)
                if not plan.quick and running >= self.max_running:
                    raise RuntimeError(
                        f"{running} profiles are already being computed; wait for one to finish or cancel it"
                    )
                payload = {
                    "load_string": entry.load_string,
                    "key": entry.key,
                    "method": plan.method,
                    "iterations": plan.iterations,
                    "cache_path": str(plan.cache_path),
                    "equilibria_dir": str(self.equilibria_dir),
                    "equilibrium_cached": plan.equilibrium_cached,
                }
                q = self._ctx.Queue()
                process = self._ctx.Process(target=_solve, args=(payload, q), daemon=True)
                process.start()
                job = self._jobs[entry.key] = Job(process, q, plan.iterations, quick=plan.quick)
                self._load_errors.pop(entry.key, None)
                threading.Thread(target=self._watch, args=(entry, job), daemon=True).start()
        return self.status(entry)

    def _watch(self, entry: GameEntry, job: Job) -> None:
        while True:
            try:
                message = job.queue.get(timeout=0.5)
            except queue.Empty:
                if job.process.is_alive():
                    continue
                if job.state == "running":
                    job.state = "error"
                    job.error = f"solver process stopped (exit code {job.process.exitcode})"
                    job.finished = time.monotonic()
                break
            kind = message[0]
            if kind == "progress":
                job.iteration, job.total = message[1], message[2]
                job.phase = "iterating"
            elif kind == "phase":
                job.phase = message[1]
            elif kind == "done":
                try:
                    profile = load_profile(Path(message[1]))
                    with self._lock:
                        self._profiles[entry.key] = profile
                    job.state = "done"
                except (OSError, ValueError, KeyError) as e:
                    job.state, job.error = "error", f"could not read the solved profile: {e}"
                job.finished = time.monotonic()
                break
            elif kind == "error":
                job.state, job.error = "error", message[1]
                job.finished = time.monotonic()
                break
        job.process.join(timeout=5)

    def cancel(self, entry: GameEntry) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(entry.key)
        if job is not None and job.state == "running":
            job.state = "cancelled"
            job.finished = time.monotonic()
            job.process.terminate()
            with self._lock:
                self._jobs.pop(entry.key, None)
        return self.status(entry)

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.process.is_alive():
                job.process.terminate()
                job.process.join(timeout=5)
