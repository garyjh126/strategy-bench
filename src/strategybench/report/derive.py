"""Derived result files written into a run directory: ``breakdown.json`` and ``replay.json``.

Both are computed only from the run's own result files (``strategy.json``, ``metrics.json``,
``manifest.json``, ``calls.jsonl`` and, after a play-mode run, ``play.json``, ``hands.jsonl``
and ``play_calls.jsonl``), so they can be rebuilt at any time. Each records the SHA-256 of
its inputs and is recomputed when an input changes.

``breakdown.json``: the per-infostate decomposition of M2 (``analysis.breakdown``) for both
seats, plus the subject's own infostates ranked by reach-weighted distance from equilibrium.
All values are in normalised units (``payoff_unit`` per hand).

``replay.json``: hands to replay, with everything the replay view shows at each decision.
Three kinds of hand:

* ``key``: for each seat, the infostates where the best responder gains most. The hand is
  the most likely deal and history reaching the infostate; from there the responder plays
  the best response and the subject its most likely action.
* ``played``: the first hands of a play-mode match, with the subject's raw replies.
* ``simulated`` (only without play-mode data): hands drawn from the estimated strategy
  against the equilibrium. Every query is independent and context-free, so these follow
  the same distribution as live play, but they were not played live.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyspiel
from open_spiel.python import policy as policy_lib

from strategybench.analysis.breakdown import br_breakdown
from strategybench.estimation.infostates import InfoState, enumerate_infostates
from strategybench.games.base import GameSpec
from strategybench.report.explain import responder_sentence, subject_sentence
from strategybench.report.numbers import Source, render

DERIVED_VERSION = 1
REPLAY_HANDS = 100
#: Key-situation hands per seat, taken from the infostates with the largest contributions.
KEY_SITUATIONS = 3
#: Contributions below this display as 0.000 (three decimals) and get no key-situation hand.
MIN_CONTRIBUTION = 0.0005
#: Example failed replies kept per infostate.
FAILURE_EXAMPLES = 2
_MAX_REPLY_CHARS = 300


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _inputs(run_dir: Path, names: list[str]) -> dict[str, str]:
    return {name: file_sha256(run_dir / name) for name in names if (run_dir / name).is_file()}


def _is_current(path: Path, inputs: dict[str, str], params: dict[str, Any]) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return False
    return (
        data.get("version") == DERIVED_VERSION
        and data.get("derived_from") == inputs
        and data.get("params", {}) == params
    )


def _finite(x: float) -> float | None:
    return None if x is None or math.isnan(x) else float(x)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=1, allow_nan=False))


@dataclass
class RunPolicies:
    game: pyspiel.Game
    infostates: dict[str, InfoState]
    #: Infostate key -> {action: label}.
    labels: dict[str, dict[int, str]]
    #: Infostate key -> its strategy.json row.
    rows: dict[str, dict[str, Any]]
    estimated: policy_lib.TabularPolicy
    equilibrium: policy_lib.TabularPolicy


def load_policies(spec: GameSpec, strategy_rows: list[dict[str, Any]]) -> RunPolicies:
    """Rebuild the estimated and equilibrium strategies from a run's ``strategy.json``."""
    game = spec.load()
    infos = {i.key: i for i in enumerate_infostates(game)}
    rows = {r["infostate"]: r for r in strategy_rows}
    estimated, equilibrium = policy_lib.TabularPolicy(game), policy_lib.TabularPolicy(game)
    if set(rows) != set(infos) or set(estimated.state_lookup) != set(infos):
        raise ValueError(f"strategy.json does not match the infostates of {spec.load_string}")
    labels = {}
    for key, info in infos.items():
        labels[key] = spec.action_labels(info.state)
        for policy, field in ((estimated, "estimated"), (equilibrium, "equilibrium")):
            row = policy.policy_for_key(key)
            row[:] = 0.0
            for action, label in labels[key].items():
                row[action] = rows[key][field][label]
    return RunPolicies(game, infos, labels, rows, estimated, equilibrium)


