"""Build the static site (leaderboard, run pages, replays, methodology) from a results directory.

Derives breakdown.json and replay.json in each shown run directory when they are missing or
stale, renders the pages into --out, and verifies that every number on every page matches the
result file it names. Open site/index.html in a browser; no server is needed.

Examples:
    uv run python scripts/build_site.py
    uv run python scripts/build_site.py --runs runs --out site --min-samples 30
    uv run python scripts/build_site.py --exclude 20261007T222508Z_kuhn_gemini-3.5-flash-lite_text
"""

from __future__ import annotations

import argparse
import sys

from strategybench.report.site import SiteError, build_site


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", default="runs", help="results directory (one subdirectory per run)")
    ap.add_argument("--out", default="site", help="output directory (replaced on each build)")
    ap.add_argument(
        "--min-samples", type=int, default=30, help="leave out sampled runs with fewer samples per infostate"
    )
    ap.add_argument("--exclude", nargs="*", default=[], help="run directory names to leave out")
    ap.add_argument("--replay-hands", type=int, default=100, help="hands per run in the replay view")
    ap.add_argument("--methodology", default="docs/methodology.md")
    args = ap.parse_args()

    try:
        result = build_site(
            args.runs, args.out, args.min_samples, args.exclude, args.replay_hands, args.methodology
        )
    except SiteError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    for run_id, files in result.derived.items():
        print(f"derived {', '.join(files)} for {run_id}")
    print(f"shown ({len(result.shown)}):")
    for run_id in result.shown:
        print(f"  {run_id}")
    if result.skipped:
        print(f"left out ({len(result.skipped)}):")
        for run_id, reason in result.skipped:
            print(f"  {run_id}: {reason}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    r = result.report
    print(f"verified {r.numbers} numbers on {r.pages} pages against {r.files} published result files")
    print(f"site: {result.out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
