"""Run the scripted reference subjects on each game (free: mock subjects, no API calls).

The references answer through the same text interface as a model and anchor the
leaderboard's scale: the equilibrium and uniform random (each read exactly, and sampled like
a model), always check/fold, always the most aggressive action, and a noisy equilibrium
player with malformed replies that also plays a match against the equilibrium (play mode),
which gives the exact-versus-simulated cross-check and played hands for the replay view.

Each subject is run with scripts/run_benchmark.py, exactly as a model would be.

Examples:
    uv run python scripts/run_references.py
    uv run python scripts/run_references.py --games kuhn --samples 200 --hands 20000
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BENCHMARK = Path(__file__).with_name("run_benchmark.py")


def references(hands: int) -> list[list[str]]:
    return [
        ["--agent", "cfr", "--client", "distribution"],
        ["--agent", "cfr"],
        ["--agent", "uniform", "--client", "distribution"],
        ["--agent", "uniform"],
        ["--agent", "first-action"],
        ["--agent", "last-action"],
        ["--agent", "cfr-noisy", "--garbage-rate", "0.05", "--format-noise"]
        + ["--mode", "both", "--hands", str(hands)],
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--games", nargs="+", default=["kuhn", "leduc", "liars_dice"])
    ap.add_argument("--samples", type=int, default=200, help="samples per infostate for sampled subjects")
    ap.add_argument("--hands", type=int, default=20000, help="hands in the play-mode match")
    ap.add_argument("--out", default="runs")
    args = ap.parse_args()

    for game in args.games:
        for extra in references(args.hands):
            cmd = [sys.executable, str(BENCHMARK), "--game", game, "--samples", str(args.samples)]
            cmd += ["--out", args.out]
            print("$", " ".join(cmd[1:] + extra), flush=True)
            if subprocess.run(cmd + extra).returncode != 0:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
