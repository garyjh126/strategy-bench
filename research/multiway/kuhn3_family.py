"""The Szafron, Gibson and Sturtevant (AAMAS 2013) equilibrium family for 3-player Kuhn poker.

Notation follows the paper. `a`, `b`, `c` are players 1, 2, 3 (OpenSpiel players 0, 1, 2).
`xjk` is the probability of the aggressive action (bet or call, OpenSpiel action 1) holding
card j (1 = Jack ... 4 = Ace; OpenSpiel card j - 1) in betting situation k (Table 1):

    situation   P1      P2      P3
    1           -       K       KK
    2           KKB     B       KB
    3           KBF     KKBF    BF
    4           KBC     KKBC    BC

(K = check, B = bet, F = fold, C = call; OpenSpiel writes p for K/F and b for B/C.)

Table 2 of the paper fixes 21 parameters (dominated actions); Table 3 gives three
sub-families indexed by c11 (= 0, strictly between 0 and 1/2, = 1/2). The prose for the
c11 = 1/2 sub-family gives b33 = (1 + b11 + 2 b21) / 2, which differs from Table 3's general
formula b33 = 1/2 + (b11 + b21)/2 + beta/2 - b23 (1 - b21) (beta = b11 there). `B33_PROSE`
selects the prose version so the two can be checked against each other numerically.
"""

from __future__ import annotations

import numpy as np

KAPPA = 1.0 / 24.0
HISTORY = {
    0: {1: "", 2: "ppb", 3: "pbp", 4: "pbb"},
    1: {1: "p", 2: "b", 3: "ppbp", 4: "ppbb"},
    2: {1: "pp", 2: "pb", 3: "bp", 4: "bb"},
}
LETTER = "abc"
PARAMS = [f"{LETTER[p]}{j}{k}" for p in range(3) for j in range(1, 5) for k in range(1, 5)]

# Parameters at infostates that are never reached when player 1 never opens with a bet
# (true of every member of the family): player 2 facing an opening bet, player 3 after
# an opening bet.
OFF_PATH = {f"b{j}2" for j in range(1, 5)} | {f"c{j}{k}" for j in range(1, 5) for k in (3, 4)}

TABLE2 = {}
for _x in "abc":
    TABLE2.update({f"{_x}12": 0.0, f"{_x}13": 0.0, f"{_x}14": 0.0, f"{_x}24": 0.0})
    TABLE2.update({f"{_x}42": 1.0, f"{_x}43": 1.0, f"{_x}44": 1.0})

COMMON = {
    # Player 1 has no free parameters.
    "a11": 0.0, "a21": 0.0, "a22": 0.0, "a23": 0.0, "a31": 0.0,
    "a32": 0.0, "a33": 0.5, "a34": 0.0, "a41": 0.0,
    "b22": 0.0, "b31": 0.0, "b34": 0.0,
    "c22": 0.0, "c23": 0.0, "c31": 0.0, "c32": 0.0, "c41": 1.0,
}  # fmt: skip

SUBFAMILIES = ("c11=0", "0<c11<1/2", "c11=1/2")


def key(param: str) -> str:
    """OpenSpiel information-state string of a parameter."""
    player = LETTER.index(param[0])
    return f"{int(param[1]) - 1}{HISTORY[player][int(param[2])]}"


def to_sigma(tree, params: dict) -> np.ndarray:
    sigma = np.zeros(tree.num_seqs)
    for name in PARAMS:
        info = tree.infoset_index[key(name)]
        first = tree.infoset_first_seq[info]
        assert tree.infoset_actions[info] == [0, 1]
        sigma[first] = 1.0 - params[name]
        sigma[first + 1] = params[name]
    return sigma


def from_sigma(tree, sigma: np.ndarray) -> dict:
    return {name: float(sigma[tree.infoset_first_seq[tree.infoset_index[key(name)]] + 1]) for name in PARAMS}


def beta(p: dict) -> float:
    return max(p["b11"], p["b21"])


def predicted_ev(p: dict) -> list[float]:
    """Table 3 utilities, which depend only on beta = max(b11, b21)."""
    bt = beta(p)
    return [-KAPPA * (0.5 + bt), -KAPPA * 0.5, KAPPA * (1.0 + bt)]


def member(sub: str, free: dict, b33_prose: bool = False) -> dict:
    """Fill a member of a sub-family from its free parameters (c34 defaults to 0)."""
    p = dict(TABLE2)
    p.update(COMMON)
    p["c34"] = free.get("c34", 0.0)
    b11 = free["b11"]
    if sub == "c11=0":
        b21 = free["b21"]
        p.update(b11=b11, b21=b21, b23=0.0, c11=0.0, c21=0.5)
        p["b33"] = (1 + b11 + 2 * b21) / 2
        p["b41"] = 2 * b11 + 2 * b21
    elif sub == "0<c11<1/2":
        c11 = free["c11"]
        p.update(b11=b11, b21=b11, b23=0.0, c11=c11, c21=0.5 - c11)
        p["b33"] = (1 + 3 * b11) / 2
        p["b41"] = 4 * b11
    elif sub == "c11=1/2":
        b21, b23 = free["b21"], free["b23"]
        p.update(b11=b11, b21=b21, b23=b23, c11=0.5, c21=0.0)
        if b33_prose:
            p["b33"] = (1 + b11 + 2 * b21) / 2
        else:
            p["b33"] = 0.5 + (b11 + b21) / 2 + b11 / 2 - b23 * (1 - b21)
        p["b41"] = 2 * b11 + 2 * b21
    else:
        raise ValueError(sub)
    p["b32"] = free["b32"]
    p["c33"] = free["c33"]
    assert set(p) == set(PARAMS)
    return p


