"""Strict action-label parser.

The whole reply, after light normalisation, must equal exactly one label. Normalisation
only strips whitespace, surrounding quotes/backticks/asterisks and one trailing period,
and ignores case. Anything else (extra words, several labels, empty output) fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_STRIP_CHARS = " \t\r\n\"'`*"


class ParseStatus(StrEnum):
    OK = "ok"
    PARSE_FAILURE = "parse_failure"  # not a single recognisable label
    ILLEGAL = "illegal"  # a real game label, but not legal here


@dataclass
class ParseResult:
    status: ParseStatus
    label: str | None = None
    action: int | None = None


def normalise(text: str) -> str:
    out = text.strip(_STRIP_CHARS)
    if out.endswith("."):
        out = out[:-1].strip(_STRIP_CHARS)
    return out.upper()


def parse_label(text: str | None, legal: list[str], vocabulary: frozenset[str]) -> ParseResult:
    if not text:
        return ParseResult(ParseStatus.PARSE_FAILURE)
    candidate = normalise(text)
    legal_upper = {lab.upper(): lab for lab in legal}
    if candidate in legal_upper:
        return ParseResult(ParseStatus.OK, label=legal_upper[candidate])
    if candidate in {v.upper() for v in vocabulary}:
        return ParseResult(ParseStatus.ILLEGAL)
    return ParseResult(ParseStatus.PARSE_FAILURE)
