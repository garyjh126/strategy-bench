# StrategyBench

Measures how **strategically exploitable** an LLM agent is when it plays small imperfect-information games.

The LLM plays through a constrained text interface. Its behavioral strategy is estimated by repeated sampling at
each information state, and a classical best response (via [OpenSpiel](https://github.com/google-deepmind/open_spiel))
is computed against it. The headline output is an exploitability score per model per game, with bootstrap
confidence intervals.

> **Status:** Phase 4. Kuhn poker, Leduc poker and Liar's Dice run end to end (`direct` and `play`
> modes), clients for Claude, Gemini and DeepSeek are in place, and a static site (leaderboard,
> run pages, match replays, methodology) is built from the results. No LLM results are published
> yet; the site currently shows scripted reference subjects.

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
uv run python scripts/run_benchmark.py --game leduc --agent cfr-noisy --samples 200 --mode both --hands 20000
uv run python scripts/run_benchmark.py --game liars_dice --agent uniform --samples 200
```

Games: `kuhn` (the default), `leduc` and `liars_dice` (one three-sided die each; see the
methodology for the exact rules).

`--mode play` plays full hands against `--opponent equilibrium|uniform`; `--mode both` also checks
that the direct-mode estimate predicts the play results. `--prompt` selects a prompt variant
(for example `leduc-v1-para` or `leduc-v1+shuffled`).

## Measure a game before adding it

Prints decision infostates, how many are forced (one legal action), the direct-mode call count at
N samples per infostate and the CFR+ solve time, for any OpenSpiel load string:

```bash
uv run python scripts/game_size.py "liars_dice(numdice=1,dice_sides=3)" "liars_dice(numdice=1,dice_sides=4)"
```

## Run a real model

API keys come from environment variables: copy `.env.example` to `.env` and add yours, or, if
they live in Bitwarden (one item per key, named after the variable), prefix the command with
`scripts/with-keys.sh`. Models are defined in `models.yaml`.
Always look at the dry run first; paid models refuse to run without `--max-cost`.

```bash
uv run python scripts/run_benchmark.py --model deepseek-flash --samples 200 --dry-run
uv run python scripts/run_benchmark.py --model deepseek-flash --samples 200 --max-cost 1.00
```

Each run writes `manifest.json`, `calls.jsonl`, `strategy.json` and `metrics.json` to a new
directory under `runs/`. See [docs/methodology.md](docs/methodology.md) for the metric definitions.

## Build the site

The site is generated from the results directory. Every run directory with `metrics.json` is a
candidate; smoke tests (fewer than 30 samples per infostate) and superseded duplicates are left
out, with the reason printed.

```bash
uv run python scripts/run_references.py   # scripted reference subjects for every game (free)
uv run python scripts/build_site.py       # writes site/; open site/index.html in a browser
```

The build writes `breakdown.json` (where a best responder gains) and `replay.json` (hands for the
replay view) into each run directory, renders the pages, and then checks that every number on
every page matches the result file it names. It fails if any number does not.

`site/` is plain HTML, CSS and a little JavaScript with no external requests, so it can be
opened directly from disk or served from GitHub Pages.

To check how well the bootstrap intervals cover the true exploitability (free, by simulation):

```bash
uv run python scripts/ci_coverage.py --game kuhn
```

## Layout

```
src/strategybench/
  games/       game registry wrapping OpenSpiel games
  adapters/    LLM client interface and providers
  prompts/     versioned prompt templates
  estimation/  infostate enumeration and strategy estimation
  analysis/    exploitability, best response, CIs
  baselines/   scripted agents and CFR equilibrium
  report/      site build: run selection, derived files, templates, number tracing
scripts/       entry-point scripts
tests/         pytest suite
docs/          methodology and design notes
runs/          generated run logs and results (not committed)
apps/gui/      local web app: play the games against bots, browse a run's strategy (calls no model)
research/      exploratory work outside the benchmark (multiway/: three-player Kuhn and Leduc)
```

`uv run pytest` also runs the tests in `apps/gui/tests` and `research/multiway`. See
[apps/gui/README.md](apps/gui/README.md) and [docs/research/multiway.md](docs/research/multiway.md).

## License

MIT
