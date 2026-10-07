from strategybench.adapters.parser import ParseStatus
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES

KING, JACK = 2, 0
PASS, BET = 0, 1


def _state(*history):
    spec = get_game_spec("kuhn")
    state = spec.load().new_initial_state()
    for a in history:
        state.apply_action(a)
    return spec, state


def test_twelve_infostates():
    spec = get_game_spec("kuhn")
    infos = enumerate_infostates(spec.load())
    assert len(infos) == 12
    assert sum(i.player == 0 for i in infos) == 6


def test_labels_depend_on_facing_a_bet():
    spec, s = _state(KING, JACK)
    assert spec.action_labels(s) == {PASS: "CHECK", BET: "BET"}
    s.apply_action(BET)
    assert spec.action_labels(s) == {PASS: "FOLD", BET: "CALL"}


def test_render_first_decision():
    spec, s = _state(KING, JACK)
    assert spec.render_infostate(s) == (
        "You are Player 1 (you act first).\nYour card: King.\nActions so far: none."
    )


def test_render_after_check_and_bet():
    spec, s = _state(KING, JACK, PASS, BET)
    assert spec.render_infostate(s) == (
        "You are Player 1 (you act first).\nYour card: King.\nActions so far: Player 1 checked, Player 2 bet."
    )


def test_render_hides_opponent_card():
    spec, s = _state(JACK, KING, PASS)
    text = spec.render_infostate(s)
    assert "Player 2" in text and "King" in text and "Jack" not in text


def test_parse_action_maps_label_to_openspiel_action():
    spec, s = _state(KING, JACK, BET)
    result = spec.parse_action(s, "call")
    assert result.status is ParseStatus.OK and result.action == BET
    assert spec.parse_action(s, "BET").status is ParseStatus.ILLEGAL


def test_prompts_differ_only_in_situation_and_are_unique_per_infostate():
    spec = get_game_spec("kuhn")
    template = DEFAULT_TEMPLATES["kuhn"]
    prompts = [template.render(spec, i.state) for i in enumerate_infostates(spec.load())]
    assert len({p.hash for p in prompts}) == 12
    assert len({p.system for p in prompts}) == 1
    assert all(p.user.rstrip().endswith("Do not write anything else.") for p in prompts)
