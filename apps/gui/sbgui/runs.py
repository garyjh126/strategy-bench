"""Read measured strategies from run directories (``runs/<id>/strategy.json``). Read-only.

A run can sit in a seat when its OpenSpiel game is the session's game. Runs are listed from
the top level of the results directory, like the static site does.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import pyspiel

from sbgui.catalog import canonical_key
from strategybench.report.runs import load_run

#: Fewer samples per infostate than this is a smoke test, not a result (the site's rule).
SMOKE_TEST_SAMPLES = 30
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


@dataclass(frozen=True)
class StrategyRecord:
    player: int
    key: str
    situation: str
    support: int
    filled: bool
    estimated: dict[str, float]
    equilibrium: dict[str, float]


@dataclass
class RunStrategy:
    records: dict[tuple[int, str], StrategyRecord]

    def lookup(self, player: int, key: str) -> StrategyRecord | None:
        return self.records.get((player, key))


@dataclass
class RunInfo:
    run_id: str
    path: Path
    #: OpenSpiel load string the run was measured on.
    openspiel_game: str
    game_name: str
    display_name: str
    description: str
    n_samples: int | None
    subject_kind: str
    prompt_version: str
    created: str

    @property
    def smoke_test(self) -> bool:
        return self.subject_kind == "sampled" and (self.n_samples or 0) < SMOKE_TEST_SAMPLES

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.run_id,
            "name": self.display_name,
            "description": self.description,
            "game": self.game_name,
            "n_samples": self.n_samples,
            "subject_kind": self.subject_kind,
            "prompt_version": self.prompt_version,
            "created": self.created,
            "smoke_test": self.smoke_test,
        }


def read_strategy(path: Path) -> RunStrategy:
    rows = json.loads((path / "strategy.json").read_text())
    if not isinstance(rows, list):
        raise ValueError("strategy.json is not a list of infostates")
    records = {}
    for row in rows:
        record = StrategyRecord(
            player=int(row["player"]),
            key=str(row["infostate"]),
            situation=str(row.get("situation", "")),
            support=int(row.get("support", 0)),
            filled=bool(row.get("filled", False)),
            estimated={str(k): float(v) for k, v in row["estimated"].items()},
            equilibrium={str(k): float(v) for k, v in (row.get("equilibrium") or {}).items()},
        )
        records[(record.player, record.key)] = record
    return RunStrategy(records)


class RunLibrary:
    """Lists runs and loads their strategies on demand (cached; files are never written)."""

    def __init__(self, runs_dir: str | Path) -> None:
        self.runs_dir = Path(runs_dir)
        self._lock = threading.Lock()
        self._strategies: dict[str, RunStrategy] = {}
        self._keys: dict[str, str | None] = {}

    def _game_key(self, load_string: str) -> str | None:
        with self._lock:
            if load_string in self._keys:
                return self._keys[load_string]
        try:
            key = canonical_key(pyspiel.load_game(load_string))
        except pyspiel.SpielError:
            key = None
        with self._lock:
            self._keys[load_string] = key
        return key

    def list(self, game_key: str | None = None) -> list[RunInfo]:
        """Runs with a strategy, newest first; only those measured on ``game_key`` if given."""
        if not self.runs_dir.is_dir():
            return []
        out = []
        for path in self.runs_dir.iterdir():
            if not _RUN_ID.match(path.name) or not (path / "strategy.json").is_file():
                continue
            try:
                record = load_run(path)
                load_string = record.manifest["openspiel_game"]
            except (OSError, ValueError, KeyError):
                continue
            if game_key is not None and self._game_key(load_string) != game_key:
                continue
            out.append(
                RunInfo(
                    run_id=record.run_id,
                    path=path,
                    openspiel_game=load_string,
                    game_name=record.game,
                    display_name=record.display_name,
                    description=record.description,
                    n_samples=record.n_samples,
                    subject_kind=record.subject_kind,
                    prompt_version=record.prompt_version,
                    created=record.created,
                )
            )
        return sorted(out, key=lambda r: (r.created, r.run_id), reverse=True)

    def get(self, run_id: str, game_key: str) -> RunInfo:
        """The run named ``run_id`` if it exists and was measured on ``game_key``."""
        if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
            raise KeyError("not a run id")
        for run in self.list(game_key):
            if run.run_id == run_id:
                return run
        raise KeyError(f"no run {run_id!r} for this game")

    def strategy(self, run: RunInfo) -> RunStrategy:
        with self._lock:
            cached = self._strategies.get(run.run_id)
        if cached is None:
            cached = read_strategy(run.path)
            with self._lock:
                self._strategies[run.run_id] = cached
        return cached
