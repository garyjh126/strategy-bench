import pytest

from strategybench.adapters.parser import ParseStatus, parse_label

VOCAB = frozenset({"CHECK", "BET", "FOLD", "CALL"})
LEGAL = ["CHECK", "BET"]


@pytest.mark.parametrize(
    "text, label",
    [
        ("BET", "BET"),
        ("CHECK", "CHECK"),
        ("bet", "BET"),
        ("Check", "CHECK"),
        ("  BET \n", "BET"),
        ("BET.", "BET"),
        ('"BET"', "BET"),
        ("**CHECK**", "CHECK"),
        ("`BET`", "BET"),
    ],
)
def test_valid_labels(text, label):
    result = parse_label(text, LEGAL, VOCAB)
    assert result.status is ParseStatus.OK
    assert result.label == label


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "   ",
        "I will BET",
        "BET because I have the king",
        "BET or CHECK",
        "BET CHECK",
        "BET\nCHECK",
        "RAISE",
        "B",
        "BETTING",
        "1",
    ],
)
def test_parse_failures(text):
    assert parse_label(text, LEGAL, VOCAB).status is ParseStatus.PARSE_FAILURE


@pytest.mark.parametrize("text", ["CALL", "fold", "FOLD."])
def test_out_of_range_actions_are_illegal_not_unparseable(text):
    assert parse_label(text, LEGAL, VOCAB).status is ParseStatus.ILLEGAL
