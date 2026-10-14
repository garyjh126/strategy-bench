"""Game catalogue, game sizes and CFR profiles (planning, background solving, caching, cancelling)."""

import time

import pyspiel
import pytest
from sbgui.catalog import GameError, canonical_key, count_tree, estimate_decision_nodes
from sbgui.profiles import EQUILIBRIUM_ITERATIONS, MAX_ITERATIONS, ProfileManager, guarantee_text


def test_registered_games_use_their_gamespec(catalog):
    names = {e.ref for e in catalog.registered()}
    assert {"kuhn", "leduc", "liars_dice"} <= names
    kuhn = catalog.resolve("kuhn")
    assert kuhn.registered and kuhn.spec is not None and kuhn.two_player_zero_sum


def test_game_string_with_registered_parameters_maps_to_the_registered_game(catalog):
    # Same OpenSpiel game, written out: it gets the GameSpec text and the project's runs.
    entry = catalog.resolve("kuhn_poker(players=2)")
    assert entry.registered and entry.ref == "kuhn"
    assert entry.key == canonical_key(pyspiel.load_game("kuhn_poker"))


@pytest.mark.parametrize(
    "ref, players, nodes, infostates",
    [
        ("kuhn", 2, 24, [6, 6]),
        ("leduc", 2, 774, [144, 144]),
        ("liars_dice", 2, 576, [96, 96]),
        # Ganzfried (arXiv:2509.25618) counts 288 player decision nodes and 48 infostates.
        ("kuhn_poker(players=3)", 3, 288, [16, 16, 16]),
    ],
)
def test_exact_sizes(catalog, ref, players, nodes, infostates):
    entry = catalog.resolve(ref)
    assert entry.num_players == players
    assert entry.size.exact
    assert entry.size.decision_nodes == nodes
    assert entry.size.infostates == infostates


def test_random_walk_estimate_is_close_to_the_exact_count():
    game = pyspiel.load_game("kuhn_poker(players=3)")
    estimate = estimate_decision_nodes(game, rollouts=4000, time_budget=5.0)
    assert estimate == pytest.approx(count_tree(game).decision_nodes, rel=0.1)


def test_count_tree_gives_up_above_its_limit():
    assert count_tree(pyspiel.load_game("kuhn_poker(players=3)"), limit=100) is None


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "choose a game"),
        ("kuhn_poker; rm -rf /", "not a game string"),
        ("no_such_game", "could not load"),
        ("matrix_rps", "not turn-based"),
        ("kuhn_poker(players=9)", "between 1 and 8 players"),
    ],
)
def test_bad_game_strings_are_refused(catalog, text, message):
    with pytest.raises(GameError, match=message):
        catalog.resolve(text)


def test_only_the_dealt_player_observes_a_private_card(kuhn):
    state = kuhn.game.new_initial_state()
    assert kuhn.observers(state, 0) == [0]  # Player 1's card
    state.apply_action(0)
    assert kuhn.observers(state, 1) == [1]  # Player 2's card
    state.apply_action(1)
    assert kuhn.observers(state, 1) == [0, 1]  # a bet is public


def test_guarantee_text_is_honest_about_player_count():
    assert guarantee_text(2, True)["kind"] == "nash"
    three = guarantee_text(3, False)
    assert three["kind"] == "no-guarantee"
    assert "coarse correlated equilibrium" in three["text"]
    assert guarantee_text(2, False)["kind"] == "no-guarantee"


def test_plans(catalog, profiles):
    plan = profiles.plan(catalog.resolve("kuhn"))
    assert (plan.method, plan.iterations, plan.allowed) == ("equilibrium", EQUILIBRIUM_ITERATIONS, True)
    plan = profiles.plan(catalog.resolve("kuhn_poker(players=3)"))
    assert (plan.method, plan.iterations, plan.quick) == ("cfr", MAX_ITERATIONS, True)
    plan = profiles.plan(catalog.resolve("mancala"))
    assert not plan.allowed and "no information-state strings" in plan.reason
    plan = profiles.plan(catalog.resolve("leduc_poker(players=4)"))
    assert not plan.allowed and "too large" in plan.reason


def wait_for(manager, entry, state, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.status(entry)
        if status["state"] == state:
            return status
        assert status["state"] in ("running", "idle"), status
        time.sleep(0.2)
    raise AssertionError(f"profile never reached {state!r}")


def test_profile_is_solved_in_the_background_and_cached(tmp_path, kuhn3):
    first = ProfileManager(tmp_path / "gui_cache", tmp_path / "equilibria")
    try:
        assert first.status(kuhn3)["state"] == "idle"
        first.start(kuhn3)
        status = wait_for(first, kuhn3, "ready")
    finally:
        first.shutdown()
    profile = status["profile"]
    assert profile["infostates"] == 48
    assert profile["exploitability"] is None  # only defined for two players
    assert 0 <= profile["nash_conv"] < 0.01
    assert sum(profile["values"]) == pytest.approx(0.0, abs=1e-9)  # zero-sum

    # A new manager (a restarted server) reads the cached file instead of solving again.
    second = ProfileManager(tmp_path / "gui_cache", tmp_path / "equilibria")
    assert second.status(kuhn3)["state"] == "ready"
    assert len(second.get(kuhn3).table) == 48
    assert not second._jobs


def test_cancelling_stops_the_solver_process(catalog, profiles):
    leduc3 = catalog.resolve("leduc_poker(players=3)")  # minutes of work: not a quick plan
    assert not profiles.plan(leduc3).quick
    assert profiles.start(leduc3)["state"] == "running"
    job = profiles._jobs[leduc3.key]
    assert profiles.cancel(leduc3)["state"] == "idle"
    job.process.join(timeout=10)
    assert not job.process.is_alive()
