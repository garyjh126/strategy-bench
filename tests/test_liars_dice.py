"""Liar's Dice: game spec, prompts and pipeline checks against OpenSpiel's direct computation."""

import collections

import pytest
from open_spiel.python.algorithms import exploitability, get_all_states

from strategybench.adapters.mock import MockDistributionClient, MockTextClient, policy_lookup
from strategybench.adapters.parser import ParseStatus
from strategybench.analysis.metrics import compute_metrics, solve_equilibrium
from strategybench.baselines.scripted import first_action_policy, last_action_policy, uniform_policy
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES, TEMPLATES
from strategybench.runner import RunConfig, run_direct

SPEC = get_game_spec("liars_dice")
TEMPLATE = DEFAULT_TEMPLATES["liars_dice"]
GAME = SPEC.load()
LIAR = 6
BIDS = ("1x1", "1x2", "1x3", "2x1", "2x2", "2x3")


def bid(quantity, face):
    return (quantity - 1) * 3 + (face - 1)


def _state(dice, *bids):
    s = GAME.new_initial_state()
    for d in dice:
        s.apply_action(d - 1)
    for b in bids:
        s.apply_action(b)
    return s


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium(SPEC.load_string, 2000)


def test_infostates_and_label_sets():
    infos = enumerate_infostates(GAME)
    assert len(infos) == 192
    prompts = [TEMPLATE.render(SPEC, i.state) for i in infos]
    assert len({p.hash for p in prompts}) == 192
    for info, prompt in zip(infos, prompts, strict=True):
        assert prompt.labels == tuple(SPEC.action_labels(info.state)[a] for a in info.legal_actions)
    # After a last bid b (0-5) the options are the higher bids and LIAR, and 2^b bid histories end
    # in b; the opening offers every bid but no LIAR. Three die values each.
    assert collections.Counter(p.labels for p in prompts) == {
        BIDS: 3,
        (*BIDS[1:], "LIAR"): 3,
        (*BIDS[2:], "LIAR"): 6,
        (*BIDS[3:], "LIAR"): 12,
        (*BIDS[4:], "LIAR"): 24,
        (*BIDS[5:], "LIAR"): 48,
        ("LIAR",): 96,
    }


@pytest.mark.parametrize(
    "dice, bids, returns",
    [
        ((2, 3), [bid(1, 2)], [1.0, -1.0]),  # a 3 counts towards a bid on 2: true, bidder wins
        ((1, 1), [bid(1, 2)], [-1.0, 1.0]),  # false: the caller wins
        ((1, 3), [bid(2, 1)], [1.0, -1.0]),  # 1 and a wild 3 make two 1s
        ((1, 3), [bid(2, 3)], [-1.0, 1.0]),  # a bid on 3 counts only 3s
        ((2, 2), [bid(1, 3)], [-1.0, 1.0]),
        ((3, 3), [bid(1, 1), bid(2, 3)], [-1.0, 1.0]),  # Player 2's true bid beats Player 1's call
        ((1, 2), [bid(1, 1), bid(2, 2)], [1.0, -1.0]),  # Player 2's false bid loses to Player 1's call
    ],
)
def test_scoring_matches_the_rules_text(dice, bids, returns):
    s = _state(dice, *bids, LIAR)
    assert s.is_terminal() and s.returns() == returns


def test_render_opening_bid():
    s = _state((2, 3))
    assert SPEC.render_infostate(s) == "You are Player 1 (you bid first).\nYour die: 2.\nBids so far: none."
    assert SPEC.action_labels(s) == dict(enumerate(BIDS))  # no LIAR before the first bid


def test_render_facing_a_bid():
    s = _state((2, 3), bid(1, 2))
    assert SPEC.render_infostate(s) == (
        "You are Player 2 (you bid second).\n"
        "Your die: 3.\n"
        "Bids so far: Player 1 bid 1x2.\n"
        "Current bid: 1x2 by Player 1 (true if at least one of the two dice shows 2 or 3)."
    )
    assert SPEC.action_labels(s) == {2: "1x3", 3: "2x1", 4: "2x2", 5: "2x3", LIAR: "LIAR"}


def test_render_after_the_highest_bid():
    s = _state((1, 2), bid(1, 1), bid(2, 3))
    assert SPEC.render_infostate(s) == (
        "You are Player 1 (you bid first).\n"
        "Your die: 1.\n"
        "Bids so far: Player 1 bid 1x1, Player 2 bid 2x3.\n"
        "Current bid: 2x3 by Player 2 (true if both dice show 3)."
    )
    assert SPEC.action_labels(s) == {LIAR: "LIAR"}


