"""scripts/run_benchmark.py end to end: an aborted run and its resume keep separate results."""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "run_benchmark.py"


@pytest.fixture
def script(monkeypatch):
    spec = importlib.util.spec_from_file_location("run_benchmark_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FrozenClock:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(module, "datetime", FrozenClock)
    return module


def _run(module, monkeypatch, tmp_path, *extra):
    argv = ["run_benchmark.py", "--agent", "uniform", "--samples", "2", "--bootstrap", "0"]
    argv += ["--cache", str(tmp_path / "cache.sqlite"), "--out", str(tmp_path / "runs")]
    argv += ["--eq-cache", str(tmp_path / "equilibria"), *extra]
    monkeypatch.setattr(sys, "argv", argv)
    return module.main()


def test_a_resume_in_the_same_second_does_not_share_the_aborted_runs_directory(script, monkeypatch, tmp_path):
    assert _run(script, monkeypatch, tmp_path, "--max-calls", "5") == 2  # aborted by the cap
    assert _run(script, monkeypatch, tmp_path) == 0  # resumed from the cache, same timestamp
    dirs = sorted((tmp_path / "runs").iterdir())
    assert len(dirs) == 2
    resumed = next(d for d in dirs if (d / "metrics.json").exists())
    lines = [json.loads(line) for line in (resumed / "calls.jsonl").read_text().splitlines()]
    assert len(lines) == 12 * 2  # one line per attempt of this run only
    assert sum(line["from_cache"] for line in lines) == 5
