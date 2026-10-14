"""Strategy explorer: reach weighting, run against CFR comparison, fallback notes, filtering and paging."""

import pytest
from sbgui import explorer
from sbgui.profiles import Profile
from sbgui.runs import RunLibrary

from strategybench.estimation.infostates import enumerate_infostates


@pytest.fixture(autouse=True)
def fresh_cache():
    explorer._cache.clear()
    yield
    explorer._cache.clear()


def uniform_profile(entry):
    table = {
        i.key: {a: 1 / len(i.legal_actions) for a in i.legal_actions}
        for i in enumerate_infostates(entry.game)
    }
    return Profile(table, {})


def by_short(rows):
    return {r["short"]: r for r in rows}


def test_rows_cover_every_infostate_sorted_by_reach(kuhn):
    rows = explorer.build_rows(kuhn, None, None, None)
    assert len(rows) == 12
    reach = [r["reach"] for r in rows]
    assert reach == sorted(reach, reverse=True)
    # Uniform play: each first decision has probability 1/3; Player 2 holding a given card after
    # a check, 1/3 * 1/2; Player 1 facing check-bet with a given card, 1/3 * 1/2 * 1/2.
    rows = by_short(rows)
    assert rows["Jack · first to act"]["reach"] == pytest.approx(1 / 3)
    assert rows["King · Player 1 checked"]["reach"] == pytest.approx(1 / 6)
    assert rows["Queen · Player 1 checked, Player 2 bet"]["reach"] == pytest.approx(1 / 12)
    assert sum(r["reach"] for r in rows.values() if r["player"] == 0 and "first" in r["short"]) == 1


def test_run_rows_show_the_measured_strategy_next_to_the_profile(kuhn, runs_dir):
    library = RunLibrary(runs_dir)
    (run,) = library.list(kuhn.key)
    rows = by_short(explorer.build_rows(kuhn, run, library.strategy(run), uniform_profile(kuhn)))
    queen = rows["Queen · first to act"]
    assert queen["run"] == {"CHECK": 1.0, "BET": 0.0}
    assert queen["cfr"] == {"CHECK": 0.5, "BET": 0.5}
    assert queen["distance"] == pytest.approx(0.5)
    assert queen["support"] == 50 and queen["note"] is None
    jack = rows["Jack · first to act"]
    assert jack["run"] == {"CHECK": 0.5, "BET": 0.5} and "no valid samples" in jack["note"]
    missing = [r for r in rows.values() if r["note"] and "not in the run" in r["note"]]
    assert len(missing) == 1 and missing[0]["support"] == 0


def test_reach_follows_the_run_when_there_is_one(kuhn, runs_dir):
    # The run never bets except with the Jack (filled, so uniform there): Player 2 faces a bet
    # only when Player 1 holds the Jack and bets, so Player 2's Jack never faces one.
    library = RunLibrary(runs_dir)
    (run,) = library.list(kuhn.key)
    rows = by_short(explorer.build_rows(kuhn, run, library.strategy(run), None))
    assert rows["Queen · Player 1 bet"]["reach"] == pytest.approx(1 / 6 * 1 / 2)
    assert rows["Jack · Player 1 bet"]["reach"] == 0


def test_filtering_and_paging(kuhn, catalog):
    rows = explorer.build_rows(kuhn, None, None, None)
    assert explorer.page(rows, player=1)["matched"] == 6
    kings = explorer.page(rows, query="  KING ")
    assert kings["matched"] == 4 and all("King" in r["short"] for r in kings["rows"])
    first = explorer.page(rows, offset=-5, limit=0)
    assert first["offset"] == 0 and len(first["rows"]) == 1
    assert len(explorer.page(rows, limit=10_000)["rows"]) == 12

    liars = catalog.resolve("liars_dice")
    rows = explorer.build_rows(liars, None, None, None)
    assert explorer.page(rows, hide_forced=False)["matched"] == 192
    assert explorer.page(rows, hide_forced=True)["matched"] == 96  # LIAR is the only move after 2x3

    leduc = explorer.build_rows(catalog.resolve("leduc"), None, None, None)
    assert len(leduc) == 288
    assert len(explorer.page(leduc, hide_forced=False, limit=500)["rows"]) == explorer.MAX_PAGE