def write_breakdown(run_dir: Path, spec: GameSpec, force: bool = False) -> tuple[Path, bool]:
    """Write ``breakdown.json`` unless it is current. Returns (path, whether it was written)."""
    out = run_dir / "breakdown.json"
    inputs = _inputs(run_dir, ["strategy.json", "metrics.json"])
    if not force and _is_current(out, inputs, {}):
        return out, False
    strategy = json.loads((run_dir / "strategy.json").read_text())
    metrics = json.loads((run_dir / "metrics.json").read_text())
    pol = load_policies(spec, strategy)
    unit = float(metrics["metrics"]["unit_size"])

    seats = []
    for s in br_breakdown(pol.game, pol.estimated, pol.equilibrium, metrics["equilibrium"]["values"]):
        reported_gain = metrics["metrics"]["br_gain_norm"][s.subject_seat]
        if abs(s.gain / unit - reported_gain) > 1e-6:
            raise ValueError(
                f"{run_dir.name}: breakdown gain {s.gain / unit} does not match metrics.json {reported_gain}"
            )
        responder = []
        for r in sorted(s.responder, key=lambda r: -r.contribution):
            lab = pol.labels[r.key]
            responder.append(
                {
                    "infostate": r.key,
                    "player": r.player,
                    "short": spec.short_label(pol.infostates[r.key].state),
                    "situation": pol.rows[r.key]["situation"],
                    "reach": r.reach,
                    "best_response": lab[r.best_response],
                    "equilibrium": {lab[a]: p for a, p in r.equilibrium.items()},
                    "values": {lab[a]: _finite(v / unit) for a, v in r.values.items()},
                    "eq_mix_value": _finite(r.eq_mix_value / unit),
                    "edge": _finite(r.edge / unit),
                    "contribution": r.contribution / unit,
                    "share": r.contribution / s.gain if s.gain > 1e-9 else None,
                    "example_history": r.example_history,
                }
            )
        subject = []
        for r in sorted(s.subject, key=lambda r: (-r.reach * r.distance, r.key)):
            lab = pol.labels[r.key]
            row = pol.rows[r.key]
            subject.append(
                {
                    "infostate": r.key,
                    "player": r.player,
                    "short": spec.short_label(pol.infostates[r.key].state),
                    "situation": row["situation"],
                    "reach": r.reach,
                    "estimated": row["estimated"],
                    "equilibrium": row["equilibrium"],
                    "distance": r.distance,
                    "weighted_distance": r.reach * r.distance,
                    "support": row["support"],
                    "filled": row["filled"],
                }
            )
        seats.append(
            {
                "subject_seat": s.subject_seat,
                "responder_seat": s.responder_seat,
                "gain": s.gain / unit,
                "passive": s.passive / unit,
                "active": s.active / unit,
                "br_value": s.br_value / unit,
                "eq_value": s.eq_value / unit,
                "game_value": s.game_value / unit,
                "responder": responder,
                "subject": subject,
            }
        )
    _write_json(
        out,
        {
            "version": DERIVED_VERSION,
            "derived_from": inputs,
            "game": spec.name,
            "payoff_unit": metrics["payoff_unit"],
            "unit_size": unit,
            "seats": seats,
        },
    )
    return out, True


def _draw(rng: np.random.Generator, probs: dict[int, float]) -> int:
    actions = list(probs)
    p = np.array([probs[a] for a in actions], dtype=float)
    return int(actions[rng.choice(len(actions), p=p / p.sum())])


def _argmax(probs: dict[int, float]) -> int:
    return max(probs, key=lambda a: probs[a])  # ties: first legal action


def _reply_summaries(path: Path) -> dict[str, dict[str, Any]]:
    """Per infostate: direct-mode attempts, failures and a few failed raw replies."""
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"attempts": 0, "failures": 0, "examples": []})
    if not path.is_file():
        return {}
    with open(path) as fh:
        for line in fh:
            r = json.loads(line)
            s = out[r["infostate"]]
            s["attempts"] += 1
            if r["status"] != "ok":
                s["failures"] += 1
                if len(s["examples"]) < FAILURE_EXAMPLES:
                    raw = r["raw_output"] if "raw_output" in r else json.dumps(r.get("distribution"))
                    s["examples"].append({"raw": (raw or "")[:_MAX_REPLY_CHARS], "status": r["status"]})
    return dict(out)


def _play_attempts(path: Path, hands: set[int]) -> dict[str, list[dict[str, str]]]:
    """Play-mode attempts for the given hands, keyed by sample index, in attempt order."""
    found: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
    if path.is_file():
        with open(path) as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("hand") in hands:
                    found[str(r["sample_index"])].append(
                        (
                            r["attempt"],
                            {"raw": (r["raw_output"] or "")[:_MAX_REPLY_CHARS], "status": r["status"]},
                        )
                    )
    return {k: [a for _, a in sorted(v, key=lambda t: t[0])] for k, v in found.items()}


