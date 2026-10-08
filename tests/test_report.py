"""Reporting: run selection, derived files, templated explanations, traceable numbers, site build."""

import json
import shutil
from pathlib import Path

import pytest

from strategybench.adapters.mock import MockDistributionClient, MockTextClient, policy_lookup
from strategybench.analysis.metrics import solve_equilibrium
from strategybench.baselines.scripted import first_action_policy, mix_policies, uniform_policy
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.report.derive import derive
from strategybench.report.explain import responder_sentence, subject_sentence
from strategybench.report.numbers import Source, pointer, render, resolve
from strategybench.report.runs import discover, select
from strategybench.report.site import SiteError, build_site
from strategybench.report.verify import verify_site
from strategybench.runner import RunConfig, run_direct, run_play

SPEC = get_game_spec("kuhn")
TEMPLATE = DEFAULT_TEMPLATES["kuhn"]
GAME = SPEC.load()
METHODOLOGY = Path(__file__).parents[1] / "docs" / "methodology.md"


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium("kuhn_poker", 2000)


def _text(name, policy, **kw):
    return MockTextClient(name, policy_lookup(SPEC, TEMPLATE, policy), vocabulary=SPEC.vocabulary(), **kw)


@pytest.fixture(scope="module")
def runs_dir(tmp_path_factory, eq):
    root = tmp_path_factory.mktemp("runs")
    noisy = mix_policies(GAME, eq.policy, uniform_policy(GAME), 0.8)
    config = RunConfig(n_samples=40, n_boot=20)
    _, col, strat = run_direct(
        SPEC, TEMPLATE, _text("noisy", noisy, garbage_rate=0.1), config, root / "a_noisy", equilibrium=eq,
        return_internals=True,
    )  # fmt: skip
    run_play(
        SPEC, TEMPLATE, _text("noisy", noisy, garbage_rate=0.1), config, 300, "equilibrium", root / "a_noisy",
        equilibrium=eq, direct=(col, strat),
    )  # fmt: skip
    exact = MockDistributionClient("first-action", policy_lookup(SPEC, TEMPLATE, first_action_policy(GAME)))
    run_direct(SPEC, TEMPLATE, exact, RunConfig(), root / "b_pass", equilibrium=eq)
    smoke = RunConfig(n_samples=2, n_boot=0)
    run_direct(SPEC, TEMPLATE, _text("smoke", uniform_policy(GAME)), smoke, root / "c_smoke", equilibrium=eq)
    return root


def test_selection_rules(runs_dir, tmp_path):
    records, unreadable = discover(runs_dir)
    assert unreadable == []
    shown, skipped = select(records, min_samples=30)
    assert [r.run_id for r in shown] == ["a_noisy", "b_pass"]
    assert [s[0] for s in skipped] == ["c_smoke"] and skipped[0][1].startswith("smoke test: N=2")

    shown, skipped = select(records, min_samples=30, exclude=["b_pass"])
    assert [r.run_id for r in shown] == ["a_noisy"]
    assert ("b_pass", "excluded by request") in skipped

    # A later run of the same subject and settings supersedes the earlier one.
    copy = tmp_path / "runs"
    shutil.copytree(runs_dir, copy)
    shutil.copytree(copy / "a_noisy", copy / "d_noisy_again")
    manifest = json.loads((copy / "d_noisy_again" / "manifest.json").read_text())
    manifest["created"] = "2999-01-01T00:00:00+00:00"
    (copy / "d_noisy_again" / "manifest.json").write_text(json.dumps(manifest))
    shown, skipped = select(discover(copy)[0], min_samples=30)
    assert [r.run_id for r in shown] == ["b_pass", "d_noisy_again"]
    assert ("a_noisy", "superseded by d_noisy_again") in skipped


def test_reference_display_names(runs_dir):
    records = {r.run_id: r for r in discover(runs_dir)[0]}
    assert records["b_pass"].display_name == "Always check / fold"
    assert records["b_pass"].description == "scripted reference · exact probabilities"
    assert "10% malformed replies" in records["a_noisy"].description


