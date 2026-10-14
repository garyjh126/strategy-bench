# Proposal B: a strategy viewer

**Recommendation.** Build it as a **"Strategy" tab on each run page of the static site**, next to
"Replay". Organise it by public decision point: an action path across the top, one tile per
private hand, a table with the pot, overall action frequencies, and exact numbers for one hand.
At the subject's decisions it compares the measured strategy with CFR+. At the best responder's
decisions it shows the best response and the chips it wins there, from the existing gain
breakdown. Ship it for Kuhn first. It is worth building for the small games, but because of how
it organises the strategy rather than because of the grid.

**Mockup** (invented subject, everything else computed exactly; see "About the mockup"):

* [`img/mockup-responder-node.png`](img/mockup-responder-node.png): Player 2 facing a bet. The CFR+ mix per card, the best
  response, and the 0.061 ante per hand it wins with the Queen.
* [`img/mockup-subject-node.png`](img/mockup-subject-node.png): Player 1's first decision. Subject against CFR+ per card,
  with the exact numbers for the Jack.
* [`img/mockup-dark.png`](img/mockup-dark.png) and [`img/mockup-mobile.png`](img/mockup-mobile.png): dark theme and phone width.
* [`mockup/strategy-view.html`](mockup/strategy-view.html): the page itself, clickable (open it in a browser).

---

## 1. Where it lives: static site or local GUI?

**Static site.** The viewer's job is comparison for someone reading results (a reviewer, an
interviewer), so it belongs where the results are. It works on GitHub Pages with no Python.
Almost all its data is already published with each run. The site's rule that every number traces
to a result file can cover it, as long as the new numbers come from a derived file built at build
time, the same pattern as `breakdown.json` and `replay.json`.

**Local GUI.** It can show any game, including three-player and custom ones, and computes CFR
profiles live. But it is only on your machine, and its explorer already covers ad-hoc
inspection: one row per situation, run against CFR. Once the site version exists, the same
JavaScript component could be reused there.

**So:** site first. GUI later, only if you want the tile view for custom games.

## 2. What the "hand grid" is for each game

Each public decision point (same public history, same player to act) has one cell per private
hand. Counted with OpenSpiel (a chance event is private when it only changes some players'
information):

| Game | Decision points | Hands per point | Layout |
|---|---|---|---|
| Kuhn | 4 (2 per seat) | 3: Jack, Queen, King | a row of 3 tiles; the whole game fits on one screen |
| Leduc | 96 | 3: the private rank (suits are merged by the suit-isomorphic encoding) | round 1: a row of 3; round 2: a 3×3 grid, private rank × board rank, which merges the three board cards for the same betting (the diagonal is a pair) |
| Liar's Dice | 64, of which 32 forced (only LIAR after 2×3) | 3: your die face | a row of 3; forced points hidden, as in the explorer |
| Phase 5 Hold'em | depends on the reduction | e.g. 13×13 starting hands, smaller with a reduced deck | the familiar grid, supplied by that game's `GameSpec` |

**Is it worth it for the small games?** Yes, but the grid itself adds little when there are three
hands. The value is elsewhere:

1. **Organisation by decision point.** The run page and the GUI explorer list situations one by
   one. The viewer shows a whole range at once ("what does the subject do with each card when
   checked to?"), which is how a poker player reads a strategy.
2. **The best-response overlay.** The breakdown already says where the best responder gains, but
   as a ranked list. The viewer places each gain at its decision point, next to the subject
   decision that caused it. The mockup's message is "the subject bluffs the Jack 36% of the time
   but bets the King only 53%, so too many of its bets are bluffs. Player 2 should always call
   with the Queen, which wins 0.061 ante per hand".
3. **One screen for Kuhn.** Four decision points of three tiles give the whole strategy and the
   whole leak in one view, which suits a portfolio page.

The 13×13 grid pays off only with Hold'em. So I would make the layout a `GameSpec` hook (row,
grid, or 13×13) rather than build the big grid now.

## 3. Data: what it needs and what already exists

