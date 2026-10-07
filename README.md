# StrategyBench

Measures how **strategically exploitable** an LLM agent is when it plays small imperfect-information games.

The LLM plays through a constrained text interface. Its behavioral strategy is estimated by repeated sampling at
each information state, and a classical best response (via [OpenSpiel](https://github.com/google-deepmind/open_spiel))
is computed against it. The headline output is an exploitability score per model per game, with bootstrap
confidence intervals.

> **Status:** Phase 1 in progress. The Kuhn poker pipeline runs end to end with mock subjects;
> no real LLM results yet.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). OpenSpiel wheels are available for Linux and macOS;
on Windows use WSL or Docker.

```bash
uv sync
uv run pytest
```

## Solve Kuhn poker with CFR

```bash
uv run python scripts/solve_kuhn.py --iterations 10000 --eval-every 1000
```

Prints CFR exploitability over iterations and the equilibrium game value (theory: −1/18 for player 1).

## Run the pipeline with a mock subject

Mock subjects are scripted policies that answer through the same text interface as an LLM,
so the full pipeline can be checked against known values at no cost.

```bash
uv run python scripts/run_benchmark.py --agent uniform --samples 200
uv run python scripts/run_benchmark.py --agent cfr --client distribution
uv run python scripts/run_benchmark.py --agent cfr-noisy --samples 200 --garbage-rate 0.1 --format-noise
uv run python scripts/run_benchmark.py --agent uniform --samples 100 --dry-run   # call count only
```

Each run writes `manifest.json`, `calls.jsonl`, `strategy.json` and `metrics.json` to a new
directory under `runs/`. See [docs/methodology.md](docs/methodology.md) for the metric definitions.

## Layout

```
src/strategybench/
  games/       game registry wrapping OpenSpiel games
  adapters/    LLM client interface and providers
  prompts/     versioned prompt templates
  estimation/  infostate enumeration and strategy estimation
  analysis/    exploitability, best response, CIs
  baselines/   scripted agents and CFR equilibrium
  report/      leaderboard and static site
scripts/       entry-point scripts
tests/         pytest suite
docs/          methodology
runs/          generated run logs and results (not committed)
```

## License

MIT