class _ReplayBuilder:
    def __init__(self, spec: GameSpec, pol: RunPolicies, breakdown: dict[str, Any], kind: str) -> None:
        self.spec, self.pol, self.kind = spec, pol, kind
        self.unit = breakdown["unit_size"]
        self.unit_name = breakdown["payoff_unit"]
        self.responder: dict[str, tuple[int, dict[str, Any]]] = {}
        for block in breakdown["seats"]:
            for row in block["responder"]:
                self.responder[row["infostate"]] = (block["subject_seat"], row)
        self.entries: dict[str, dict[str, Any]] = {}
        self.replies: dict[str, dict[str, Any]] = {}

    def entry(self, key: str) -> None:
        if key in self.entries:
            return
        row, labels = self.pol.rows[key], self.pol.labels[key]
        e: dict[str, Any] = {
            "player": row["player"],
            "short": self.spec.short_label(self.pol.infostates[key].state),
            "situation": row["situation"],
            "labels": [labels[a] for a in sorted(labels)],
            "estimated": row["estimated"],
            "equilibrium": row["equilibrium"],
            "support": row["support"],
            "filled": row["filled"],
        }
        e["text"] = {
            "estimated": {lab: render(p, "pct0") for lab, p in row["estimated"].items()},
            "equilibrium": {lab: render(p, "pct0") for lab, p in row["equilibrium"].items()},
        }
        e["subject_note"] = subject_sentence(Source(None, e, plain=True), "", self.kind).unescape()
        if key in self.replies:
            e["replies"] = self.replies[key]
        if key in self.responder:
            subject_seat, r = self.responder[key]
            fields = ("reach", "best_response", "values", "eq_mix_value", "edge", "contribution", "share")
            e["responder"] = {f: r[f] for f in fields}
            e["responder"]["text"] = {
                "values": {lab: render(v, "sf3") for lab, v in r["values"].items()},
                "eq_mix_value": render(r["eq_mix_value"], "sf3"),
                "reach": render(r["reach"], "pct1"),
                "contribution": render(r["contribution"], "f3"),
                "share": render(r["share"], "pct0"),
            }
            e["responder_note"] = responder_sentence(
                Source(None, e["responder"], plain=True), "", subject_seat, self.unit_name
            ).unescape()
        self.entries[key] = e

    def hand(
        self,
        actions: list[int],
        subject_seat: int,
        attempts: list[list[dict[str, str]]] | None = None,
        fallbacks: list[bool] | None = None,
    ) -> dict[str, Any]:
        state = self.pol.game.new_initial_state()
        steps, n = [], 0
        for action in actions:
            if state.is_chance_node():
                steps.append({"kind": "chance", "text": self.spec.describe_chance(state, action)})
            else:
                key, player = state.information_state_string(), state.current_player()
                self.entry(key)
                step = {
                    "kind": "decision",
                    "player": player,
                    "role": "subject" if player == subject_seat else "opponent",
                    "infostate": key,
                    "action": self.pol.labels[key][action],
                }
                if player == subject_seat:
                    if attempts is not None:
                        step["attempts"] = attempts[n] if n < len(attempts) else []
                    if fallbacks is not None:
                        step["fallback"] = fallbacks[n]
                    n += 1
                steps.append(step)
            state.apply_action(action)
        if not state.is_terminal():
            raise ValueError("replay history does not reach a terminal state")
        payoff = state.returns()[subject_seat] / self.unit
        return {
            "subject_seat": subject_seat,
            "subject_payoff": payoff,
            "payoff_text": render(payoff, "sf3"),
            "steps": steps,
        }

    def key_actions(self, row: dict[str, Any], subject_seat: int) -> list[int]:
        """Most likely history into ``row``'s infostate, then best response / most likely play."""
        state = self.pol.game.new_initial_state()
        actions = list(row["example_history"])
        for a in actions:
            state.apply_action(a)
        while not state.is_terminal():
            if state.is_chance_node():
                a = _argmax(dict(state.chance_outcomes()))
            elif state.current_player() == subject_seat:
                a = _argmax(self.pol.estimated.action_probabilities(state))
            else:
                key = state.information_state_string()
                best = self.responder[key][1]["best_response"]
                a = next(x for x, lab in self.pol.labels[key].items() if lab == best)
            state.apply_action(a)
            actions.append(a)
        return actions


