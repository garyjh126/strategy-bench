# Design notes

Decisions that are not obvious from the code, and a log of changes to `estimation/` and
`analysis/` (the brief asks that adding a game need no changes there).

## Generality log

| Phase | Game added | Core changes needed for the game | Other core changes in the phase |
|---|---|---|---|
| 1 | Kuhn | n/a (first game) | n/a |
| 2 | Leduc | **None.** New files only: `games/leduc.py`, `prompts/leduc.py`, two registry lines, tests. | Equilibrium solver switched from OpenSpiel's Python CFR+ to its C++ CFR+ with a disk cache (Leduc: about 10 s per 1,000 iterations instead of about 1 minute). Query and retry logic extracted into `TextQuerier` so `play` mode can share it. `exact_seat_values` added for the play-mode cross-check. None of these is game-specific. |
| 3 | (none) | n/a | `analysis/breakdown.py` added (per-infostate decomposition of M2); no existing `estimation/` or `analysis/` code changed. `GameSpec` gained four **optional** members with defaults (`title`, `summary`, `short_label`, `describe_chance`), used only by reports, so a new game still needs only its own spec. |
| 4 | Liar's Dice | **None.** New files only: `games/liars_dice.py`, `prompts/liars_dice.py`, registry entries in `games/__init__.py` and `prompts/__init__.py`, tests. `git diff --stat c2fbbac -- src/strategybench/estimation src/strategybench/analysis` is empty. | None in `estimation/` or `analysis/`. Report wording: `GameSpec` gained two more **optional** attributes whose defaults keep Kuhn and Leduc unchanged (`episode`, default "hand", "round" for Liar's Dice; `reference_names`, the scripted references' names in the game's terms). Site-wide text no longer says "poker", and `replay.json` records the episode word (`DERIVED_VERSION` 3). `scripts/game_size.py` added for sizing games. |

**Design flaw found in Phase 4, fixed 2026-10-14: direct mode queried forced decisions.**
`collect_text` samples every infostate, including those with a single legal action. Kuhn and
Leduc have none, but half of Liar's Dice's 192 infostates are forced (after 2x3 only LIAR is
legal), so a real-model run makes twice the calls it needs: 38,400 instead of 19,200 at N = 200.
Results are unaffected, because the estimated strategy at a forced infostate is LIAR whatever
the replies (the uniform fill gives the same), so only M4 counts them. Skipping them is a small,
game-independent change to `estimation/direct.py` and the dry-run count. It is deferred so that
Phase 4's gate tests the game alone, and because it changes what M4 measures; it needs the
owner's decision. The owner approved it, and since 2026-10-14 both direct-mode collectors skip
forced infostates (`InfoState.forced`), report them under `forced` in `metrics.json` and
`strategy.json`, and count them as covered. A Liar's Dice run now makes 19,200 calls at
N = 200; the dry-run estimates below predate the change and are halved by it.

## Decisions

* **Leduc is the suit-isomorphic variant** (`leduc_poker(suit_isomorphism=True)`, 288 infostates).
  Prompts name ranks only, so suited infostates would collapse to identical prompts.
* **Liar's Dice uses one three-sided die each** (`liars_dice(numdice=1,dice_sides=3)`). Sizes from
  `scripts/game_size.py` (timings on the development machine):

  | Dice sides | Decision infostates | Forced | Direct-mode calls at N = 200 | CFR+ 200 iterations |
  |---|---|---|---|---|
  | 3 | 192 | 96 | 38,400 | 0.17 s |
  | 4 | 1,024 | 512 | 204,800 | 1.02 s |
  | 6 | 24,576 | 12,288 | 4,915,200 | not run |

  Dry-run estimates for three sides at N = 200 (`scripts/run_benchmark.py --game liars_dice
  --model <name> --samples 200 --dry-run`, prices from `models.yaml`): Claude Haiku 4.5 $14.98
  ($44.93 if every sample needed both retries), DeepSeek Flash $4.30 ($12.89), Gemini 3.5
  Flash-Lite free but limited to the configured 10 requests per minute (38,400 calls is about 64
  hours). Four sides needs 5.3 times the calls, so it would cost at least 5.3 times as much; for
  comparison Leduc needs 57,600 calls at N = 200. Nothing rules three sides out: the reference
  equilibrium mixes (in any Liar's Dice run's `strategy.json`, Player 1 holding a 3 opens 2x1,
  2x2 or 2x3 about 33%, 38% and 29% of the time) and fixed rules are very exploitable (7/9 for
  always the lowest bid, 8/9 for always LIAR).
* **Liar's Dice rules come from OpenSpiel's source, not the usual game.** Checked in the installed
  2.0.2 wheel (`open_spiel/games/liars_dice/liars_dice.cc`): the highest face is wild (the common
  rule makes 1s wild), a bid on the wild face counts only that face, bids rank by quantity then
  face, LIAR is not legal on the opening move, the bidder wins a challenge if at least the bid
  quantity of dice match, and payoffs are +1 / -1. The rules prompt states all of these, and tests
  score challenges to confirm them.
