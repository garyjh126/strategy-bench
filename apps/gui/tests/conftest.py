"""Shared fixtures for the GUI tests (run: uv run pytest apps/gui/tests).

Everything is written under pytest's tmp_path: the tests never read or write the real runs/.
"""

import json
import sys
from pathlib import Path

import pytest

GUI = Path(__file__).resolve().parents[1]
if str(GUI) not in sys.path:
    sys.path.insert(0, str(GUI))

from sbgui.catalog import Catalog  # noqa: E402
from sbgui.profiles import ProfileManager  # noqa: E402

from strategybench.estimation.infostates import enumerate_infostates  # noqa: E402

RUN_ID = "20261014T000000Z_kuhn_test-first-action_text"


@pytest.fixture(scope="session")
def catalog():
    return Catalog()


@pytest.fixture(scope="session")
def kuhn(catalog):
    return catalog.resolve("kuhn")


@pytest.fixture(scope="session")
def kuhn3(catalog):
    return catalog.resolve("kuhn_poker(players=3)")


@pytest.fixture
def profiles(tmp_path):
    manager = ProfileManager(tmp_path / "gui_cache", tmp_path / "equilibria")
    yield manager
    manager.shutdown()


@pytest.fixture
def runs_dir(tmp_path, kuhn):
    """A results directory holding one Kuhn run that always plays the first legal action.

    The first infostate (Player 1 holding the Jack) is marked as filled (no valid samples) and
    the last one is left out of strategy.json, so both fallbacks can be checked.
    """
    infos = enumerate_infostates(kuhn.game)
    rows = []
    for i, info in enumerate(infos[:-1]):
        labels = kuhn.action_labels(info.state)
        first = info.legal_actions[0]
        rows.append(
            {
                "infostate": info.key,
                "player": info.player,
                "situation": kuhn.situation(info.state)[0],
                "support": 0 if i == 0 else 50,
                "filled": i == 0,
                "estimated": {labels[a]: float(a == first) for a in info.legal_actions},
                "equilibrium": {},
            }
        )
    run = tmp_path / "runs" / RUN_ID
    run.mkdir(parents=True)
    (run / "strategy.json").write_text(json.dumps(rows))
    (run / "manifest.json").write_text(
        json.dumps({"openspiel_game": "kuhn_poker", "created": "2026-10-14T00:00:00+00:00"})
    )
    (run / "metrics.json").write_text(
        json.dumps(
            {
                "game": "kuhn",
                "provider": "test",
                "model_id": "test-first-action",
                "prompt_version": "kuhn-v1",
                "subject_kind": "sampled",
                "n_samples": 50,
                "params": {},
            }
        )
    )
    return tmp_path / "runs"


@pytest.fixture
def run_id(runs_dir):
    """The id of the run in ``runs_dir``."""
    return RUN_ID
