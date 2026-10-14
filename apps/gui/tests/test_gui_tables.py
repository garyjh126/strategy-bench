"""Tables: move rules, hidden information, totals and export, seat policies, best-response hints."""

import pytest
from sbgui import hints
from sbgui.policies import Decision, RunPolicy, TablePolicy, UniformPolicy
from sbgui.runs import RunLibrary
from sbgui.session import Conflict, Seat, Session

JACK, QUEEN, KING = 0, 1, 2
CHECK, BET = 0, 1  # FOLD and CALL share the same action ids


class Always:
    """A scripted bot that always plays one action id."""

    def __init__(self, action):
        self.action = action

    def decide(self, state):
        return Decision({self.action: 1.0})


def human():
    return Seat("human", "Human", "")


def bot(policy, kind="uniform"):
    return Seat(kind, "Bot", "", policy)


def play_bots(session):
    """Advance chance and bot moves until a human must act or the hand is over."""
    while session.phase() in ("chance", "bot"):
        assert session.step(session.ply)


def deal(session, *cards):
    """Deal fixed cards (Kuhn deals one per player), bypassing the session's random draws and log."""
    for card in cards:
        session.state.apply_action(card)


def test_bots_play_whole_hands_and_totals_add_up(kuhn, profiles):
    s = Session("t", kuhn, [bot(UniformPolicy()), bot(UniformPolicy())], profiles, seed=1)
    for hand in range(1, 21):
        play_bots(s)
        assert s.phase() == "terminal"
        s.next_hand(hand)
    returns = [h["returns"] for h in s.finished]
    assert len(returns) == 20
    assert s.totals == pytest.approx([sum(r[i] for r in returns) for i in range(2)])
    assert sum(s.totals) == pytest.approx(0.0)  # zero-sum


def test_same_seed_same_hands(kuhn, profiles):
    def history(seed):
        s = Session("t", kuhn, [bot(UniformPolicy()), bot(UniformPolicy())], profiles, seed=seed)
        for hand in range(1, 11):
            play_bots(s)
            s.next_hand(hand)
        return [h["history"] for h in s.finished]

    assert history(5) == history(5)
    assert history(5) != history(6)


def test_stale_illegal_and_out_of_turn_requests_are_refused(kuhn, profiles):
    s = Session("t", kuhn, [human(), bot(UniformPolicy())], profiles, seed=0)
    with pytest.raises(Conflict, match="moved on"):
        s.step(s.ply + 1)
    play_bots(s)
    assert s.phase() == "human"
    with pytest.raises(Conflict, match="finish the current hand"):
        s.next_hand(s.hand)
    with pytest.raises(ValueError, match="not legal"):
        s.act(7, s.ply)
    with pytest.raises(ValueError, match="integer"):
        s.act("1", s.ply)
    with pytest.raises(Conflict, match="moved on"):
        s.act(CHECK, s.ply - 1)
    with pytest.raises(Conflict, match="nothing to step"):
        s.step(s.ply)


def test_opponent_card_and_bot_probabilities_stay_hidden_until_the_hand_ends(kuhn, profiles):
    s = Session("t", kuhn, [human(), bot(Always(BET))], profiles, seed=0)
    play_bots(s)  # deal both cards
    s.act(CHECK, s.ply)
    play_bots(s)  # the bot bets; the human must answer
    view = s.view()
    assert view["viewer"] == 0 and not view["revealed"]
    own, theirs, my_move, their_move = view["log"]
    assert not own["hidden"] and theirs["hidden"]
    assert "hidden from you" in theirs["text"] and "label" not in theirs
    assert my_move["label"] == "CHECK" and their_move["label"] == "BET"
    assert "probs" not in their_move  # the bot's mix depends on its private card

    s.act(CHECK, s.ply)  # FOLD
    view = s.view()
    assert view["phase"] == "terminal" and view["revealed"]
    assert not any(e["hidden"] for e in view["log"])
    assert view["log"][3]["probs"] == [{"label": "CHECK", "p": 0.0}, {"label": "BET", "p": 1.0}]
    assert view["returns"] == [-1.0, 1.0]


def test_reveal_shows_everything_during_the_hand(kuhn, profiles):
    s = Session("t", kuhn, [human(), bot(UniformPolicy())], profiles, seed=0)
    play_bots(s)
    assert not any(e["hidden"] for e in s.view(reveal=True)["log"])