def sample_free(sub: str, rng: np.random.Generator) -> dict:
    """Draw free parameters inside a sub-family's constraints (not uniform on the region)."""
    u = rng.uniform
    if sub == "c11=0":
        b21 = u(0, 0.25)
        b11 = u(0, b21)
        reach = 3 * b11 + 4 * b21
        free = {"b11": b11, "b21": b21}
    elif sub == "0<c11<1/2":
        b11 = u(0, 0.25)
        c_max = 0.5 if b11 <= 1 / 6 else (2 - b11) / (3 + 4 * b11)
        free = {"b11": b11, "c11": u(0, c_max) * (1 - 1e-9) + 1e-12}
        reach = 7 * b11
    else:
        b11 = u(0, 0.25)
        b21 = u(0, min(b11, 0.5 - 2 * b11))
        b23 = u(0, (b11 - b21) / (2 * (1 - b21)))
        free = {"b11": b11, "b21": b21, "b23": b23}
        reach = 4 * b11 + 3 * b21
    b32 = u(0, (2 + reach) / 4)
    lo, hi = 0.5 - b32, 0.5 - b32 + reach / 4
    free.update(b32=b32, c33=u(lo, hi), c34=u(0, 1))
    return free


def _eq(x, y):
    return abs(x - y)


def _le(x, y):
    return max(0.0, x - y)


def constraints(p: dict, sub: str) -> list[tuple[str, tuple[str, ...], float]]:
    """(label, parameters involved, violation >= 0) for Table 2, the fixed part of Table 3
    and the sub-family's own constraints."""
    out = [(f"{k}={v:g}", (k,), _eq(p[k], v)) for k, v in {**TABLE2, **COMMON}.items()]
    b11, b21, b23, b32, b33, b41 = (p[k] for k in ("b11", "b21", "b23", "b32", "b33", "b41"))
    c11, c21, c33 = p["c11"], p["c21"], p["c33"]
    if sub == "c11=0":
        reach = 3 * b11 + 4 * b21
        out += [
            ("c11=0", ("c11",), _eq(c11, 0.0)),
            ("b21<=1/4", ("b21",), _le(b21, 0.25)),
            ("b11<=b21", ("b11", "b21"), _le(b11, b21)),
            ("b23=0", ("b23",), _eq(b23, 0.0)),
            ("b33=(1+b11+2b21)/2", ("b33", "b11", "b21"), _eq(b33, (1 + b11 + 2 * b21) / 2)),
            ("b41=2b11+2b21", ("b41", "b11", "b21"), _eq(b41, 2 * b11 + 2 * b21)),
            ("c21=1/2", ("c21",), _eq(c21, 0.5)),
        ]
    elif sub == "0<c11<1/2":
        reach = 7 * b11
        c_max = 0.5 if b11 <= 1 / 6 else (2 - b11) / (3 + 4 * b11)
        out += [
            ("c11<=cmax", ("c11", "b11"), _le(c11, c_max)),
            ("b11<=1/4", ("b11",), _le(b11, 0.25)),
            ("b21=b11", ("b21", "b11"), _eq(b21, b11)),
            ("b23=0", ("b23",), _eq(b23, 0.0)),
            ("b33=(1+3b11)/2", ("b33", "b11"), _eq(b33, (1 + 3 * b11) / 2)),
            ("b41=4b11", ("b41", "b11"), _eq(b41, 4 * b11)),
            ("c21=1/2-c11", ("c21", "c11"), _eq(c21, 0.5 - c11)),
        ]
    else:
        reach = 4 * b11 + 3 * b21
        out += [
            ("c11=1/2", ("c11",), _eq(c11, 0.5)),
            ("b11<=1/4", ("b11",), _le(b11, 0.25)),
            ("b21<=min(b11,1/2-2b11)", ("b21", "b11"), _le(b21, min(b11, 0.5 - 2 * b11))),
            ("b23<=(b11-b21)/(2(1-b21))", ("b23", "b11", "b21"), _le(b23, (b11 - b21) / (2 * (1 - b21)))),
            (
                "b33=1/2+(b11+b21)/2+b11/2-b23(1-b21)",
                ("b33", "b11", "b21", "b23"),
                _eq(b33, 0.5 + (b11 + b21) / 2 + b11 / 2 - b23 * (1 - b21)),
            ),
            ("b41=2b11+2b21", ("b41", "b11", "b21"), _eq(b41, 2 * b11 + 2 * b21)),
            ("c21=0", ("c21",), _eq(c21, 0.0)),
        ]
    out += [
        ("b32<=(2+r)/4", ("b32", "b11", "b21"), _le(b32, (2 + reach) / 4)),
        ("c33>=1/2-b32", ("c33", "b32"), _le(0.5 - b32, c33)),
        ("c33<=1/2-b32+r/4", ("c33", "b32", "b11", "b21"), _le(c33, 0.5 - b32 + reach / 4)),
    ]
    return out


def distance(p: dict) -> dict:
    """Largest constraint violation per sub-family, split into on-path and off-path groups.

    A constraint is off-path if it involves any parameter in OFF_PATH. Returns the closest
    sub-family by on-path violation, and both violations for every sub-family.
    """
    per = {}
    for sub in SUBFAMILIES:
        on = off = 0.0
        worst_on = ""
        for label, names, viol in constraints(p, sub):
            if any(n in OFF_PATH for n in names):
                off = max(off, viol)
            elif viol > on:
                on, worst_on = viol, label
        per[sub] = {"on_path": on, "off_path": off, "worst_on_path": worst_on}
    best = min(SUBFAMILIES, key=lambda s: (per[s]["on_path"], per[s]["off_path"]))
    return {"closest": best, **per[best], "per_subfamily": per}
