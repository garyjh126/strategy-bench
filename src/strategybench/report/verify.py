"""Check that every number on the built site traces to a published result file.

Each ``<span class="num">`` names its source (``data-src="<file>#<JSON pointer>"``), format
and optional scale. The check reloads the file, resolves the pointer, formats the value the
same way and compares it with the span's text. It also checks every published data file
against the SHA-256 recorded for it in ``build.json`` (which ``build_site`` takes from the
original file in the run directory).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from strategybench.report.derive import file_sha256
from strategybench.report.numbers import render, resolve


@dataclass
class VerifyReport:
    numbers: int = 0
    pages: int = 0
    files: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class _NumParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[dict[str, str | None], str]] = []
        self._open: dict[str, str | None] | None = None
        self._depth = 0
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._open is not None:
            if tag == "span":
                self._depth += 1
            return
        a = dict(attrs)
        if tag == "span" and "num" in (a.get("class") or "").split():
            self._open, self._depth, self._text = a, 0, []

    def handle_endtag(self, tag: str) -> None:
        if self._open is None or tag != "span":
            return
        if self._depth:
            self._depth -= 1
            return
        self.found.append((self._open, "".join(self._text)))
        self._open = None

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._text.append(data)


def verify_site(site_dir: str | Path) -> VerifyReport:
    site = Path(site_dir)
    report = VerifyReport()
    loaded: dict[str, Any] = {}

    build_path = site / "build.json"
    if not build_path.is_file():
        report.errors.append("build.json is missing")
        return report
    build = json.loads(build_path.read_text())
    for run in build["runs"]:
        for name, digest in run["files"].items():
            published = site / run["published"] / name
            report.files += 1
            if not published.is_file():
                report.errors.append(f"{published.relative_to(site)}: missing")
            elif file_sha256(published) != digest:
                report.errors.append(f"{published.relative_to(site)}: differs from {run['source']}/{name}")

    for page in sorted(site.rglob("*.html")):
        report.pages += 1
        parser = _NumParser()
        parser.feed(page.read_text())
        for attrs, text in parser.found:
            report.numbers += 1
            where = f"{page.relative_to(site)}: {attrs.get('data-src')}"
            try:
                path, ptr = (attrs["data-src"] or "").split("#", 1)
                if path not in loaded:
                    loaded[path] = json.loads((site / path).read_text())
                scale = float(attrs["data-scale"]) if attrs.get("data-scale") else None
                expected = render(resolve(loaded[path], ptr), attrs["data-fmt"] or "", scale)
            except (KeyError, IndexError, TypeError, ValueError, OSError) as e:
                report.errors.append(f"{where}: cannot resolve ({e!r})")
                continue
            if text != expected:
                report.errors.append(f"{where}: page shows {text!r}, file gives {expected!r}")
    return report
