"""Discover result directories and choose which ones the site shows.

Rules (also stated in the methodology):

* A candidate is a directory under the results root with ``manifest.json`` and ``metrics.json``
  (a direct-mode run).
* Runs named with ``exclude`` are left out.
* Sampled runs with fewer than ``min_samples`` samples per infostate are smoke tests, not
  results, and are left out.
* Runs that measure the same thing (game, provider, model, parameters, prompt version and
  estimation kind) are deduplicated: the most recently created one is shown.

Every run left out is reported with its reason.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from strategybench.games import get_game_spec

#: Default display names for the scripted reference subjects (``mock-<agent>`` model ids), in
#: poker terms; a game can rename them with ``GameSpec.reference_names``.
REFERENCE_NAMES = {
    "cfr": "Equilibrium (CFR+)",
    "cfr-noisy": "80% equilibrium, 20% uniform",
    "uniform": "Uniform random",
    "first-action": "Always check / fold",
    "last-action": "Always the most aggressive action",
}


@dataclass
class RunRecord:
    run_id: str
    path: Path
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    play: dict[str, Any] | None = None
    files: list[str] = field(default_factory=list)

    @property
    def game(self) -> str:
        return self.metrics["game"]

    @property
    def provider(self) -> str:
        return self.metrics["provider"]

    @property
    def model_id(self) -> str:
        return self.metrics["model_id"]

    @property
    def params(self) -> dict[str, Any]:
        return self.metrics.get("params") or {}

    @property
    def prompt_version(self) -> str:
        return self.metrics["prompt_version"]

    @property
    def subject_kind(self) -> str:
        return self.metrics["subject_kind"]

    @property
    def n_samples(self) -> int | None:
        return self.metrics.get("n_samples")

    @property
    def created(self) -> str:
        return self.manifest.get("created", "")

    @property
    def is_reference(self) -> bool:
        return self.provider == "mock"

    @property
    def identity(self) -> tuple[str, ...]:
        return (
            self.game,
            self.provider,
            self.model_id,
            json.dumps(self.params, sort_keys=True),
            self.prompt_version,
            self.subject_kind,
        )

    @property
    def display_name(self) -> str:
        if self.is_reference:
            agent = self.model_id.removeprefix("mock-")
            names = {**REFERENCE_NAMES, **get_game_spec(self.game).reference_names}
            return names.get(agent, agent)
        return self.model_id

    @property
    def description(self) -> str:
        """Secondary line under the subject's name."""
        how = "exact probabilities" if self.subject_kind == "distribution" else "sampled"
        if not self.is_reference:
            return f"{self.provider} · {how}"
        parts = ["scripted reference", how]
        p = self.params
        if p.get("garbage_rate"):
            parts.append(f"{p['garbage_rate']:.0%} malformed replies")
        if p.get("illegal_rate"):
            parts.append(f"{p['illegal_rate']:.0%} illegal replies")
        if p.get("format_noise"):
            parts.append("format noise")
        return " · ".join(parts)


def load_run(path: Path) -> RunRecord:
    manifest = json.loads((path / "manifest.json").read_text())
    metrics = json.loads((path / "metrics.json").read_text())
    play_path = path / "play.json"
    play = json.loads(play_path.read_text()) if play_path.exists() else None
    files = sorted(p.name for p in path.iterdir() if p.is_file())
    return RunRecord(path.name, path, manifest, metrics, play, files)


def discover(runs_dir: str | Path) -> tuple[list[RunRecord], list[tuple[str, str]]]:
    """Every direct-mode run under ``runs_dir``, plus directories that could not be read."""
    records, unreadable = [], []
    for path in sorted(Path(runs_dir).iterdir()):
        if not (path / "metrics.json").is_file() or not (path / "manifest.json").is_file():
            continue
        try:
            records.append(load_run(path))
        except (OSError, ValueError, KeyError) as e:
            unreadable.append((path.name, f"unreadable: {e}"))
    return records, unreadable


def select(
    records: list[RunRecord], min_samples: int = 30, exclude: tuple[str, ...] | list[str] = ()
) -> tuple[list[RunRecord], list[tuple[str, str]]]:
    """Apply the selection rules; return (shown runs, [(run id, reason left out)])."""
    skipped: list[tuple[str, str]] = []
    kept: list[RunRecord] = []
    for r in records:
        if r.run_id in exclude:
            skipped.append((r.run_id, "excluded by request"))
        elif r.subject_kind == "sampled" and (r.n_samples or 0) < min_samples:
            skipped.append((r.run_id, f"smoke test: N={r.n_samples} < {min_samples} samples per infostate"))
        else:
            kept.append(r)

    latest: dict[tuple[str, ...], RunRecord] = {}
    for r in sorted(kept, key=lambda r: (r.created, r.run_id)):
        if r.identity in latest:
            skipped.append((latest[r.identity].run_id, f"superseded by {r.run_id}"))
        latest[r.identity] = r
    return sorted(latest.values(), key=lambda r: r.run_id), skipped