* **Liar's Dice labels** are `QxF` bids (`1x1` to `2x3`) and `LIAR`: short, unique, untouched by
  the parser's normalisation, and all listed in order in the rules prompt. The situation text also
  says when the current bid is true ("true if at least one of the two dice shows 2 or 3"), so the
  notation and the wild rule cannot be misread. This is the same kind of derived fact as Leduc's
  "To call: 4 chips".
* **Strict parsing.** The whole reply must be one label (after trimming quotes, asterisks,
  backticks, a trailing period and case). Verbose replies count as failures and show up in M4.
* **The system prompt is logged once per run** in `manifest.json` rather than on every call line,
  to keep `calls.jsonl` small. It is constant within a run.
* **Bootstrap intervals are basic (reflected), not percentile** (changed in Phase 3). Exploitability
  is a maximum, so plug-in estimates and bootstrap replicates are both biased upwards and
  percentile intervals sit above the truth; for an equilibrium subject they essentially never
  cover it. Runs report the bias-corrected estimate with the basic interval centred on it, and
  keep the plug-in value and the percentile interval in `metrics.json`. Evidence:
  `scripts/ci_coverage.py` (see the methodology). Basic intervals are still far from calibrated
  near equilibrium in Leduc (30% coverage), and did worse than percentile for one Leduc
  strategy, so this is an improvement, not a solution; a cross-fitted lower estimate is the
  candidate next step.
* **Reference rows are not re-drawn to look tidy.** The sampled uniform subject in Kuhn
  (seed 0) lands 2.7 standard deviations above the exact value because one infostate (King
  facing a bet) drew 61% folds. The exact-probability row sits next to it; changing the seed to
  hide that would be cherry-picking.
* **Play-mode fallback.** A play-mode decision that fails every attempt is played uniformly at
  random and counted as a fallback. Play must continue, so this is the one place an action is
  substituted; it is always reported.
* **Provider settings** (recorded in `models.yaml`, checked 2026-10-08):
  * Anthropic SDK 1.x removed `temperature` from `messages.create`. Models that still accept it
    (Haiku 4.5) get it through `extra_body`. Newer Claude models reject custom temperatures.
  * DeepSeek's current models reason by default; even `reasoning_effort: low` used more than 2,048
    tokens on a Kuhn prompt and returned no answer. They run with thinking disabled.
  * Gemini 3.5 Flash-Lite does not think by default.

## Reporting (Phase 3)

* **The site build only reads files.** Everything shown is either in a run's own result files or
  in two derived files written into the run directory (`breakdown.json`, `replay.json`). Derived
  files record the SHA-256 of their inputs and are rebuilt when an input changes. Bump
  `DERIVED_VERSION` in `report/derive.py` whenever their schema changes.
* **Number tracing.** Every number on a results page is rendered by `Source.num`, which emits a
  span with `data-src="<published file>#<JSON pointer>"`, `data-fmt` and an optional
  `data-scale` (CIs and bias values are stored in native units). `report/verify.py` re-reads every
  span after the build and fails the build on a mismatch. Formatting lives in one table
  (`report/numbers.py`) shared by pages, tooltips and replay data, so the same value always
  prints the same way. The replay page renders with JavaScript from strings preformatted in
  Python, because Python and JavaScript round exact halves differently (62.5% is a common
  frequency at N = 200).
* **Charts are HTML and CSS**, not Plotly: no CDN, works offline from `file://`, prints, and the
  numbers stay in the HTML where the verifier can see them. Colours follow a validated palette
  (accent blue for LLM rows, grey for references) with a selected dark theme.
* **Replay hands are stored trajectories, not a game tree.** Kuhn and Leduc trees are small (774
  decision nodes for suit-isomorphic Leduc), but a one-die, six-sided Liar's Dice has 147,456
  (`scripts/game_size.py`), so embedding trees would not scale to larger games.
* **Key-situation hands** use the history in the infostate where switching to the best response
  gains most (reach-weighted), not the most likely history. The most likely history can be one
  where the best response loses (calling a Queen into a King) even though it gains on average,
  which makes a confusing example.
* **What gets published.** `manifest.json`, `metrics.json`, `strategy.json`, `breakdown.json`,
  `replay.json` and `play.json` are copied next to each run page. Raw call logs stay in the run
  directory: Leduc logs at N = 200 are tens of megabytes. `build.json` uses paths relative to the
  results directory, so local absolute paths are never published.
* **Output directory safety.** The build replaces its output directory only if it is empty or
  was made by the build (marked by `build.json`), and writes the marker first so a failed build
  can be overwritten.
