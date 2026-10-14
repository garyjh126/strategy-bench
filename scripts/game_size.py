"""Measure the size of OpenSpiel games before adding one: infostates, forced decisions, solve time.

For each load string, prints the decision histories and decision infostates (per seat), how
many infostates have a single legal action (forced; direct mode does not query them), the
direct-mode call count at N samples per queried infostate, and the time and result of OpenSpiel's C++
CFR+ (seat values and exploitability of the average policy). Makes no subject calls.

Examples:
    uv run python scripts/game_size.py "liars_dice(numdice=1,dice_sides=3)"
    uv run python scripts/game_size.py "liars_dice(numdice=1,dice_sides=6)" --iterations 0
"""

from __future__ import annotations

import argparse
import time

import pyspiel
from open_spiel.python import policy as policy_lib
from open_spiel.python.algorithms import expected_game_score, exploitability, get_all_states

from strategybench.estimation.infostates import enumerate_infostates


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("games", nargs="+", help="OpenSpiel load strings")
    ap.add_argument("--samples", type=int, default=200, help="samples per infostate (N) for the call count")
    ap.add_argument("--iterations", type=int, default=200, help="CFR+ iterations to time (0 skips solving)")
    args = ap.parse_args()

    for load_string in args.games:
        game = pyspiel.load_game(load_string)
        histories = get_all_states.get_all_states(
            game, depth_limit=-1, include_terminals=False, include_chance_states=False
        )
        infos = enumerate_infostates(game)
        per_seat = [sum(i.player == p for i in infos) for p in range(game.num_players())]
        forced = sum(len(i.legal_actions) == 1 for i in infos)
        widths = [len(i.legal_actions) for i in infos]
        n = args.samples
        print(load_string)
        print(f"  decision histories:       {len(histories):,}")
        seats = ", ".join(f"Player {p + 1}: {k:,}" for p, k in enumerate(per_seat))
        print(f"  decision infostates:      {len(infos):,} ({seats})")
        print(f"  forced (1 legal action):  {forced:,} ({forced / len(infos):.1%})")
        print(f"  legal actions:            mean {sum(widths) / len(widths):.2f}, max {max(widths)}")
        queried = len(infos) - forced
        print(f"  direct-mode calls, N={n}: {queried * n:,} (forced infostates are not queried)")
        if args.iterations > 0:
            solver = pyspiel.CFRPlusSolver(game)
            start = time.perf_counter()
            for _ in range(args.iterations):
                solver.evaluate_and_update_policy()
            seconds = time.perf_counter() - start
            avg = policy_lib.pyspiel_policy_to_python_policy(game, solver.tabular_average_policy())
            values = expected_game_score.policy_value(game.new_initial_state(), [avg, avg])
            print(
                f"  CFR+ {args.iterations} iterations:    {seconds:.2f} s; seat values "
                f"{[round(float(v), 5) for v in values]}; exploitability "
                f"{exploitability.exploitability(game, avg):.2g}"
            )


if __name__ == "__main__":
    main()