def test_derived_files_match_their_sources(runs_dir):
    run = runs_dir / "a_noisy"
    derive(run, SPEC)
    assert derive(run, SPEC) == []  # up to date: nothing rewritten
    metrics = json.loads((run / "metrics.json").read_text())
    strategy = {r["infostate"]: r for r in json.loads((run / "strategy.json").read_text())}
    breakdown = json.loads((run / "breakdown.json").read_text())
    for seat in breakdown["seats"]:
        i = seat["subject_seat"]
        assert seat["gain"] == pytest.approx(metrics["metrics"]["br_gain_norm"][i], abs=1e-9)
        assert seat["passive"] == pytest.approx(metrics["metrics"]["h2h_loss_norm"][i], abs=1e-9)
        assert sum(r["contribution"] for r in seat["responder"]) == pytest.approx(seat["active"], abs=1e-9)

    replay = json.loads((run / "replay.json").read_text())
    assert replay["source"] == "played" and replay["hands_total"] == 300
    for key, entry in replay["infostates"].items():
        assert entry["estimated"] == strategy[key]["estimated"]
        assert entry["equilibrium"] == strategy[key]["equilibrium"]
    groups = [h["group"] for h in replay["hands"]]
    assert groups.count("played") == 100 and groups.count("key") >= 1
    played = [h for h in replay["hands"] if h["group"] == "played"]
    subject_steps = [s for h in played for s in h["steps"] if s.get("role") == "subject"]
    assert all(
        s["attempts"] and s["attempts"][-1]["status"] in ("ok", "parse_failure", "illegal")
        for s in subject_steps
    )
    assert any(len(s["attempts"]) > 1 for s in subject_steps)  # retries after malformed replies are shown

    # Changing an input makes the derived files stale.
    (run / "metrics.json").write_text((run / "metrics.json").read_text() + "\n")
    assert derive(run, SPEC) == ["breakdown.json", "replay.json"]


def test_simulated_replay_without_play_data(runs_dir):
    derive(runs_dir / "b_pass", SPEC)
    replay = json.loads((runs_dir / "b_pass" / "replay.json").read_text())
    assert replay["source"] == "simulated"
    simulated = [h for h in replay["hands"] if h["group"] == "simulated"]
    assert len(simulated) == 100
    assert {h["subject_seat"] for h in simulated} == {0, 1}
    # Always check/fold never bets, so every simulated subject action is CHECK or FOLD.
    actions = {s["action"] for h in simulated for s in h["steps"] if s.get("role") == "subject"}
    assert actions <= {"CHECK", "FOLD"}


def test_number_formats():
    assert render(-0.0001, "f3") == "0.000"
    assert render(-0.5, "sf3") == "−0.500"
    assert render(0.25, "sf3") == "+0.250"
    assert render(0.625, "pct0") == "62%"  # ties round to even, as in Python's formatting
    assert render(0.0123, "pct1") == "1.2%"
    assert render(None, "f3") == "—"
    assert render(float("nan"), "pct0") == "—"
    assert render(4.36e-05, "sci") == "4.4e−5"
    assert render(2.0, "f3", scale=0.5) == "1.000"
    assert render(1234, "int") == "1,234"
    assert pointer("a/b", "c~d", 0) == "/a~1b/c~0d/0"
    assert resolve({"a/b": {"c~d": [7]}}, pointer("a/b", "c~d", 0)) == 7


def test_subject_sentences():
    row = {"estimated": {"CHECK": 0.38, "BET": 0.62}, "equilibrium": {"CHECK": 0.78, "BET": 0.22}}
    row |= {"support": 50, "filled": False}
    text = str(subject_sentence(Source(None, row, plain=True), "", "sampled"))
    assert text == (
        "The subject plays CHECK 38% of the time here (from 50 valid samples); the equilibrium plays it 78%."
    )

    close = row | {"estimated": {"CHECK": 0.76, "BET": 0.24}}
    text = str(subject_sentence(Source(None, close, plain=True), "", "distribution"))
    assert text.startswith("Close to equilibrium: the largest gap is CHECK at 76% against 78%")
    assert "returned probabilities" in text

    filled = row | {"filled": True}
    assert "filled with a uniform strategy" in str(
        subject_sentence(Source(None, filled, plain=True), "", "sampled")
    )


def test_responder_sentences():
    row = {
        "reach": 0.145,
        "best_response": "CALL",
        "values": {"FOLD": -1.0, "CALL": -0.808},
        "eq_mix_value": -0.936,
        "edge": 0.128,
        "contribution": 0.0186,
        "share": 0.467,
    }
    text = Source(None, row, plain=True)
    assert responder_sentence(text, "", 0, "ante").unescape() == (
        "A best responder plays CALL here, earning −0.808 ante per visit against −0.936 for the "
        "equilibrium mix. The situation arises in 14.5% of hands with the subject as Player 1, adding 0.019 "
        "ante per hand (46.7% of the best responder's gain)."
    )
    html = str(responder_sentence(Source("runs/x/data/breakdown.json", row), "", 0, "ante"))
    assert html.count('class="num"') == 5
    assert 'data-src="runs/x/data/breakdown.json#/contribution"' in html

    unreached = row | {"reach": 0.0, "edge": None}
    assert "never arises" in str(responder_sentence(Source(None, unreached, plain=True), "", 0, "ante"))
    no_gain = row | {"edge": 0.0, "contribution": 0.0}
    assert "already a best response" in str(
        responder_sentence(Source(None, no_gain, plain=True), "", 1, "ante")
    )
    rare = row | {"contribution": 0.0001}
    assert "less than 0.001" in str(responder_sentence(Source(None, rare, plain=True), "", 1, "ante"))
    rounds = responder_sentence(text, "", 0, "point", "round").unescape()
    assert "arises in 14.5% of rounds with the subject as Player 1, adding 0.019 point per round" in rounds


