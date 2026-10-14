"""Write the result tables and quoted numbers into docs/research/multiway.md from results/*.json.

Each table sits between `<!-- BEGIN table:NAME -->` and `<!-- END table:NAME -->` markers in
the doc, and each number quoted in the prose sits between `<!--v:NAME-->` and `<!--/v-->`.
Both are regenerated in place, so no experimental number in the doc is typed by hand. Where a
sentence makes a claim the numbers alone do not show (for example "CFR+ splits between two
sub-families"), a check below fails if the results stop supporting it.

    uv run python research/multiway/make_tables.py
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
RESULTS = HERE / "results"
DOC = HERE.parent.parent / "docs" / "research" / "multiway.md"
KAPPA = 1 / 24
#: A run counts as converged when every player's gain is at most this (chips; 0.01 mA).
CONVERGED = 1e-5
#: Off-path constraint violation above which a run counts as leaving the family off the path.
OFF_PATH_FLAG = 1e-3
#: Seat values of Gambit's logit QRE solution as reported by Ganzfried (arXiv:2509.25618, Sec. 4).
LOGIT_QRE_VALUES = (-0.0276, -0.0208, 0.0484)
SIMPLE = "OpenSpiel ES-MCCFR (simple averaging)"
FULL = "OpenSpiel ES-MCCFR (full averaging)"
SUBFAMILY_NAME = {"c11=0": "c11 = 0", "0<c11<1/2": "0 < c11 < ½", "c11=1/2": "c11 = ½"}
CARD = "JQKA"
SITUATION = {
    "a": {1: "opening", 2: "check, check, bet", 3: "check, bet, fold", 4: "check, bet, call"},
    "b": {
        1: "after a check",
        2: "facing an opening bet",
        3: "check, check, bet, fold",
        4: "check, check, bet, call",
    },
    "c": {1: "after check, check", 2: "check, bet", 3: "bet, fold", 4: "bet, call"},
}


def load(name):
    return json.loads((RESULTS / name).read_text())


def ma(x, digits=2):
    """Chips (= antes) per hand to milli-antes per hand."""
    return f"{1000 * x:.{digits}f}".replace("-0.00", "0.00")


def gain(x):
    v = 1000 * x
    if abs(v) < 5e-11:
        return "0"
    return f"{v:.1e}" if abs(v) < 0.01 else f"{v:.2f}"


def span(values, digits=2):
    lo, hi = min(values), max(values)
    return ma(lo, digits) if abs(hi - lo) < 0.5e-3 * 10**-digits else f"{ma(lo, digits)} to {ma(hi, digits)}"


def describe(param):
    player = {"a": "P1", "b": "P2", "c": "P3"}[param[0]]
    return f"{player}, {CARD[int(param[1]) - 1]}, {SITUATION[param[0]][int(param[2])]}"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def minus(text):
    """Typographic minus sign for numbers quoted in prose."""
    return text.replace("-", "−")


def power(n):
    """10**6 -> 10⁶ and 3 * 10**5 -> 3·10⁵, as the doc writes iteration counts."""
    exp = len(str(n)) - 1
    lead = n // 10**exp
    assert lead * 10**exp == n, n
    return (
        ("" if lead == 1 else f"{lead}·")
        + "10"
        + str(exp).translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"))
    )


def two_figures(x):
    """Round to two significant figures for an 'about N times' statement."""
    return f"{round(x, 1 - math.floor(math.log10(abs(x)))):,.0f}"


def check(condition, claim):
    """Stop if the results no longer support a sentence in the doc."""
    if not condition:
        raise SystemExit(f"the results no longer support this claim in the doc: {claim}")


def group_of(run):
    return run["label"].split(",")[0]


def solver_tables(sol):
    runs = sol["runs"]
    groups = defaultdict(list)
    for r in runs:
        groups[group_of(r)].append(r)
    rows = []
    for g, rs in groups.items():
        f = [r["final"] for r in rs]
        mg = [x["max_gain"] for x in f]
        subs = defaultdict(int)
        for x in f:
            subs[x["closest_subfamily"]] += 1
        rows.append(
            [
                g,
                len(rs),
                f"{rs[0]['iterations']:,}",
                gain(float(np.median(mg))),
                gain(max(mg)),
                span([x["ev"][0] for x in f]),
                span([x["ev"][1] for x in f]),
                span([x["ev"][2] for x in f]),
                " to ".join(dict.fromkeys(f"{fn(x['beta'] for x in f):.3f}" for fn in (min, max))),
                " / ".join(str(subs[s]) for s in ("c11=0", "0<c11<1/2", "c11=1/2")),
            ]
        )
    summary = table(
        [
            "Solver",
            "Runs",
            "Iterations",
            "Largest gain, median run (mA)",
            "Largest gain, worst run (mA)",
            "P1 value (mA)",
            "P2 value (mA)",
            "P3 value (mA)",
            "β = max(b11, b21)",
            "Closest sub-family: c11=0 / 0<c11<½ / c11=½",
        ],
        rows,
    )

    # Spread of seat values among runs whose every gain is small.
    fam_lo, fam_hi = -KAPPA * 0.75, -KAPPA * 0.5
    spread_rows = []
    for thr in (1e-3, 1e-4, 1e-5):
        ok = [r for r in runs if r["final"]["max_gain"] <= thr]
        ev = np.array([r["final"]["ev"] for r in ok])
        spread_rows.append(
            [
                f"every gain ≤ {gain(thr)} mA",
                len(ok),
                ", ".join(sorted({group_of(r) for r in ok})),
                span(ev[:, 0]),
                span(ev[:, 1]),
                span(ev[:, 2]),
                ma(ev[:, 0].max() - ev[:, 0].min()),
            ]
        )
    spread_rows.append(
        [
            "analytic family (all members)",
            "∞",
            "Szafron et al. 2013, Table 3",
            f"{ma(fam_lo)} to {ma(fam_hi)}",
            ma(-KAPPA * 0.5),
            f"{ma(KAPPA)} to {ma(KAPPA * 1.25)}",
            ma(fam_hi - fam_lo),
        ]
    )
    spread = table(
        [
            "Runs kept",
            "Count",
            "Solvers",
            "P1 value (mA)",
            "P2 value (mA)",
            "P3 value (mA)",
            "P1 spread (mA)",
        ],
        spread_rows,
    )

    # Convergence: median largest gain at checkpoints, full-width solvers.
    marks = (100, 1000, 10000, 20000)
    conv_rows = []
    for g, rs in groups.items():
        if "MCCFR" in g:
            continue
        cells = []
        for m in marks:
            vals = [max(c["gains"]) for r in rs for c in r["checkpoints"] if c["iteration"] == m]
            cells.append(gain(float(np.median(vals))) if vals else "")
        conv_rows.append([g, rs[0]["updates"], *cells])
    conv = table(["Solver", "Updates", *[f"after {m:,} (mA)" for m in marks]], conv_rows)

    mccfr_rows = []
    for g, rs in groups.items():
        if "MCCFR" not in g:
            continue
        cells = []
        for m in (10**4, 10**5, 3 * 10**5, 10**6):
            vals = [max(c["gains"]) for r in rs for c in r["checkpoints"] if c["iteration"] == m]
            cells.append(
                f"{gain(float(np.median(vals)))} ({gain(min(vals))} to {gain(max(vals))})"
                if vals
                else "not run"
            )
        mccfr_rows.append([g, len(rs), *cells])
    mccfr = table(
        ["Solver", "Seeds", "after 10⁴: median (range), mA", "after 10⁵", "after 3·10⁵", "after 10⁶"],
        mccfr_rows,
    )

    # CCE gap versus Nash gap for simultaneous-update CFR.
    cce_rows = []
    for r in runs:
        if not r["label"].startswith("CFR simultaneous"):
            continue
        for c in r["checkpoints"]:
            if r["init"] != "uniform" and c["iteration"] != r["iterations"]:
                continue
            if c["iteration"] < 100:
                continue
            cce_rows.append(
                [
                    r["init"],
                    f"{c['iteration']:,}",
                    gain(max(c["gains"])),
                    gain(max(c["cce_gap"])),
                    ma(c["ev"][0]),
                    ma(c["cce_ev"][0]),
                    ma(c["ev"][1]),
                    ma(c["cce_ev"][1]),
                ]
            )
    cce = table(
        [
            "Start",
            "Iterations",
            "Largest gain of average profile (mA)",
            "Largest CCE gap (mA)",
            "P1 value, average profile",
            "P1 value, CCE",
            "P2 value, average profile",
            "P2 value, CCE",
        ],
        cce_rows,
    )

    per_run = table(
        [
            "Run",
            "Largest gain (mA)",
            "P1 (mA)",
            "P2 (mA)",
            "P3 (mA)",
            "β",
            "Closest sub-family",
            "On-path violation",
            "Off-path violation",
        ],
        [
            [
                r["label"],
                gain(r["final"]["max_gain"]),
                ma(r["final"]["ev"][0]),
                ma(r["final"]["ev"][1]),
                ma(r["final"]["ev"][2]),
                f"{r['final']['beta']:.3f}",
                r["final"]["closest_subfamily"],
                f"{r['final']['on_path_violation']:.1e}",
                f"{r['final']['off_path_violation']:.1e}",
            ]
            for r in runs
        ],
    )
    return {
        "solver-summary": summary,
        "ev-spread": spread,
        "convergence": conv,
        "mccfr": mccfr,
        "cce": cce,
        "per-run": per_run,
    }


def offpath_totals(fam):
    """Per unreached parameter, over all sampled members: how often it was unreached, how often
    pushing it to 0 or 1 broke the equilibrium, and the largest gain that created."""
    agg = defaultdict(lambda: {"unreached": 0, "breaks": 0, "max_gain": 0.0})
    for off in fam["off_path"].values():
        for name, v in off.items():
            a = agg[name]
            a["unreached"] += v["unreached"]
            a["breaks"] += v["breaks"]
            a["max_gain"] = max(a["max_gain"], v["max_gain"])
    return agg


def family_tables(fam):
    rows = []
    for sub, v in fam["subfamilies"].items():
        rows.append(
            [
                sub,
                fam["members_per_subfamily"],
                gain(v["max_gain"]),
                f"{1000 * v['max_ev_minus_formula']:.0e}",
                f"{ma(v['ev_min'][0])} to {ma(v['ev_max'][0])}",
                ma(v["ev_min"][1]),
                f"{ma(v['ev_min'][2])} to {ma(v['ev_max'][2])}",
                "" if v["prose_b33_max_gain"] is None else gain(v["prose_b33_max_gain"]),
            ]
        )
    members = table(
        [
            "Sub-family",
            "Random members",
            "Largest gain (mA)",
            "Largest gap between value and formula (mA)",
            "P1 value (mA)",
            "P2 value (mA)",
            "P3 value (mA)",
            "Largest gain with the prose b33 formula (mA)",
        ],
        rows,
    )

    agg = offpath_totals(fam)
    total = fam["members_per_subfamily"] * len(fam["off_path"])
    breaks = table(
        [
            "Parameter",
            "Infostate",
            "Unreached in",
            "Pushing to 0 or 1 breaks equilibrium",
            "Largest gain created (mA)",
        ],
        [
            [
                n,
                describe(n),
                f"{v['unreached']:,} of {total:,}",
                f"{100 * v['breaks'] / v['unreached']:.0f}%",
                gain(v["max_gain"]),
            ]
            for n, v in sorted(agg.items(), key=lambda kv: (-kv[1]["breaks"] / kv[1]["unreached"], kv[0]))
        ],
    )

    intervals = fam["offpath_intervals"]
    labels = list(intervals)
    names = sorted({n for rows in intervals.values() for n in rows})
    irows = []
    for n in names:
        cells = []
        for lab in labels:
            v = intervals[lab].get(n)
            if v is None:
                cells.append("reached")
            else:
                # The family's own value is an exact equilibrium and the allowed set is an
                # interval, so widen the grid's interval to include it (15/16 is off the grid).
                lo = min(v["allowed_min"], v["family_value"])
                hi = max(v["allowed_max"], v["family_value"])
                cells.append(f"{v['family_value']:.3g}: [{lo:.3g}, {hi:.3g}]")
        irows.append([n, describe(n), *cells])
    interval_table = table(["Parameter", "Infostate", *labels], irows)

    gz = fam["ganzfried_offpath_variants"]
    bases = []
    for r in gz:
        b = f"b32={r['base']['b32']:g}, c33={r['base']['c33']:g}"
        if b not in bases:
            bases.append(b)
    variants = []
    for r in gz:
        if r["variant"] not in variants:
            variants.append(r["variant"])
    cell = {}
    for r in gz:
        b = f"b32={r['base']['b32']:g}, c33={r['base']['c33']:g}"
        g = r["gains"]
        i = int(np.argmax(g))
        cell[(r["variant"], b)] = "0 (equilibrium)" if max(g) < 1e-12 else f"P{i + 1} gains {gain(g[i])}"
    ganz = table(
        ["Change to the β = 0 member", *[f"base {b}" for b in bases]],
        [[v, *[cell[(v, b)] for b in bases]] for v in variants],
    )
    return {
        "family-members": members,
        "offpath-breaks": breaks,
        "offpath-intervals": interval_table,
        "ganzfried": ganz,
    }


def seat_tables(seat):
    def rows_for(prefix):
        out = []
        for r in seat["rows"]:
            if not r["subject"].startswith(prefix):
                continue
            out.append(
                [
                    r["seat"],
                    r["reference"],
                    ma(r["subject_ev"]),
                    ma(r["reference_ev"]),
                    ma(r["loss_vs_reference"]),
                    ma(r["seat_regret"]),
                    f"{ma(r['max_opponent_gain'])} ({r['max_gain_opponent']})",
                    f"{ma(r['paid_by_subject'])} / {ma(r['paid_by_bystander'])}",
                    ma(r["max_punishment_loss"]),
                ]
            )
        return out

    header = [
        "Seat",
        "Other seats play",
        "Subject value (mA)",
        "Reference value in that seat (mA)",
        "Loss vs reference (mA)",
        "Seat regret (mA)",
        "Largest opponent gain (mA, who)",
        "Paid by subject / bystander (mA)",
        "Largest punishment loss (mA)",
    ]
    refs = table(
        ["Reference profile", "Largest gain (mA)", "P1 (mA)", "P2 (mA)", "P3 (mA)"],
        [[n, gain(max(v["gains"])), *[ma(x) for x in v["ev"]]] for n, v in seat["references"].items()],
    )
    self_play = table(
        ["Subject in every seat", "P1 gain (mA)", "P2 gain (mA)", "P3 gain (mA)"],
        [[n, *[ma(g) for g in v["gains"]]] for n, v in seat["self_play"].items()],
    )
    return {
        "seat-references": refs,
        "seat-uniform": table(header, rows_for("uniform")),
        "seat-mismatch": table(header, rows_for("equilibrium strategy")),
        "seat-selfplay": self_play,
    }


def leduc_table(led):
    rows = []
    for r in led["runs"]:
        for c in r["checkpoints"]:
            rows.append(
                [
                    r["label"],
                    f"{c['iteration']:,}",
                    f"{c['train_seconds_so_far']:.0f}",
                    " / ".join(ma(g, 0) for g in c["gains"]),
                    " / ".join(ma(e, 0) for e in c["ev"]),
                ]
            )
    return {
        "leduc": table(
            ["Run", "Iterations", "Training time (s)", "Gains P1 / P2 / P3 (mA)", "Values P1 / P2 / P3 (mA)"],
            rows,
        )
    }


def solver_values(meta, runs):
    """Numbers quoted in the prose about the three-player Kuhn solver runs."""
    groups = defaultdict(list)
    for r in runs:
        groups[group_of(r)].append(r)

    def final(g):
        return [r["final"] for r in groups[g]]

    def beta_range(g):
        betas = [x["beta"] for x in final(g)]
        return f"{min(betas):.3f}", f"{max(betas):.3f}"

    v = {
        "kuhn_infosets": str(meta["num_infosets"]),
        "kuhn_nodes": str(meta["num_nodes"]),
        "openspiel_version": meta["openspiel_version"],
    }
    per_player = meta["infosets_per_player"]
    check(len(set(per_player)) == 1, "every player has the same number of infostates")
    v["kuhn_infosets_per_player"] = str(per_player[0])

    # Set-up.
    full_width = ["CFR", "CFR+", "Linear CFR", "CFR simultaneous", "Fictitious play"]
    iterations = {
        r["iterations"] for g in full_width + ["OpenSpiel CFR", "OpenSpiel CFR+"] for r in groups[g]
    }
    check(len(iterations) == 1, "all full-width runs use the same number of iterations")
    v["kuhn_iterations"] = f"{iterations.pop():,}"
    starts = {g: sum(r["init"] != "uniform" for r in groups[g]) for g in full_width}
    check(
        len({starts[g] for g in ("CFR", "CFR+", "Linear CFR", "Fictitious play")}) == 1, "same random starts"
    )
    v["random_starts"] = str(starts["CFR"])
    v["sim_random_starts"] = str(starts["CFR simultaneous"])
    simple, full = groups[SIMPLE], groups[FULL]
    v["mccfr_simple_seeds"], v["mccfr_simple_iters"] = str(len(simple)), power(simple[0]["iterations"])
    v["mccfr_full_seeds"], v["mccfr_full_iters"] = str(len(full)), power(full[0]["iterations"])

    def seconds_per_iteration(rs):
        return sum(r["seconds"] for r in rs) / sum(r["iterations"] for r in rs)

    v["mccfr_full_slowdown"] = f"{seconds_per_iteration(full) / seconds_per_iteration(simple):.0f}"

    # Converged runs and the spread of their seat values.
    conv = [r["final"] for r in runs if r["final"]["max_gain"] <= CONVERGED]
    ev = np.array([x["ev"] for x in conv])
    spread = ev[:, 0].max() - ev[:, 0].min()
    v["conv_count"] = str(len(conv))
    v["conv_threshold"] = f"{1000 * CONVERGED:g}"
    v["conv_p1_min"], v["conv_p1_max"] = minus(ma(ev[:, 0].min())), minus(ma(ev[:, 0].max()))
    v["conv_p1_spread"] = ma(spread)
    v["conv_spread_pct"] = f"{100 * spread / (KAPPA / 4):.0f}"
    v["conv_ratio"] = two_figures(spread / max(x["max_gain"] for x in conv))
    v["conv_p2_dev"] = f"{1000 * np.abs(ev[:, 1] + KAPPA / 2).max():.3f}"

    # Alternating against simultaneous updates.
    alternating = [x["max_gain"] for g in ("CFR", "CFR+", "Linear CFR") for x in final(g)]
    v["alt_worst_gain"] = gain(max(alternating))
    for key, g in (
        ("cfr_alt_median", "CFR"),
        ("sim_median", "CFR simultaneous"),
        ("fp_median", "Fictitious play"),
    ):
        v[key] = gain(float(np.median([x["max_gain"] for x in final(g)])))
    check(
        max(np.median([x["max_gain"] for x in final(g)]) for g in ("CFR", "CFR+", "Linear CFR"))
        < min(np.median([x["max_gain"] for x in final(g)]) for g in ("CFR simultaneous", "Fictitious play")),
        "simultaneous updates converge more slowly than alternating ones",
    )

    # CCE gap against the deployed average profile (simultaneous-update CFR).
    sim = groups["CFR simultaneous"]
    uniform = next(r for r in sim if r["init"] == "uniform")
    last = uniform["checkpoints"][-1]
    v["sim_avg_gain"], v["sim_cce_gap"] = gain(max(last["gains"])), gain(max(last["cce_gap"]))
    ratios = [max(r["checkpoints"][-1]["gains"]) / max(r["checkpoints"][-1]["cce_gap"]) for r in sim]
    v["sim_ratio_lo"], v["sim_ratio_hi"] = f"{min(ratios):.1f}", f"{max(ratios):.1f}"

    def value_gap(c):
        return 1000 * max(abs(a - b) for a, b in zip(c["ev"], c["cce_ev"], strict=True))

    v["cce_value_gap_max"] = (
        f"{max(value_gap(c) for c in uniform['checkpoints'] if c['iteration'] >= 100):.1f}"
    )
    v["cce_value_gap_final"] = f"{max(value_gap(r['checkpoints'][-1]) for r in sim):.2f}"

    # Which equilibria the runs select.
    cfr = final("CFR")
    check(
        all(x["closest_subfamily"] == "c11=0" for x in cfr),
        "every CFR run is closest to the c11 = 0 sub-family",
    )
    v["cfr_n"] = str(len(cfr))
    v["cfr_b11_max"] = f"{max(x['params']['b11'] for x in cfr):.3f}"
    v["cfr_beta_lo"], v["cfr_beta_hi"] = beta_range("CFR")
    plus = final("CFR+")
    split = Counter(x["closest_subfamily"] for x in plus).most_common()
    check(len(split) == 2, "CFR+ runs split between two sub-families")
    (first, n_first), (second, n_second) = split
    v["cfrplus_split"] = (
        f"{n_first} of the {len(plus)} starts ended closest to the {SUBFAMILY_NAME[first]} sub-family "
        f"and {n_second} closest to {SUBFAMILY_NAME[second]}"
    )
    v["cfrplus_beta_lo"], v["cfrplus_beta_hi"] = beta_range("CFR+")
    linear_random = [r["final"]["beta"] for r in groups["Linear CFR"] if r["init"] != "uniform"]
    v["linear_beta_lo"], v["linear_beta_hi"] = f"{min(linear_random):.3f}", f"{max(linear_random):.3f}"
    v["linear_high"] = f"{sum(b > 0.2 for b in linear_random)} of {len(linear_random)}"
    check(
        sum(b > 0.2 for b in linear_random) > len(linear_random) / 2,
        "linear CFR mostly ends with beta above 0.2",
    )
    v["linear_beta_uniform"] = (
        f"{next(r['final']['beta'] for r in groups['Linear CFR'] if r['init'] == 'uniform'):.3f}"
    )
    betas = [r["final"]["beta"] for r in runs]
    v["beta_min"], v["beta_max"] = f"{min(betas):.3f}", f"{max(betas):.3f}"
    for key in ("cfr", "cfrplus", "linear"):
        g = {"cfr": "CFR", "cfrplus": "CFR+", "linear": "Linear CFR"}[key]
        v[f"onpath_{key}"] = f"{np.median([x['on_path_violation'] for x in final(g)]):.1e}"
    # Ganzfried's logit QRE values put it in the family at beta = -u1/kappa - 1/2 = u3/kappa - 1.
    qre_p1, qre_p3 = -LOGIT_QRE_VALUES[0] / KAPPA - 0.5, LOGIT_QRE_VALUES[2] / KAPPA - 1
    check(abs(qre_p1 - qre_p3) < 0.01, "player 1's and player 3's logit values give the same beta")
    qre_beta = (qre_p1 + qre_p3) / 2
    cfr_family = [
        x["beta"] for g in ("CFR", "CFR+", "Linear CFR", "OpenSpiel CFR", "OpenSpiel CFR+") for x in final(g)
    ]
    check(
        min(cfr_family) <= qre_beta <= max(cfr_family),
        "the logit solution's beta is inside the CFR runs' range",
    )
    v["qre_beta"] = f"{qre_beta:.2f}"

    # CFR+ runs that leave the family off the path of play.
    flagged = [x for x in plus if x["off_path_violation"] >= OFF_PATH_FLAG]
    check(0 < len(flagged) < len(plus), "some, not all, CFR+ runs leave the family off the path")
    v["cfrplus_offpath_runs"] = f"{len(flagged)} of the {len(plus)}"
    v["cfrplus_worst_gain"] = gain(max(x["max_gain"] for x in flagged))
    v["cfrplus_b22_max"] = f"{100 * max(x['params']['b22'] for x in flagged):.1f}%"
    v["cfrplus_c23_max"] = f"{100 * max(x['params']['c23'] for x in flagged):.1f}%"

    # External-sampling MCCFR and its two averaging modes.
    top, mid = simple[0]["iterations"], full[0]["iterations"]

    def gains_at(rs, iteration):
        return [max(c["gains"]) for r in rs for c in r["checkpoints"] if c["iteration"] == iteration]

    at_top, at_mid = gains_at(simple, top), gains_at(simple, mid)
    v["mccfr_simple_1e6"] = gain(float(np.median(at_top)))
    v["mccfr_simple_lo"], v["mccfr_simple_hi"] = gain(min(at_top)), gain(max(at_top))
    v["mccfr_simple_mid"] = gain(float(np.median(at_mid)))
    v["mccfr_worse"] = str(sum(t > m for t, m in zip(at_top, at_mid, strict=True)))
    v["mccfr_worse_40"] = str(sum(t > 0.04 for t in at_top))
    check(
        sum(t > m for t, m in zip(at_top, at_mid, strict=True)) > 0, "some simple-averaging seeds get worse"
    )
    full_mid = gains_at(full, mid)
    v["mccfr_full_mid"] = gain(float(np.median(full_mid)))
    v["mccfr_full_lo"], v["mccfr_full_hi"] = gain(min(full_mid)), gain(max(full_mid))
    check(max(alternating) < min(at_top + full_mid), "every alternating CFR run beats the best MCCFR seed")
    return v


def family_values(fam):
    """Numbers quoted in the prose about the analytic family and its unreached infostates."""
    subs = fam["subfamilies"].values()
    largest = max(s["max_gain"] for s in subs)
    v = {
        "fam_members": f"{fam['members_per_subfamily'] * len(fam['subfamilies']):,}",
        "fam_max_gain": "0" if largest == 0 else f"{largest:.0e}",
        "fam_prose_gain": ma(max(s["prose_b33_max_gain"] or 0.0 for s in subs)),
    }
    check(largest < 1e-12, "every sampled member is an exact equilibrium")
    check(
        max(s["max_ev_minus_formula"] for s in subs) < 1e-12, "every member's seat values match the formula"
    )

    totals = offpath_totals(fam)
    always = {n for n, a in totals.items() if a["breaks"] == a["unreached"]}
    some = {n for n, a in totals.items() if 0 < a["breaks"] < a["unreached"]}
    v["offpath_total"] = str(len(totals))
    v["offpath_always"] = str(len(always))
    v["offpath_some"] = str(len(some))
    v["offpath_never"] = str(len(totals) - len(always) - len(some))
    # Responses to an opening bet: player 2 facing it, player 3 after bet-fold or bet-call.
    opening = {n for n in always if (n[0] == "b" and n[2] == "2") or (n[0] == "c" and n[2] in "34")}
    v["offpath_opening"] = str(len(opening))
    check(
        {"b12", "b22", "b42", "c13", "c23", "c43"} <= always,
        "the responses named in Section 2.5 always matter",
    )

    intervals = fam["offpath_intervals"]
    check(
        all(r["contiguous"] for rows in intervals.values() for r in rows.values()),
        "allowed sets are intervals",
    )
    low = next(rows for label, rows in intervals.items() if label.startswith("c11=0, beta=0 "))
    high = next(rows for label, rows in intervals.items() if label.startswith("c11=0, beta=1/4"))
    pinned = sum(r["allowed_min"] == r["allowed_max"] for r in low.values())
    v["iv_pinned_b0"] = f"{pinned} of the {len(low)}"
    check(
        all(high[n]["allowed_max"] == 0 for n in ("b12", "b22", "c13", "c23")),
        "at beta = 1/4 J and Q calls pinned",
    )
    check(
        all(high[n]["allowed_min"] < high[n]["allowed_max"] for n in ("b32", "b42", "c43")),
        "b32, b42, c43 free",
    )

    variants = fam["ganzfried_offpath_variants"]

    def rows(prefix):
        return [r for r in variants if r["variant"].startswith(prefix)]

    check(
        all(max(r["gains"]) < 1e-12 for r in rows("a33=0, c32=1/2")),
        "Ganzfried's profile is an equilibrium (c32)",
    )
    described = rows("a33=0, c33=1/2")
    check(all(int(np.argmax(r["gains"])) == 1 for r in described), "under the c33 reading player 2 gains")
    check(
        all(max(r["gains"]) > 1e-9 for r in rows("a33=0 only") + rows("c32=1/2 only")),
        "each change alone breaks",
    )
    v["ganz_c33_gain"] = ma(max(max(r["gains"]) for r in described))
    return v


def seat_values(seat):
    """Numbers quoted in the prose about the per-seat metric demonstration."""

    def row(subject, seat_name, reference):
        return next(
            r
            for r in seat["rows"]
            if r["subject"].startswith(subject) and r["seat"] == seat_name and r["reference"] == reference
        )

    v = {}
    u0, u14 = row("uniform", "P1", "family beta=0"), row("uniform", "P1", "family beta=1/4")
    v["seat_u_p1_b0"], v["seat_u_p1_b14"] = ma(u0["loss_vs_reference"]), ma(u14["loss_vs_reference"])
    v["seat_u_ratio"] = f"{u14['loss_vs_reference'] / u0['loss_vs_reference']:.2f}"

    eq = [r for r in seat["rows"] if r["subject"].startswith("equilibrium strategy")]
    family = [r for r in eq if r["reference"].startswith("family")]
    seat1 = [r for r in family if r["seat"] == "P1"]
    check(
        all(abs(r["loss_vs_reference"]) < 1e-12 for r in seat1),
        "player 1 plays the same strategy in every member",
    )
    every_ref = [r for r in eq if r["seat"] == "P1"]
    check(
        all(r["max_opponent_gain"] < 5e-6 for r in every_ref)
        and any(abs(r["paid_by_subject"]) > 1e-3 for r in every_ref),
        "seat-1 mismatch rows show 0.00 gains with a non-zero tie-break split",
    )
    v["seat_eq_p1_punish"] = ma(max(r["max_punishment_loss"] for r in seat1))
    seat2 = [r["loss_vs_reference"] for r in family if r["seat"] == "P2"]
    check(
        all(abs(x - KAPPA / 4) < 1e-12 for x in seat2),
        "the seat-2 loss is the kappa-beta transfer at beta = 1/4",
    )
    v["seat_eq_p2_loss"] = ma(seat2[0])
    mix = max(eq, key=lambda r: r["opponent_gains"].get("P1", 0.0))
    check(
        mix["seat"] == "P2" and mix["reference"] == "family beta=1/4",
        "the largest P1 gain is seat 2 vs beta = 1/4",
    )
    check(
        mix["bystander"] == "P3" and mix["paid_by_bystander"] > mix["paid_by_subject"],
        "player 3 pays most of it",
    )
    v["seat_mix_p1_gain"] = ma(mix["opponent_gains"]["P1"])
    v["seat_mix_paid_subject"], v["seat_mix_paid_bystander"] = (
        ma(mix["paid_by_subject"]),
        ma(mix["paid_by_bystander"]),
    )
    return v


def leduc_values(led):
    """Numbers quoted in the prose about the time-boxed three-player Leduc runs."""
    runs = led["runs"]
    cfr_plus = next(r for r in runs if r["label"] == "OpenSpiel CFR+")
    last = cfr_plus["checkpoints"][-1]
    return {
        "leduc_seconds": f"{led['meta']['total_seconds']:.0f}",
        "leduc_best": ma(min(max(r["checkpoints"][-1]["gains"]) for r in runs), 0),
        "leduc_infosets": f"{cfr_plus['num_infosets']:,}",
        "leduc_eval_seconds": f"{np.median([c['eval_seconds'] for r in runs for c in r['checkpoints']]):.0f}",
        "leduc_cfrplus_iters": str(last["iteration"]),
        "leduc_cfrplus_s_per_it": f"{last['train_seconds_so_far'] / last['iteration']:.1f}",
    }


def main() -> None:
    tables = {}
    solvers = load("kuhn3_solvers.json")
    solvers["runs"] += load("kuhn3_mccfr.json")["runs"]
    family, seat, leduc = load("kuhn3_family.json"), load("kuhn3_seat_metric.json"), load("leduc3.json")
    tables.update(solver_tables(solvers))
    tables.update(family_tables(family))
    tables.update(seat_tables(seat))
    tables.update(leduc_table(leduc))
    values = {
        **solver_values(solvers["meta"], solvers["runs"]),
        **family_values(family),
        **seat_values(seat),
        **leduc_values(leduc),
    }
    text = DOC.read_text()
    for name, body in tables.items():
        # The block between the markers may be empty (a fresh doc) or hold the previous table.
        pattern = re.compile(
            rf"(<!-- BEGIN table:{re.escape(name)} -->\n)(?:.*?\n)?(<!-- END table:{re.escape(name)} -->)",
            re.S,
        )
        if not pattern.search(text):
            raise SystemExit(f"marker for table {name!r} not found in {DOC}")
        text = pattern.sub(lambda m, body=body: m.group(1) + body + "\n" + m.group(2), text)
    missing = set(re.findall(r"<!-- BEGIN table:([\w-]+) -->", text)) - set(tables)
    if missing:
        raise SystemExit(f"doc has markers with no generator: {sorted(missing)}")

    value = re.compile(r"<!--v:([\w-]+)-->.*?<!--/v-->")
    used = set(value.findall(text))
    if used - set(values):
        raise SystemExit(f"doc quotes values with no generator: {sorted(used - set(values))}")
    if set(values) - used:
        raise SystemExit(f"generated values the doc never quotes: {sorted(set(values) - used)}")
    text = value.sub(lambda m: f"<!--v:{m.group(1)}-->{values[m.group(1)]}<!--/v-->", text)
    DOC.write_text(text)
    print(
        f"wrote {len(tables)} tables and {len(used)} quoted values into {DOC.relative_to(HERE.parent.parent)}"
    )


if __name__ == "__main__":
    main()