def write_replay(
    run_dir: Path, spec: GameSpec, n_hands: int = REPLAY_HANDS, force: bool = False
) -> tuple[Path, bool]:
    """Write ``replay.json`` unless it is current. Needs ``breakdown.json``."""
    out = run_dir / "replay.json"
    names = [
        "strategy.json",
        "metrics.json",
        "manifest.json",
        "breakdown.json",
        "calls.jsonl",
        "play.json",
        "hands.jsonl",
        "play_calls.jsonl",
    ]
    inputs = _inputs(run_dir, names)
    params = {"hands": n_hands, "key_situations": KEY_SITUATIONS}
    if not force and _is_current(out, inputs, params):
        return out, False

    metrics = json.loads((run_dir / "metrics.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    breakdown = json.loads((run_dir / "breakdown.json").read_text())
    pol = load_policies(spec, json.loads((run_dir / "strategy.json").read_text()))
    b = _ReplayBuilder(spec, pol, breakdown, metrics["subject_kind"])
    b.replies = _reply_summaries(run_dir / "calls.jsonl")

    hands: list[dict[str, Any]] = []
    for block in breakdown["seats"]:
        seat = block["subject_seat"]
        top = [r for r in block["responder"] if r["contribution"] >= MIN_CONTRIBUTION][:KEY_SITUATIONS]
        for rank, row in enumerate(top, start=1):
            h = b.hand(b.key_actions(row, seat), seat)
            h.update(
                id=f"key-p{seat + 1}-{rank}",
                group="key",
                title=f"Biggest gain {rank} against the subject as Player {seat + 1}",
                focus=row["infostate"],
            )
            hands.append(h)

    play_path, hands_path = run_dir / "play.json", run_dir / "hands.jsonl"
    if play_path.is_file() and hands_path.is_file():
        play = json.loads(play_path.read_text())["play"]
        source, opponent, total = "played", play["opponent"], play["n_hands"]
        with open(hands_path) as fh:
            logged = sorted((json.loads(line) for line in fh), key=lambda h: h["hand"])[:n_hands]
        attempts = _play_attempts(run_dir / "play_calls.jsonl", {h["hand"] for h in logged})
        for rec in logged:
            hand_no, seat = rec["hand"], rec["subject_seat"]
            actions = [e["chance"] if "chance" in e else e["action"] for e in rec["events"]]
            subject_events = [e for e in rec["events"] if e.get("subject")]
            h = b.hand(
                actions,
                seat,
                attempts=[
                    attempts.get(f"play:{play['seed']}:{hand_no}:{n}", []) for n in range(len(subject_events))
                ],
                fallbacks=[bool(e["fallback"]) for e in subject_events],
            )
            if abs(h["subject_payoff"] - rec["subject_payoff"] / b.unit) > 1e-9:
                raise ValueError(f"{run_dir.name}: hand {hand_no} payoff does not match hands.jsonl")
            h.update(id=f"hand-{hand_no + 1}", group=source, title=f"Hand {hand_no + 1}")
            hands.append(h)
    else:
        source, opponent, total = "simulated", "equilibrium", n_hands
        seed = manifest["config"]["seed"]
        for i in range(n_hands):
            rng = np.random.default_rng([seed, i])
            seat, state, actions = i % 2, pol.game.new_initial_state(), []
            while not state.is_terminal():
                if state.is_chance_node():
                    probs = dict(state.chance_outcomes())
                elif state.current_player() == seat:
                    probs = pol.estimated.action_probabilities(state)
                else:
                    probs = pol.equilibrium.action_probabilities(state)
                a = _draw(rng, probs)
                state.apply_action(a)
                actions.append(a)
            h = b.hand(actions, seat)
            h.update(id=f"sim-{i + 1}", group=source, title=f"Simulated hand {i + 1}")
            hands.append(h)

    _write_json(
        out,
        {
            "version": DERIVED_VERSION,
            "derived_from": inputs,
            "params": params,
            "game": spec.name,
            "payoff_unit": breakdown["payoff_unit"],
            "subject_kind": metrics["subject_kind"],
            "source": source,
            "opponent": opponent,
            "hands_total": total,
            "infostates": b.entries,
            "hands": hands,
        },
    )
    return out, True


def derive(
    run_dir: str | Path, spec: GameSpec, n_hands: int = REPLAY_HANDS, force: bool = False
) -> list[str]:
    """Bring a run's derived files up to date. Returns the names of the files written."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if manifest.get("openspiel_game") != spec.load_string:
        raise ValueError(
            f"{run_dir.name} was run on {manifest.get('openspiel_game')!r}, "
            f"but the {spec.name} spec now loads {spec.load_string!r}"
        )
    written = []
    path, changed = write_breakdown(run_dir, spec, force)
    if changed:
        written.append(path.name)
    path, changed = write_replay(run_dir, spec, n_hands, force)
    if changed:
        written.append(path.name)
    return written