def test_site_builds_and_every_number_traces(runs_dir, tmp_path):
    out = tmp_path / "site"
    result = build_site(runs_dir, out, methodology=METHODOLOGY)
    assert result.shown == ["a_noisy", "b_pass"]
    assert result.report.ok and result.report.numbers > 300 and result.report.files == 11
    for page in ["index.html", "methodology.html", "runs/a_noisy/index.html", "runs/a_noisy/replay.html"]:
        assert (out / page).is_file()
    assert (out / "runs/a_noisy/replay-data.js").read_text().startswith("window.SB_REPLAY = {")

    index = (out / "index.html").read_text()
    assert "Always check / fold" in index and "c_smoke" not in index
    metrics = json.loads((runs_dir / "a_noisy" / "metrics.json").read_text())
    expected = render(metrics["metrics"]["exploitability_norm"], "f3")
    assert 'data-src="runs/a_noisy/data/metrics.json#/metrics/exploitability_norm" data-fmt="f3"' in index
    assert f">{expected}</span>" in index

    build = json.loads((out / "build.json").read_text())
    assert build["skipped"] == [{"id": "c_smoke", "reason": "smoke test: N=2 < 30 samples per infostate"}]
    assert all(not run["source"].startswith("/") for run in build["runs"])  # no local absolute paths

    # Rebuilding over our own output is allowed.
    assert build_site(runs_dir, out, methodology=METHODOLOGY).report.ok


def test_game_supplies_its_own_wording(runs_dir, tmp_path):
    # Liar's Dice is played in rounds and renames the scripted references; Kuhn keeps the defaults.
    dice = get_game_spec("liars_dice")
    template = DEFAULT_TEMPLATES["liars_dice"]
    lowest_bid = policy_lookup(dice, template, first_action_policy(dice.load()))
    root = tmp_path / "runs"
    run_direct(
        dice, template, MockDistributionClient("first-action", lowest_bid), RunConfig(), root / "dice_low",
        equilibrium=solve_equilibrium(dice.load_string, 2000),
    )  # fmt: skip
    shutil.copytree(runs_dir / "b_pass", root / "b_pass")
    out = tmp_path / "site"
    assert build_site(root, out, methodology=METHODOLOGY).report.ok

    records = {r.run_id: r for r in discover(root)[0]}
    assert records["dice_low"].display_name == "Always the lowest legal bid"
    assert records["b_pass"].display_name == "Always check / fold"

    replay = json.loads((root / "dice_low" / "replay.json").read_text())
    assert replay["episode"] == "round"
    assert {h["title"].rsplit(" ", 1)[0] for h in replay["hands"] if h["group"] == "simulated"} == {
        "Simulated round"
    }
    dice_page = (out / "runs/dice_low/index.html").read_text()
    assert "points per round" in dice_page and "Replay rounds" in dice_page
    assert "per hand" not in dice_page and "of hands" not in dice_page
    dice_replay = (out / "runs/dice_low/replay.html").read_text()
    assert "Step through a round." in dice_replay and "Step through a hand" not in dice_replay
    assert "the deal and betting" not in dice_replay
    kuhn_page = (out / "runs/b_pass/index.html").read_text()
    assert "antes per hand" in kuhn_page and "Replay hands" in kuhn_page
    index = (out / "index.html").read_text()
    assert "wins per hand or round" in index and "points per round" in index and "antes per hand" in index


def test_verification_catches_tampering(runs_dir, tmp_path):
    out = tmp_path / "site"
    build_site(runs_dir, out, methodology=METHODOLOGY)
    page = out / "runs" / "b_pass" / "index.html"
    html = page.read_text()
    marker = 'data-src="runs/b_pass/data/metrics.json#/metrics/exploitability_norm" data-fmt="f3"'
    start = html.index(">", html.index(marker)) + 1
    end = html.index("</span>", start)
    page.write_text(html[:start] + "0.001" + html[end:])
    report = verify_site(out)
    assert not report.ok and "page shows '0.001'" in report.errors[0]

    data = out / "runs" / "b_pass" / "data" / "strategy.json"
    data.write_text(data.read_text().replace("0.0", "0.5", 1))
    assert any("differs from" in e for e in verify_site(out).errors)


def test_refuses_to_overwrite_a_foreign_directory(runs_dir, tmp_path):
    out = tmp_path / "precious"
    out.mkdir()
    (out / "notes.txt").write_text("keep me")
    with pytest.raises(SiteError, match="refusing to overwrite"):
        build_site(runs_dir, out, methodology=METHODOLOGY)
    assert (out / "notes.txt").read_text() == "keep me"
