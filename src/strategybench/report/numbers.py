"""Number formatting and traceable rendering.

Every number on the site's pages is rendered by ``Source.num``, which wraps it in a span
carrying ``data-src`` (a published result file plus a JSON pointer into it), ``data-fmt``
and, when the value is rescaled, ``data-scale``. ``verify.verify_site`` re-reads every such
span and checks that its text is exactly what the file says.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from markupsafe import Markup, escape

MINUS = "−"
MISSING = "—"


def _fixed(digits: int, signed: bool = False) -> Callable[[float], str]:
    def fmt(x: float) -> str:
        text = f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}"
        if float(text) == 0:
            text = f"{0:.{digits}f}"
        return text.replace("-", MINUS)

    return fmt


def _percent(digits: int) -> Callable[[float], str]:
    def fmt(x: float) -> str:
        text = f"{100 * x:.{digits}f}"
        return ("0" if float(text) == 0 and digits == 0 else text).replace("-", MINUS) + "%"

    return fmt


def _scientific(x: float) -> str:
    if x == 0:
        return "0"
    mantissa, exponent = f"{x:.1e}".split("e")
    return f"{mantissa}e{int(exponent)}".replace("-", MINUS)


def _usd(x: float) -> str:
    return f"${x:,.2f}" if x >= 0.01 or x == 0 else f"${x:.4f}"


FORMATS: dict[str, Callable[[Any], str]] = {
    "f1": _fixed(1),
    "f3": _fixed(3),
    "sf3": _fixed(3, signed=True),
    "pct0": _percent(0),
    "pct1": _percent(1),
    "sci": _scientific,
    "int": lambda x: f"{int(x):,}",
    "usd": _usd,
    "text": str,
}


def render(value: Any, fmt: str, scale: float | None = None) -> str:
    """Format ``value`` (times ``scale``) for display; missing values render as a dash."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return MISSING
    if scale is not None:
        value = value * scale
    return FORMATS[fmt](value)


def escape_token(token: object) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def pointer(*tokens: object) -> str:
    """JSON pointer (RFC 6901) from path tokens, e.g. ``pointer("ci95", "exploitability", 0)``."""
    return "".join(f"/{escape_token(t)}" for t in tokens)


def resolve(data: Any, ptr: str) -> Any:
    if ptr == "":
        return data
    if not ptr.startswith("/"):
        raise ValueError(f"invalid JSON pointer {ptr!r}")
    for raw in ptr[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        data = data[int(token)] if isinstance(data, list) else data[token]
    return data


class Source:
    """A published JSON result file, used to render traceable numbers.

    ``path`` is the file's path relative to the site root. With ``plain=True`` (for text
    that is stored in another result file rather than shown as HTML), ``num`` returns the
    formatted value without the span.
    """

    def __init__(self, path: str | None, data: Any, plain: bool = False) -> None:
        self.path = path
        self.data = data
        self.plain = plain

    def get(self, ptr: str) -> Any:
        return resolve(self.data, ptr)

    def has(self, ptr: str) -> bool:
        try:
            self.get(ptr)
        except (KeyError, IndexError, TypeError):
            return False
        return True

    def num(self, ptr: str, fmt: str, scale: float | None = None) -> Markup:
        text = render(self.get(ptr), fmt, scale)
        if self.plain or self.path is None:
            return escape(text)
        scale_attr = Markup(' data-scale="{}"').format(repr(scale)) if scale not in (None, 1.0) else ""
        return Markup('<span class="num" data-src="{}#{}" data-fmt="{}"{} title="{} {}">{}</span>').format(
            self.path, ptr, fmt, scale_attr, self.path, ptr, text
        )
