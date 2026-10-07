# Design notes

Decisions that are not obvious from the code, and a log of changes to `estimation/` and
`analysis/` (the brief asks that adding a game need no changes there).

## Generality log

| Phase | Game added | Core changes needed for the game | Other core changes in the phase |
|---|---|---|---|
| 1 | Kuhn | n/a (first game) | n/a |
| 2 | Leduc | **None.** New files only: `games/leduc.py`, `prompts/leduc.py`, two registry lines, tests. | Equilibrium solver switched from OpenSpiel's Python CFR+ to its C++ CFR+ with a disk cache (Leduc: about 10 s per 1,000 iterations instead of about 1 minute). Query and retry logic extracted into `TextQuerier` so `play` mode can share it. `exact_seat_values` added for the play-mode cross-check. None of these is game-specific. |

## Decisions

* **Leduc is the suit-isomorphic variant** (`leduc_poker(suit_isomorphism=True)`, 288 infostates).
  Prompts name ranks only, so suited infostates would collapse to identical prompts.
* **Strict parsing.** The whole reply must be one label (after trimming quotes, asterisks,
  backticks, a trailing period and case). Verbose replies count as failures and show up in M4.
* **The system prompt is logged once per run** in `manifest.json` rather than on every call line,
  to keep `calls.jsonl` small. It is constant within a run.
* **Play-mode fallback.** A play-mode decision that fails every attempt is played uniformly at
  random and counted as a fallback. Play must continue, so this is the one place an action is
  substituted; it is always reported.
* **Provider settings** (recorded in `models.yaml`, checked 2026-10-08):
  * Anthropic SDK 1.x removed `temperature` from `messages.create`. Models that still accept it
    (Haiku 4.5) get it through `extra_body`. Newer Claude models reject custom temperatures.
  * DeepSeek's current models reason by default; even `reasoning_effort: low` used more than 2,048
    tokens on a Kuhn prompt and returned no answer. They run with thinking disabled.
  * Gemini 3.5 Flash-Lite does not think by default.
