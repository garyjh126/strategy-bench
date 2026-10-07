"""Solve Kuhn poker with CFR and print the exploitability trajectory and game value.

Usage:
    uv run python scripts/solve_kuhn.py [--iterations N] [--eval-every K] [--plus]
"""

from __future__ import annotations

import argparse

from strategybench.baselines.cfr import solve_cfr

KUHN_P1_VALUE = -1.0 / 18.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--eval-every", type=int, default=1_000)
    parser.add_argument("--plus", action="store_true", help="use CFR+ instead of vanilla CFR")
    args = parser.parse_args()

    result = solve_cfr("kuhn_poker", args.iterations, args.eval_every, plus=args.plus)

    print(f"{'CFR+' if args.plus else 'CFR'} on kuhn_poker")
    print(f"{'iteration':>10}  {'exploitability':>14}")
    for it, expl in result.exploitability_history:
        print(f"{it:>10}  {expl:>14.6g}")

    p1 = result.game_value[0]
    print(f"\nGame value (P1, P2): ({p1:.6f}, {result.game_value[1]:.6f})")
    print(f"Theoretical P1 value: {KUHN_P1_VALUE:.6f}  (|diff| = {abs(p1 - KUHN_P1_VALUE):.2e})")


if __name__ == "__main__":
    main()
