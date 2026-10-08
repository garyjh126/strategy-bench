"""Explanatory sentences, templated from computed numbers (never written by a model).

Each function reads its numbers through a ``Source`` at a JSON pointer ``ptr`` to a row
with the fields written by ``derive`` (subject rows: ``estimated``, ``equilibrium``,
``support``, ``filled``; responder rows: ``reach``, ``values``, ``best_response``,
``eq_mix_value``, ``edge``, ``contribution``, ``share``). On a page every number is a
traceable span; with a plain source the result is plain text.
"""

from __future__ import annotations

from markupsafe import Markup

from strategybench.report.numbers import Source, escape_token, render

#: Below this gap (in probability) between the subject and the equilibrium, say "close".
CLOSE_GAP = 0.05


def _largest_gap(estimated: dict[str, float], equilibrium: dict[str, float]) -> str:
    return max(estimated, key=lambda a: abs(estimated[a] - equilibrium.get(a, 0.0)))


def subject_sentence(src: Source, ptr: str, kind: str) -> Markup:
    """How the subject's action frequencies at one infostate compare with the equilibrium."""
    if src.get(f"{ptr}/filled"):
        return Markup(
            "No valid answer was collected here, so this decision is filled with a uniform strategy "
            "(reported under reliability)."
        )
    est, ref = src.get(f"{ptr}/estimated"), src.get(f"{ptr}/equilibrium")
    label = _largest_gap(est, ref)
    e = src.num(f"{ptr}/estimated/{escape_token(label)}", "pct0")
    r = src.num(f"{ptr}/equilibrium/{escape_token(label)}", "pct0")
    basis = (
        Markup(" (from {} valid samples)").format(src.num(f"{ptr}/support", "int"))
        if kind == "sampled"
        else Markup(" (from the returned probabilities)")
    )
    if abs(est[label] - ref.get(label, 0.0)) < CLOSE_GAP:
        return Markup(
            "Close to equilibrium: the largest gap is {} at {} against {} for the equilibrium{}."
        ).format(label, e, r, basis)
    return Markup("The subject plays {} {} of the time here{}; the equilibrium plays it {}.").format(
        label, e, basis, r
    )


def responder_sentence(src: Source, ptr: str, subject_seat: int, unit: str) -> Markup:
    """What a best responder does at one of its infostates, and what it gains there."""
    reach, edge = src.get(f"{ptr}/reach"), src.get(f"{ptr}/edge")
    best = src.get(f"{ptr}/best_response")
    seat_text = f"Player {subject_seat + 1}"
    if not reach:
        return Markup(
            "With the opponent at equilibrium this situation never arises against this subject, "
            "so it adds nothing to the best responder's gain."
        )
    if edge is None or edge <= 1e-9:
        return Markup("The equilibrium mix is already a best response here, so adapting gains nothing.")
    v_best = src.num(f"{ptr}/values/{escape_token(best)}", "sf3")
    v_mix = src.num(f"{ptr}/eq_mix_value", "sf3")
    r = src.num(f"{ptr}/reach", "pct1")
    head = Markup(
        "A best responder plays {} here, earning {} {} per visit against {} for the equilibrium mix."
    ).format(best, v_best, unit, v_mix)
    if render(src.get(f"{ptr}/contribution"), "f3") == render(0.0, "f3"):
        return head + Markup(
            " The situation arises in {} of hands with the subject as {}, "
            "so it adds less than 0.001 {} per hand."
        ).format(r, seat_text, unit)
    c = src.num(f"{ptr}/contribution", "f3")
    tail = Markup(
        " The situation arises in {} of hands with the subject as {}, adding {} {} per hand"
    ).format(r, seat_text, c, unit)
    if src.get(f"{ptr}/share") is not None:
        tail += Markup(" ({} of the best responder's gain)").format(src.num(f"{ptr}/share", "pct0"))
    return head + tail + Markup(".")
