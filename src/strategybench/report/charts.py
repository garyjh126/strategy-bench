"""Charts as plain HTML/CSS fragments (no charting library, no network, works from file://).

Marks are positioned with percentages so charts reflow with the page. Displayed values are
traceable ``Source.num`` spans; ``data-tip`` repeats a mark's values on hover and keyboard
focus, and every chart has the same values in a table next to it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from markupsafe import Markup

from strategybench.report.numbers import MINUS, render


def nice_ticks(max_value: float, target: int = 5) -> list[float]:
    """Evenly spaced ticks from 0 to a round number at or above ``max_value``."""
    if not max_value or max_value <= 0 or math.isnan(max_value):
        max_value = 1.0
    raw = max_value / target
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    n = math.ceil(max_value / step - 1e-9)
    return [round(i * step, 12) for i in range(n + 1)]


def _tick_text(x: float) -> str:
    return f"{x:.10g}".replace("-", MINUS)


def _pct(x: float, top: float) -> str:
    return f"{100 * min(max(x / top, 0.0), 1.0):.3f}%"


def _axis(ticks: list[float], cls: str) -> Markup:
    top = ticks[-1]
    labels = Markup("").join(
        Markup('<span style="left:{}">{}</span>').format(_pct(t, top), _tick_text(t)) for t in ticks
    )
    return Markup(
        '<div class="{}-axis" aria-hidden="true"><div></div><div class="ticks">{}</div></div>'
    ).format(cls, labels)


def _grid(ticks: list[float]) -> Markup:
    top = ticks[-1]
    return Markup("").join(Markup('<i class="grid" style="left:{}"></i>').format(_pct(t, top)) for t in ticks)


@dataclass
class DotRow:
    name: str | Markup
    value: float
    lo: float | None
    hi: float | None
    emphasis: bool
    tip: str
    href: str | None = None


def dot_plot(rows: list[DotRow], caption: Markup, legend: bool) -> Markup:
    """One dot per row with an optional confidence-interval whisker, on a shared 0-based axis."""
    ticks = nice_ticks(max([r.hi if r.hi is not None else r.value for r in rows] + [0.0]))
    top = ticks[-1]
    grid = _grid(ticks)
    body = []
    for r in rows:
        name = Markup('<a href="{}">{}</a>').format(r.href, r.name) if r.href else r.name
        ref = "" if r.emphasis else " ref"
        whisker = Markup("")
        if r.lo is not None and r.hi is not None:
            left, right = min(max(r.lo / top, 0), 1), min(max(r.hi / top, 0), 1)
            whisker = Markup('<span class="dp-ci{}" style="left:{:.3f}%;width:{:.3f}%"></span>').format(
                ref, 100 * left, 100 * (right - left)
            )
        body.append(
            Markup(
                '<div class="dp-row" tabindex="0" data-tip="{}"><div class="dp-name">{}</div>'
                '<div class="dp-track">{}{}<span class="dp-dot{}" style="left:{}"></span></div></div>'
            ).format(r.tip, name, grid, whisker, ref, _pct(r.value, top))
        )
    key = Markup("")
    if legend:
        key = Markup(
            '<div class="legend"><span><i class="key-dot"></i>LLM subject</span>'
            '<span><i class="key-dot ref"></i>Scripted reference</span>'
            '<span><i class="key-ci"></i>95% bootstrap interval</span></div>'
        )
    return Markup('<figure class="chart dotplot">{}{}{}<figcaption>{}</figcaption></figure>').format(
        key, Markup("").join(body), _axis(ticks, "dp"), caption
    )


@dataclass
class BarRow:
    name: str | Markup
    value: float
    value_html: Markup
    tip: str
    muted: bool = False


def bar_list(rows: list[BarRow], caption: Markup) -> Markup:
    """Ranked horizontal bars from a shared zero baseline, value at each bar's tip."""
    ticks = nice_ticks(max([r.value for r in rows] + [0.0]))
    top = ticks[-1]
    grid = _grid(ticks)
    body = []
    for r in rows:
        pos = _pct(r.value, top)
        body.append(
            Markup(
                '<div class="bl-row" tabindex="0" data-tip="{}"><div class="bl-name">{}</div>'
                '<div class="bl-track">{}<span class="bl-bar{}" style="width:{}"></span>'
                '<span class="bl-val" style="left:{}">{}</span></div></div>'
            ).format(r.tip, r.name, grid, " muted" if r.muted else "", pos, pos, r.value_html)
        )
    return Markup('<figure class="chart barlist">{}{}<figcaption>{}</figcaption></figure>').format(
        Markup("").join(body), _axis(ticks, "bl"), caption
    )


@dataclass
class StrategyRow:
    label: str
    estimated: float
    equilibrium: float
    estimated_html: Markup
    equilibrium_html: Markup
    chosen: bool = False


def strategy_bars(rows: list[StrategyRow], subject: str = "subject") -> Markup:
    """Per action: a bar for the subject's frequency and a tick for the equilibrium's."""
    out = []
    for r in rows:
        est, ref = render(r.estimated, "pct0"), render(r.equilibrium, "pct0")
        tip = f"{r.label}: {subject} {est}, equilibrium {ref}"
        out.append(
            Markup(
                '<div class="sb-row{}" tabindex="0" data-tip="{}"><span class="sb-label">{}</span>'
                '<span class="sb-track"><span class="sb-bar" style="width:{:.2f}%"></span>'
                '<span class="sb-tick" style="left:{:.2f}%"></span></span>'
                '<span class="sb-nums">{} <span class="muted">eq {}</span></span></div>'
            ).format(
                " chosen" if r.chosen else "",
                tip,
                r.label,
                100 * r.estimated,
                100 * r.equilibrium,
                r.estimated_html,
                r.equilibrium_html,
            )
        )
    return Markup('<div class="sbars">{}</div>').format(Markup("").join(out))


STRATEGY_LEGEND = Markup(
    '<div class="legend"><span><i class="key-bar"></i>Subject (estimated)</span>'
    '<span><i class="key-tick"></i>Equilibrium</span></div>'
)


REPLAY_LEGEND = Markup(
    '<div class="legend"><span><i class="key-bar"></i>Subject (estimated)</span>'
    '<span><i class="key-tick"></i>Equilibrium</span>'
    '<span><i class="key-bar ref"></i>Opponent\'s equilibrium mix</span>'
    '<span><i class="key-badge"></i>Best response</span></div>'
)
