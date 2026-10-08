"""Build the static site from a results directory.

Pages: ``index.html`` (leaderboard), ``methodology.html`` and, for every run shown,
``runs/<id>/index.html`` (details) and ``runs/<id>/replay.html`` (match replay). Each run's
result files are published under ``runs/<id>/data/`` next to its pages, so every number can
be followed back to the file it came from. The build ends by verifying exactly that
(``verify.verify_site``) and fails if any number does not match.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import json
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import markdown
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup

from strategybench.games import get_game_spec
from strategybench.games.base import GameSpec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.report.charts import (
    REPLAY_LEGEND,
    STRATEGY_LEGEND,
    BarRow,
    DotRow,
    StrategyRow,
    bar_list,
    dot_plot,
    strategy_bars,
)
from strategybench.report.derive import KEY_SITUATIONS, MIN_CONTRIBUTION, REPLAY_HANDS, derive, file_sha256
from strategybench.report.explain import responder_sentence
from strategybench.report.numbers import Source, escape_token, render, resolve
from strategybench.report.runs import RunRecord, discover, select
from strategybench.report.verify import VerifyReport, verify_site

#: JSON pointers to the plug-in (normalised) value of each metric key in metrics.json.
PLUG_IN = {
    "exploitability": "/metrics/exploitability_norm",
    "br_gain_0": "/metrics/br_gain_norm/0",
    "br_gain_1": "/metrics/br_gain_norm/1",
    "h2h_loss_0": "/metrics/h2h_loss_norm/0",
    "h2h_loss_1": "/metrics/h2h_loss_norm/1",
}
#: Result files published with each run (when present). Call logs stay in the run directory.
PUBLISHED = ["manifest.json", "metrics.json", "strategy.json", "breakdown.json", "replay.json", "play.json"]
GAME_ORDER = ["kuhn", "leduc"]
#: Infostates shown in the "where the best responder gains" chart.
TOP_RESPONDER = 8
#: Subject infostates shown before the rest are folded away.
TOP_SUBJECT = 12


class SiteError(RuntimeError):
    pass


@dataclass
class BuildResult:
    out_dir: Path
    shown: list[str]
    skipped: list[tuple[str, str]]
    derived: dict[str, list[str]]
    report: VerifyReport
    warnings: list[str] = field(default_factory=list)


class RunView:
    """Everything the templates need about one run; numbers come from ``Source`` objects."""

    def __init__(self, rec: RunRecord, spec: GameSpec) -> None:
        self.rec, self.spec = rec, spec
        self.id = rec.run_id
        self.base = f"runs/{rec.run_id}"
        self.data = {name: json.loads((rec.path / name).read_text()) for name in self.files}
        self.metrics = self._src("metrics.json")
        self.manifest = self._src("manifest.json")
        self.breakdown = self._src("breakdown.json")
        self.replay = self._src("replay.json")
        self.play = self._src("play.json") if "play.json" in self.data else None
        self.unit = rec.metrics["payoff_unit"]
        #: Confidence intervals and bias values are stored in native units.
        self.native_scale = 1.0 / float(rec.metrics["metrics"]["unit_size"])
        self.temperature = rec.params.get("temperature")

    @property
    def files(self) -> list[str]:
        return [name for name in PUBLISHED if (self.rec.path / name).is_file()]

    def _src(self, name: str) -> Source:
        return Source(f"{self.base}/data/{name}", self.data[name])

    # Headline values: the bias-corrected estimate with its basic bootstrap interval when the run
    # has them (sampled subjects), otherwise the plug-in value (exact or unbootstrapped runs).

    @property
    def corrected(self) -> bool:
        return bool(self.rec.metrics.get("bias_corrected"))

    @property
    def ci_method(self) -> str:
        return self.rec.metrics.get("ci_method") or "percentile"

    def value(self, key: str) -> float:
        if self.corrected:
            return self.rec.metrics["bias_corrected"][key] * self.native_scale
        return resolve(self.rec.metrics, PLUG_IN[key])

    def est(self, key: str) -> Markup:
        if self.corrected:
            return self.metrics.num(f"/bias_corrected/{key}", "f3", self.native_scale)
        return self.metrics.num(PLUG_IN[key], "f3")

    def plug_in(self, key: str) -> Markup:
        return self.metrics.num(PLUG_IN[key], "f3")

    def ci(self, key: str) -> tuple[float, float] | None:
        lo_hi = (self.rec.metrics.get("ci95") or {}).get(key)
        return None if lo_hi is None else (lo_hi[0] * self.native_scale, lo_hi[1] * self.native_scale)

    def ci_html(self, key: str) -> Markup:
        if self.ci(key) is None:
            return Markup("")
        lo = self.metrics.num(f"/ci95/{key}/0", "f3", self.native_scale)
        hi = self.metrics.num(f"/ci95/{key}/1", "f3", self.native_scale)
        return Markup("[{}, {}]").format(lo, hi)

    @property
    def m1(self) -> float:
        return self.value("exploitability")

    def seat_panels(self) -> list[dict[str, Any]]:
        panels = []
        for s, block in enumerate(self.breakdown.data["seats"]):
            ptr = f"/seats/{s}"
            responder = block["responder"]
            top = [i for i, r in enumerate(responder) if r["contribution"] >= MIN_CONTRIBUTION]
            bars = [
                BarRow(
                    name=responder[i]["short"],
                    value=responder[i]["contribution"],
                    value_html=self.breakdown.num(f"{ptr}/responder/{i}/contribution", "f3"),
                    tip=(
                        f"{responder[i]['short']}: best response {responder[i]['best_response']}, "
                        f"adds {render(responder[i]['contribution'], 'f3')} {self.unit} per hand"
                    ),
                )
                for i in top[:TOP_RESPONDER]
            ]
            examples = [
                {
                    "ptr": f"{ptr}/responder/{i}",
                    "row": responder[i],
                    "sentence": responder_sentence(self.breakdown, f"{ptr}/responder/{i}", s, self.unit),
                    "hand": f"key-p{s + 1}-{rank}",
                }
                for rank, i in enumerate(top[:KEY_SITUATIONS], start=1)
            ]
            subject = []
            for i, row in enumerate(block["subject"]):
                rp = f"{ptr}/subject/{i}"
                subject.append(
                    {
                        "ptr": rp,
                        "row": row,
                        "bars": strategy_bars(
                            [
                                StrategyRow(
                                    label=label,
                                    estimated=p,
                                    equilibrium=row["equilibrium"][label],
                                    estimated_html=self.breakdown.num(
                                        f"{rp}/estimated/{escape_token(label)}", "pct0"
                                    ),
                                    equilibrium_html=self.breakdown.num(
                                        f"{rp}/equilibrium/{escape_token(label)}", "pct0"
                                    ),
                                )
                                for label, p in row["estimated"].items()
                            ]
                        ),
                    }
                )
            panels.append(
                {
                    "seat": s,
                    "ptr": ptr,
                    "block": block,
                    "chart": bar_list(
                        bars,
                        Markup(
                            "Contribution of each of Player {}'s situations to the best responder's gain, "
                            "in {}s per hand. Hover or focus a bar for details; "
                            "the table lists every situation."
                        ).format(block["responder_seat"] + 1, self.unit),
                    )
                    if bars
                    else None,
                    "examples": examples,
                    "responder": list(enumerate(responder)),
                    "subject": subject,
                }
            )
        return panels


@dataclass
class GameView:
    spec: GameSpec
    rows: list[RunView]
    variants: list[tuple[RunView, RunView | None]]
    spread: dict[str, tuple[RunView, RunView, int]]
    chart: Markup
    any_models: bool

    @property
    def title(self) -> str:
        return self.spec.title or self.spec.name

    @property
    def facts(self) -> Source:
        return self.rows[0].metrics


def _identity_without_prompt(v: RunView) -> tuple[str, ...]:
    ident = v.rec.identity
    return ident[:4] + ident[5:]


def _game_views(views: list[RunView]) -> tuple[list[GameView], list[str]]:
    warnings: list[str] = []
    by_game: dict[str, list[RunView]] = defaultdict(list)
    for v in views:
        by_game[v.rec.game].append(v)
    order = sorted(by_game, key=lambda g: (GAME_ORDER.index(g) if g in GAME_ORDER else len(GAME_ORDER), g))

    games = []
    for g in order:
        runs = by_game[g]
        default = DEFAULT_TEMPLATES.get(g)
        main = [v for v in runs if default is None or v.rec.prompt_version == default.version] or runs
        others = [v for v in runs if v not in main]
        main.sort(key=lambda v: (v.m1, v.rec.display_name))

        values = {tuple(round(x, 9) for x in v.rec.metrics["equilibrium"]["values"]) for v in runs}
        if len(values) > 1:
            warnings.append(f"{g}: runs use different equilibrium references {sorted(values)}")

        base_of = {_identity_without_prompt(v): v for v in main}
        variants = [(v, base_of.get(_identity_without_prompt(v))) for v in others]
        spread: dict[str, tuple[RunView, RunView, int]] = {}
        for base in main:
            group = [base] + [v for v, b in variants if b is base]
            if len(group) > 1:
                spread[base.id] = (min(group, key=lambda v: v.m1), max(group, key=lambda v: v.m1), len(group))

        any_models = any(not v.rec.is_reference for v in main)
        dot_rows = []
        names = [v.rec.display_name for v in main]
        for v in main:
            ci = v.ci("exploitability")
            interval = f" [{render(ci[0], 'f3')}, {render(ci[1], 'f3')}]" if ci else ""
            raw = render(v.rec.metrics["metrics"]["exploitability_norm"], "f3")
            plug_in = f", plug-in {raw}" if ci else ""
            name = v.rec.display_name
            if names.count(name) > 1:  # e.g. the equilibrium read exactly and sampled
                name += " (exact)" if v.rec.subject_kind == "distribution" else f" (N = {v.rec.n_samples})"
            dot_rows.append(
                DotRow(
                    name=name,
                    value=v.m1,
                    lo=ci[0] if ci else None,
                    hi=ci[1] if ci else None,
                    emphasis=not v.rec.is_reference,
                    tip=f"{name} ({v.rec.description}): "
                    f"{render(v.m1, 'f3')}{interval}{plug_in} {v.unit} per hand",
                    href=f"{v.base}/index.html",
                )
            )
        unit = main[0].unit
        chart = dot_plot(
            dot_rows,
            Markup(
                "Exploitability (M1) in {}s per hand: bias-corrected estimate with 95% bootstrap interval "
                "(sampled subjects) or exact value. Lower is better; 0 is unexploitable. Hover or focus a "
                "row for its values; the table below lists them all."
            ).format(unit),
            legend=any_models and any(v.rec.is_reference for v in main),
        )
        games.append(GameView(get_game_spec(g), main, variants, spread, chart, any_models))
    return games, warnings


def _git_commit() -> str:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        status = ["git", "status", "--porcelain", "--untracked-files=no"]
        dirty = subprocess.run(status, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return commit + ("-dirty" if dirty else "")


def _prepare_out(out: Path) -> None:
    if out.exists():
        marker = out / "build.json"
        is_site = marker.is_file() and json.loads(marker.read_text()).get("generator") == "strategybench"
        if any(out.iterdir()) and not is_site:
            raise SiteError(f"{out} exists and is not a StrategyBench site; refusing to overwrite it")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    # Mark the directory as ours straight away, so a failed build can be overwritten next time.
    (out / "build.json").write_text(json.dumps({"generator": "strategybench", "status": "incomplete"}))


def _environment() -> Environment:
    templates = importlib.resources.files("strategybench.report") / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["render"] = render
    return env


def build_site(
    runs_dir: str | Path,
    out_dir: str | Path,
    min_samples: int = 30,
    exclude: tuple[str, ...] | list[str] = (),
    replay_hands: int = REPLAY_HANDS,
    methodology: str | Path = "docs/methodology.md",
) -> BuildResult:
    runs_dir, out = Path(runs_dir), Path(out_dir)
    records, unreadable = discover(runs_dir)
    shown, skipped = select(records, min_samples, exclude)
    skipped = unreadable + skipped
    if not shown:
        raise SiteError(f"no runs to show under {runs_dir} (skipped: {skipped})")

    derived = {}
    for rec in shown:
        written = derive(rec.path, get_game_spec(rec.game), replay_hands)
        if written:
            derived[rec.run_id] = written
    views = [RunView(rec, get_game_spec(rec.game)) for rec in shown]
    games, warnings = _game_views(views)

    _prepare_out(out)
    static = importlib.resources.files("strategybench.report") / "static"
    (out / "assets").mkdir()
    for item in static.iterdir():
        if item.is_file():
            (out / "assets" / item.name).write_bytes(item.read_bytes())

    commit = _git_commit()
    build_info = {
        "generator": "strategybench",
        "version": importlib.metadata.version("strategybench"),
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "commit": commit,
        "settings": {"min_samples": min_samples, "exclude": list(exclude), "replay_hands": replay_hands},
        "runs": [],
        "skipped": [{"id": run_id, "reason": reason} for run_id, reason in skipped],
    }
    env = _environment()
    common = {"build": build_info, "games": games}

    for v in views:
        page_dir = out / v.base
        (page_dir / "data").mkdir(parents=True)
        hashes = {}
        for name in v.files:
            shutil.copyfile(v.rec.path / name, page_dir / "data" / name)
            hashes[name] = file_sha256(v.rec.path / name)
        build_info["runs"].append(
            {"id": v.id, "source": f"{runs_dir.name}/{v.id}", "published": f"{v.base}/data", "files": hashes}
        )
        (page_dir / "replay-data.js").write_text(
            "window.SB_REPLAY = " + json.dumps(v.data["replay.json"], separators=(",", ":")) + ";\n"
        )
        ctx = {**common, "root": "../../", "run": v, "game_title": v.spec.title or v.spec.name}
        run_page = env.get_template("run.html")
        (page_dir / "index.html").write_text(
            run_page.render(
                **ctx,
                page="run",
                panels=v.seat_panels(),
                legend=STRATEGY_LEGEND,
                hashes=hashes,
                top_subject=TOP_SUBJECT,
            )
        )
        replay_page = env.get_template("replay.html")
        (page_dir / "replay.html").write_text(
            replay_page.render(**ctx, page="replay", legend_replay=REPLAY_LEGEND)
        )

    (out / "index.html").write_text(env.get_template("index.html").render(**common, root="", page="board"))
    methodology_path = Path(methodology)
    body = (
        Markup(markdown.markdown(methodology_path.read_text(), extensions=["tables", "fenced_code", "toc"]))
        if methodology_path.is_file()
        else Markup("<p>Methodology document not found.</p>")
    )
    (out / "methodology.html").write_text(
        env.get_template("methodology.html").render(**common, root="", page="methodology", body=body)
    )
    (out / "build.json").write_text(json.dumps(build_info, indent=1))

    report = verify_site(out)
    if not report.ok:
        raise SiteError("site verification failed:\n  " + "\n  ".join(report.errors[:20]))
    return BuildResult(out, [v.id for v in views], skipped, derived, report, warnings)