def test_export_holds_every_hand(kuhn, profiles):
    s = Session("t", kuhn, [bot(UniformPolicy()), bot(UniformPolicy())], profiles, seed=2)
    for hand in range(1, 4):
        play_bots(s)
        s.next_hand(hand)
    out = s.export()
    assert out["format"] == "strategybench-gui-hands/1"
    assert out["hands_played"] == 3 == len(out["hands"])
    assert out["totals"] == s.totals
    assert all(h["events"] and h["history"] for h in out["hands"])


def test_run_policy_plays_the_measured_strategy_and_reports_fallbacks(kuhn, runs_dir):
    library = RunLibrary(runs_dir)
    (run,) = library.list(kuhn.key)
    policy = RunPolicy(library.strategy(run), kuhn.action_labels)

    state = kuhn.game.new_initial_state()
    state.apply_action(JACK)
    state.apply_action(QUEEN)
    filled = policy.decide(state)  # Player 1 with the Jack: marked as having no valid samples
    assert filled.probs == {CHECK: 0.5, BET: 0.5} and "no valid samples" in filled.note

    state = kuhn.game.new_initial_state()
    state.apply_action(QUEEN)
    state.apply_action(KING)
    measured = policy.decide(state)
    assert measured.probs == {CHECK: 1.0, BET: 0.0} and measured.note is None


def test_run_policy_falls_back_when_a_situation_is_missing(kuhn, runs_dir):
    library = RunLibrary(runs_dir)
    (run,) = library.list(kuhn.key)
    strategy = library.strategy(run)
    policy = RunPolicy(strategy, kuhn.action_labels)
    # Find the one decision state whose infostate was left out of strategy.json.
    for p1 in (JACK, QUEEN, KING):
        for p2 in (JACK, QUEEN, KING):
            if p1 == p2:
                continue
            for moves in ([], [CHECK], [BET], [CHECK, BET]):
                state = kuhn.game.new_initial_state()
                for a in (p1, p2, *moves):
                    state.apply_action(a)
                key = state.information_state_string()
                if strategy.lookup(state.current_player(), key) is None:
                    decision = policy.decide(state)
                    assert decision.probs == {CHECK: 0.5, BET: 0.5}
                    assert "not in the run" in decision.note
                    return
    raise AssertionError("no missing situation found")


def test_table_policy_falls_back_on_unknown_or_illegal_entries(kuhn):
    state = kuhn.game.new_initial_state()
    state.apply_action(JACK)
    state.apply_action(QUEEN)
    key = state.information_state_string()
    assert TablePolicy({key: {CHECK: 0.25, BET: 0.75}}).decide(state).probs == {CHECK: 0.25, BET: 0.75}
    assert "missing" in TablePolicy({}).decide(state).note
    assert "missing" in TablePolicy({key: {CHECK: 0.5, 5: 0.5}}).decide(state).note


@pytest.mark.parametrize(
    "card, check, bet",
    [
        # Player 1's opening values against a uniformly random Player 2, worked by hand:
        # Jack: check -> P2 checks (lose 1) or bets (fold, lose 1) = -1;
        #       bet -> P2 calls (lose 2) or folds (win 1) = -0.5.
        (JACK, -1.0, -0.5),
        # Queen: check -> showdown or call against J/K evens out = 0; bet -> called 0, fold +1 = 0.5.
        (QUEEN, 0.0, 0.5),
        # King: check -> +1 or call a bet for +2 = 1.5; bet -> called +2 or folded +1 = 1.5.
        (KING, 1.5, 1.5),
    ],
)
def test_best_response_hint_matches_hand_computed_values(kuhn, profiles, card, check, bet):
    s = Session("t", kuhn, [human(), bot(UniformPolicy())], profiles, seed=0)
    other = JACK if card != JACK else QUEEN
    deal(s, card, other)
    hint = hints.best_response_hint(s)
    assert hint["available"]
    values = {v["action"]: v["value"] for v in hint["values"]}
    assert values == pytest.approx({CHECK: check, BET: bet})
    best = {v["action"] for v in hint["values"] if v["best"]}
    assert best == ({BET} if bet > check else {CHECK, BET})


def test_hint_is_withheld_where_it_has_no_meaning(kuhn, kuhn3, profiles):
    two_humans = Session("t", kuhn, [human(), human()], profiles, seed=0)
    play_bots(two_humans)
    assert "human" in hints.best_response_hint(two_humans)["reason"]
    three = Session("t", kuhn3, [human(), bot(UniformPolicy()), bot(UniformPolicy())], profiles, seed=0)
    play_bots(three)
    assert "two-player" in hints.best_response_hint(three)["reason"]