def test_claims_for_every_bid():
    claims = {
        b: SPEC.render_infostate(_state((1, 1), bid(*b))).splitlines()[-1]
        for b in [(1, 1), (1, 3), (2, 1), (2, 2)]
    }
    assert claims == {
        (1, 1): "Current bid: 1x1 by Player 1 (true if at least one of the two dice shows 1 or 3).",
        (1, 3): "Current bid: 1x3 by Player 1 (true if at least one of the two dice shows 3).",
        (2, 1): "Current bid: 2x1 by Player 1 (true if both dice show 1 or 3).",
        (2, 2): "Current bid: 2x2 by Player 1 (true if both dice show 2 or 3).",
    }


def test_render_depends_only_on_the_infostate():
    # Every history in an infostate (any opponent die) renders the same text, so the opponent's
    # die is never shown and identical prompts always mean identical infostates.
    states = get_all_states.get_all_states(
        GAME, depth_limit=-1, include_terminals=False, include_chance_states=False
    )
    texts = collections.defaultdict(set)
    for s in states.values():
        texts[s.information_state_string()].add(SPEC.render_infostate(s))
    assert len(texts) == 192 and all(len(t) == 1 for t in texts.values())


def test_labels_parse_and_vocabulary_covers_them():
    used = set()
    for info in enumerate_infostates(GAME):
        labels = SPEC.action_labels(info.state)
        used |= set(labels.values())
        for action, label in labels.items():
            for text in (label, label.lower(), label.upper(), f" {label}.", f"**{label}**", f'"{label}"'):
                result = SPEC.parse_action(info.state, text)
                assert result.status is ParseStatus.OK and result.action == action
    assert used == SPEC.vocabulary() == {*BIDS, "LIAR"}


def test_illegal_and_unparseable_replies():
    s = _state((2, 3), bid(2, 1))
    assert SPEC.parse_action(s, "2X2").action == bid(2, 2)
    assert SPEC.parse_action(s, "1x2").status is ParseStatus.ILLEGAL  # not higher than 2x1
    assert SPEC.parse_action(_state((2, 3)), "LIAR").status is ParseStatus.ILLEGAL  # opening move
    for text in ("2x4", "two 2s", "2x2 or LIAR", "2 x 2", ""):
        assert SPEC.parse_action(s, text).status is ParseStatus.PARSE_FAILURE


@pytest.mark.parametrize("version", [v for v in TEMPLATES if v.startswith("liars_dice")])
def test_rules_text_names_every_label(version):
    system = TEMPLATES[version].system
    assert ", ".join(BIDS[:-1]) in system and "LIAR" in system


def test_equilibrium_value(eq):
    assert eq.values[0] == pytest.approx(0.1111, abs=1e-3)
    assert eq.exploitability < 1e-3


@pytest.mark.parametrize("make", [first_action_policy, last_action_policy])
def test_deterministic_agents_match_direct_computation(eq, make):
    policy = make(GAME)
    client = MockTextClient("t", policy_lookup(SPEC, TEMPLATE, policy), vocabulary=SPEC.vocabulary())
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(n_samples=2, n_boot=0), equilibrium=eq)
    direct = compute_metrics(GAME, policy, eq)
    assert result["metrics"]["exploitability"] == pytest.approx(direct.exploitability, abs=1e-12)
    assert result["metrics"]["h2h_loss"] == pytest.approx(direct.h2h_loss, abs=1e-12)
    assert result["coverage"]["k=5"] == 0.0  # only 2 samples each
    assert result["filled"]["count"] == 0


def test_uniform_via_distribution_client_matches_openspiel(eq):
    client = MockDistributionClient("u", policy_lookup(SPEC, TEMPLATE, uniform_policy(GAME)))
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(), equilibrium=eq)
    expected = exploitability.exploitability(GAME, uniform_policy(GAME))
    assert result["metrics"]["exploitability"] == pytest.approx(expected, abs=1e-9)
    assert client.calls == 192


def test_equilibrium_via_distribution_client_is_unexploitable(eq):
    client = MockDistributionClient("cfr", policy_lookup(SPEC, TEMPLATE, eq.policy))
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(), equilibrium=eq)
    assert result["metrics"]["exploitability"] < 1e-3


def test_replay_text():
    assert SPEC.describe_chance(_state(()), 1) == "Player 1 rolls a 2"
    assert SPEC.describe_chance(_state((2,)), 2) == "Player 2 rolls a 3"
    assert SPEC.short_label(_state((2, 3))) == "Die 2 · opening bid"
    assert SPEC.short_label(_state((2, 3), bid(1, 2))) == "Die 3 · P1 1x2"
    assert SPEC.short_label(_state((2, 3), bid(1, 2), bid(2, 1))) == "Die 2 · P1 1x2, P2 2x1"