| Needed | Where it comes from | Exists? |
|---|---|---|
| Subject's mix per situation, sample counts, filled flag | `strategy.json` (`estimated`, `support`, `filled`) | yes |
| CFR+ mix per situation | `strategy.json` (`equilibrium`) and `breakdown.json` | yes. The equilibrium cache (`runs/equilibria/*.npz`) is not needed, and is not published |
| Best response, value of each action per visit, edge, reach, contribution, share, at every responder situation | `breakdown.json` → `seats[].responder` | yes: all 6 / 144 / 96 situations per seat in Kuhn / Leduc / Liar's Dice, not only the top ones |
| Subject's reach and distance from CFR+ per situation | `breakdown.json` → `seats[].subject` | yes |
| Gain split: without adapting (M3) and by adapting | `breakdown.json` → `passive`, `active` | yes |
| Which situations share a public decision point, and the hand label of each | nothing yet | **new**: a generic grouping (a chance event is public if every player's infostate depends on it; the GUI's `observers` already does this test), plus an optional `GameSpec` hook for hand labels and layout |
| Pot (poker) or current bid (Liar's Dice) at each point | nothing yet | **new**: a small optional `GameSpec` hook, with no table drawn if absent |
| Overall action frequencies per point, each strategy over the hands it holds there | nothing yet | **new**: computed at build time (it needs reach), so it can be traced |
| Interval per cell (Wilson, from counts) | counts are in `strategy.json` | optional, computed at build time |

So one new derived file per run, `strategy_view.json`, built from `strategy.json` and
`breakdown.json` with their hashes recorded. It is much smaller than `breakdown.json` (592 KB
for Leduc today). No new solving, no new runs.

## 4. Effort, in separately shippable pieces

| # | Piece | Ships | Estimate |
|---|---|---|---|
| 1 | Derived data: grouping by decision point, overall frequencies, pot and labels hooks for the three games; tests (Kuhn: 4 points × 3 hands; frequencies match a hand computation; contributions per point sum to `active`) | nothing visible yet | 1.5 days |
| 2 | Kuhn page v1: action path, hand tiles and detail panel at the subject's decisions; number tracing in the build check | a usable Strategy tab for Kuhn | 1.5 days |
| 3 | Best-response overlay at the responder's decisions, the "where it wins" list and the gain split | the comparison the page exists for | 1 day |
| 4 | Table diagram and overall frequency bars | polish | 0.5–1 day |
| 5 | Leduc round-2 3×3 grid and Liar's Dice tiles (forced points hidden) | all three games | 1 day |
| 6 | Hold'em grid, when Phase 5 exists | Phase 5 | about 1 day |

About 5–6 days for the three current games. Pieces 1+2 (3 days) already give a useful Kuhn
page; 3 is what makes it a comparison tool.

## 5. Design notes from building the mockup

* **Colours.** The two Kuhn action kinds use the site's categorical slots 1 and 2 (blue
  check/fold, orange bet/call). The pair passes the colour-vision validator in light and dark
  (worst colour-blind separation ΔE 24.7 light, 26.8 dark). "Chips won" is drawn in neutral ink,
  not a third hue. Every bar has its numbers printed next to it.
* **Honest attribution.** The breakdown attributes gains to the best responder's decisions, not
  to the subject's. The page says so ("a leak in the subject's play shows up at the decision
  that follows it") and does not invent a per-decision chip cost for the subject.
* **Rounding.** Contributions below the shown precision (0.001) come from the CFR+ reference
  not being exactly an equilibrium. The mockup groups them as "every other situation", rather
  than listing dozens of "+0.000" rows.
* **Reach is shown per hand.** Without it, a big difference at a rarely reached hand looks as
  important as one at a common hand.

## 6. Decisions for you

1. Site (recommended) or GUI?
2. Show a 95% interval per cell, or just N?
3. Which seat to open on: the seat with the larger gain, or always Player 1?
4. Name of the tab: "Strategy" (mockup) or something else?

## About the mockup

The subject's action frequencies and sample counts are invented. Best responses, edges,
contributions, reach and values were computed exactly from them with
`strategybench.analysis.breakdown.br_breakdown` against the project's cached CFR+ reference
(`mockup/make_data.py`, which wrote `mockup/data.json`; the page embeds that file), so the page is internally consistent. In particular, 0.117 =
0.024 + 0.093, and the two contributions sum to 0.093. The mockup lives only in this folder and changes nothing in the package. The
layout borrows only generic ideas from your screenshot (path across the top, hand grid, action
bar, table, details panel) and uses the site's own design tokens; no product is named.
