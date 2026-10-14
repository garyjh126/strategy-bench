# Proposal C: Phase 5 sizing of reduced Hold'em variants

Phase 5 asks for a small Hold'em variant whose exact best response can be computed, and asks
for its size to be measured before committing to one. This is that measurement and nothing more.
No code was added to the repo: every number below was printed by `scripts/game_size.py` on
OpenSpiel's `universal_poker`, and the raw output is in the appendix. Nothing in `src/` changed,
and no model was called.

**Recommendation.** Take **C1**, a fixed-flop subgame: two private cards each from a 24-card deck
(ranks 2 to 7), a fixed rainbow flop `5c6d7h`, and one limit betting round with at most two
bets. It is the smallest measured variant with Hold'em's hands (two private cards plus the
board, ranked by the usual 5-card rules). It has 1,260 infostates, 4.4 times Leduc's calls at
the same N. The cost is compute: 862k histories, 13.7 GB peak memory, and a 43 s exact
evaluation. So before any real run, a mock-subject run should measure how long the bootstrap
takes (section 4). If that is too slow, **C2** (at most one bet) is a third smaller. If you
would rather keep a card dealt during play, **A1** (Leduc's deck with Hold'em blinds and
position) costs seconds to analyse, but it is Leduc with blinds rather than Hold'em. Your
decisions are listed in section 6.

---

## 1. How this was measured

* OpenSpiel 2.0.2 (the pinned version) offers `kuhn_poker`, `leduc_poker`,
  `repeated_leduc_poker`, `repeated_poker` and `universal_poker`. Only `universal_poker` can
  describe a reduced Hold'em: deck size (`numRanks`, `numSuits`), private cards
  (`numHoleCards`), board cards per round (`numBoardCards`), limit betting (`betting=limit`,
  `raiseSize`, `maxRaises`), blinds and who acts first per round (`blind`, `firstPlayer`), and a
  fixed board (`boardCards`). A parameter that takes one value per round must be given at least
  two values (`raiseSize=2 2`), or the loader reads it as a number and refuses it.
* **The route is checked against a known game.** `universal_poker` set up as Leduc (6 cards, one
  private card, one board card, raises of 2 then 4, at most two per round) has the same 3,780
  decision histories, 936 infostates and seat values (−0.08536 / +0.08536) as `leduc_poker`.
* Card names are rank then suit (`2c` … `7s`); `numRanks=6` means ranks 2 to 7. Hands and boards
  are shown sorted, so the order cards are dealt in does not create extra infostates (checked
  by dealing the same cards in both orders).
* Each variant ran once with `--iterations 200`, under `/usr/bin/time -l` for wall time and peak
  memory, on an Apple M2 Max with 32 GB. D1 ran with `--iterations 0` under a memory watchdog
  instead. Some also ran with `--iterations 0` (enumeration only),
  which separates the time of one exact evaluation (section 4). The commands are in the
  appendix: prefix any with `/usr/bin/time -l` to reproduce the timings.

## 2. Results

"Histories" are decision histories and drive compute. "Infostates" are what direct mode
queries, so they drive API cost. No variant has forced decisions, so calls = infostates × N.
All are heads-up limit poker.

| | Variant | Histories | Infostates | Calls at N = 200 | × Leduc's calls | CFR+, 200 iterations | Peak memory |
|---|---|---|---|---|---|---|---|
| ref | Leduc as used (`leduc_poker(suit_isomorphism=True)`) | 774 | 288 | 57,600 | 1.00 | 0.32 s | 0.06 GB |
| ref | Leduc with suits distinguished (`leduc_poker`) | 3,780 | 936 | 187,200 | 3.25 | 1.56 s | 0.08 GB |
| A1 | Leduc's deck (3 ranks × 2 suits), one private card, one board card; blinds 2 and 1, small blind acts first, big blind first on the second street; bets of 2 then 4, at most two per street | 3,780 | 936 | 187,200 | 3.25 | 1.48 s | 0.14 GB |
| A2 | A1 with 6 ranks × 2 suits | 40,392 | 4,032 | 806,400 | 14.0 | 15.4 s | 0.90 GB |
| A3 | One private card, three streets (a board card on each of the last two), 4 ranks × 2 suits | 262,416 | 26,928 | 5,385,600 | 93.5 | 114.1 s | 5.8 GB |
| B1 | **Two** private cards, one board card on the second street, 4 ranks × 2 suits | 211,680 | 5,208 | 1,041,600 | 18.1 | 91.2 s | 4.4 GB |
| E1 | Two private cards from 4 ranks × 3 suits (12 cards), fixed flop `3c4d5h` **and a random turn card** (two streets); both post 1, Player 1 first, bets of 2 then 4, at most two per street | 471,744 | 7,776 | 1,555,200 | 27.0 | 177.0 s | 9.7 GB |
| C2 | Two private cards from 6 ranks × 4 suits (24 cards), fixed flop `5c6d7h`, one street; both post 1, Player 1 first, bets of 2, **at most one** bet | 574,560 | 840 | 168,000 | 2.92 | 229.7 s | 10.6 GB |
| C1 | C2 with **at most two** bets | 861,840 | 1,260 | 252,000 | 4.38 | 342.1 s | 13.7 GB |
| C3 | C2 with **at most three** bets | 1,149,120 | 1,680 | 336,000 | 5.83 | 409.7 s | 14.1 GB |
| C4 | C1 on a fixed five-card board `5c6d7h2s4s` (a river subgame) | 558,144 | 1,026 | 205,200 | 3.56 | 212.7 s | 10.9 GB |
| D1 | C1 with the **full 52-card deck**, fixed flop `7c8d9h` | did not finish | | | | | killed past 16.1 GB |

"× Leduc's calls" is the call count divided by 57,600 (Leduc as this project runs it). Peak
memory is in GB of 10⁹ bytes. A2, A3 and B1 use A1's blinds, bets and caps (A3: bets of 2, 4,
4). Every variant that finished was also solved: `game_size.py` computes the exact
exploitability of the CFR+ average policy with OpenSpiel's `exploitability` (0.00022 to 0.028
chips after 200 iterations; seat values are in the appendix). So exact best response works for
all of them. The question is cost.

## 3. What drives the sizes

* **Distinct suits.** `universal_poker` has no suit-isomorphism option. Leduc shows the price:
  288 infostates with suits merged, 936 with suits distinguished. A1 is Leduc with blinds, so it
  lands on 936, not 288.
* **Two private cards.** Going from one private card to two multiplies the hands each player
  can hold. B1, with two private cards from only 8 cards, has 5,208 infostates, more than A2's
  4,032 with one private card from 12. Each extra street multiplies again by the board cards
  that can arrive and the betting lines that reach it: A3 adds a third street to a one-card game
  and has 26,928. E1 keeps a fixed flop but deals a turn card during play, on a 12-card deck,
  and has 7,776.
* **Fixed board, one street.** The C variants have no chance event during play, so each
  infostate is just "my two cards + the betting so far": 840 to 1,680 infostates. But in C1
  each infostate stands for 684 histories (861,840 ÷ 1,260). Those are the opponent's 171
  possible hands, times the 4 orders in which the two players' cards can be dealt. So the C
  variants have the fewest infostates but the most histories, and the most memory and time.
* **Raise cap.** Each extra allowed bet adds one decision point per player per hand, 420
  infostates here: C2 → C1 → C3 is 840 → 1,260 → 1,680.

## 4. Compute: fits, but the fixed-board games are heavy

* **Equilibrium.** `run_benchmark.py` solves the reference with 2,000 CFR+ iterations (cached
  after the first run). At the measured 200-iteration times, that is roughly 10 times longer:
  about 57 min for C1, 38 min for C2, 15 min for B1, under 20 s for A1.
* **One exact evaluation.** Wall time with 200 iterations, minus enumeration-only wall time,
  minus the CFR+ time. This leaves converting the policy, computing its value and computing its
  exploitability: **C1 43.2 s**, A3 11.2 s, B1 8.8 s, A2 1.45 s.
* **A run's bootstrap.** A sampled run calls `compute_metrics` once for the point estimate and
  once per bootstrap replicate (200 by default, `--bootstrap`). Each call does more than one
  evaluation: two best-response values, `exploitability` (two more best responses), and two
  exact seat values. For C1 that is at least 201 × 43 s ≈ 2.4 hours of analysis per run, and
  probably several times that. This is an estimate from the measured 43 s, not a measurement.
  A mock-subject run on the chosen variant would measure it.
* **C++ best response.** These best responses run in Python. OpenSpiel also offers C++ best
  responses (`nash_conv(..., use_cpp_br=True)`, `CPPBestResponsePolicy`), which nothing in the
  repo uses. Switching would be a change in `analysis/` that needs its own sanity tests, and its
  speed-up on these games is not measured.
* **Memory.** Peak memory was 12 to 22 KB per history in every variant with more than 40,000
  histories (peak bytes ÷ histories from the table). `game_size.py` holds every decision history
  in memory, and so do the pipeline's `enumerate_infostates` and OpenSpiel's
  `BestResponsePolicy`. So the table is a fair guide to a run's memory, though not a measurement
  of one.
* **D1 did not finish.** On the 52-card deck, `game_size.py` was killed while still
  enumerating, about 3.5 minutes in, in both attempts. The watchdog's 20 GB cap never fired. The
  second attempt recorded signal 9 (exit status 137), so the kill came from macOS, presumably
  for memory. The highest memory seen was 11.5 GB and 16.1 GB, sampled every 2 s, so the real
  peaks were higher. Full-deck subgames are past this machine with the current Python
  enumeration.
* The local GUI counts exactly, enumerates infostates (explorer, hints) and computes
  best-response values only up to 200,000 decision nodes (`apps/gui/sbgui/catalog.py`). B1, E1
  and every C variant are past that.

## 5. API cost: the binding limit

No call was made. To put dollars on the call counts, I scaled tonight's Leduc dry runs
(`scripts/run_benchmark.py --game leduc --model <name> --samples 200 --dry-run`). They give
$22.87 for Claude Haiku 4.5 and $6.57 for DeepSeek Flash, before retries, for 57,600 calls. The
scale factor is the "× Leduc's calls" column. A Hold'em prompt is longer than Leduc's (two cards
with suits, a board, more betting), so these figures are **probably too low**.

| | Infostates | Haiku, N = 200 | DeepSeek, N = 200 | Haiku, N = 50 |
|---|---|---|---|---|
| C2 | 840 | ≈ $67 | ≈ $19 | ≈ $17 |
| A1 | 936 | ≈ $74 | ≈ $21 | ≈ $19 |
| C4 | 1,026 | ≈ $81 | ≈ $23 | ≈ $20 |
| C1 | 1,260 | ≈ $100 | ≈ $29 | ≈ $25 |
| C3 | 1,680 | ≈ $133 | ≈ $38 | ≈ $33 |
| B1 | 5,208 | ≈ $414 | ≈ $119 | ≈ $103 |
| E1 | 7,776 | ≈ $617 | ≈ $177 | ≈ $154 |

Every measured variant with two private cards and a card dealt during play (B1, E1)
costs at least 18 times Leduc's calls. At N = 200 that is hundreds of dollars per model. Either
N drops, or the variant has no card dealt during play.

## 6. Decisions for you

1. **Which variant.** My recommendation is C1. C2 and C4 are cheaper. A1 is the cheapest to
   compute and keeps a card dealt during play, but it is Leduc with blinds. Two private cards
   plus a dealt street (B1, E1) cost about 18 times Leduc's calls or more.
2. **Which board** (C variants). A fixed-board subgame's numbers belong to that board. `5c6d7h`
   (rainbow, connected: straights possible, flushes not) was picked for measurement only. Each
   extra board is a separate game and a separate run.
3. **N and budget.** At N = 50, C1 costs about what Leduc does at N = 200 (scaled from the
   Leduc dry run, so probably low).
4. **Bootstrap replicates** for C variants, if the mock run shows 200 replicates take too long.
   This is the existing `--bootstrap` flag, a run setting rather than a code change, but it
   widens the interval estimates' own error.
5. **Whether to build a custom game later.** A custom OpenSpiel game could merge
   suit-equivalent infostates, as Leduc's `suit_isomorphism` does. That would make
   two-private-card games with a dealt street cheaper. It needs only a new game module (allowed
   by the generality rule), but its size is not measured here.

## 7. Not measured, or to keep in mind

* Single timing runs on one machine. A3's first run took 415.7 s of wall time for 123 s of CPU.
  A repeat took 127.7 s, and the table uses the repeat; both are in the appendix.
* Equilibrium times at 2,000 iterations are 10 × the 200-iteration time, not measured.
* Cost figures assume Leduc's tokens per call. Writing a Hold'em `GameSpec` and prompt would let
  the dry run give real figures.
* `universal_poker`'s "Player 1" is OpenSpiel's player 0. In A1 to A3 and B1 that is the big
  blind; in C1 to C4 and E1 both players post 1 and Player 1 acts first.
* No prompt, parser or `GameSpec` was written, so whether models can read these games
  reliably (card notation, the fixed board) is untested.

## Appendix: raw output

Every number above comes from this log (`scripts/game_size.py` output, with `/usr/bin/time -l`
wall time and peak memory in bytes), apart from the Leduc dry-run figures quoted in section 5.
Lines starting `###` are run labels. D1 ran under a small watchdog script instead of
`/usr/bin/time`. Its line says "finished" whenever the watchdog did not stop the process
itself; both D1 attempts were killed from outside, and only the second records the exit
status.

```
### REF leduc iso | iterations=200 | limit=600s
$ uv run python scripts/game_size.py "leduc_poker(suit_isomorphism=True)" --iterations 200
leduc_poker(suit_isomorphism=True)
  decision histories:       774
  decision infostates:      288 (Player 1: 144, Player 2: 144)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 57,600 (forced infostates are not queried)
  CFR+ 200 iterations:    0.32 s; seat values [-0.08536, 0.08536]; exploitability 0.005
        0.50 real         0.46 user         0.04 sys
            57409536  maximum resident set size
exit=0

### REF leduc | iterations=200 | limit=600s
$ uv run python scripts/game_size.py "leduc_poker" --iterations 200
leduc_poker
  decision histories:       3,780
  decision infostates:      936 (Player 1: 468, Player 2: 468)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 187,200 (forced infostates are not queried)
  CFR+ 200 iterations:    1.56 s; seat values [-0.08536, 0.08536]; exploitability 0.005
        1.83 real         1.79 user         0.04 sys
            77611008  maximum resident set size
exit=0

### U-LEDUC universal_poker Leduc | iterations=200 | limit=600s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=1 1,raiseSize=2 4,firstPlayer=1 1,maxRaises=2 2,numSuits=2,numRanks=3,numHoleCards=1,numBoardCards=0 1)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=1 1,raiseSize=2 4,firstPlayer=1 1,maxRaises=2 2,numSuits=2,numRanks=3,numHoleCards=1,numBoardCards=0 1)
  decision histories:       3,780
  decision infostates:      936 (Player 1: 468, Player 2: 468)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 187,200 (forced infostates are not queried)
  CFR+ 200 iterations:    1.54 s; seat values [-0.08536, 0.08536]; exploitability 0.005
        1.82 real         1.76 user         0.04 sys
           139395072  maximum resident set size
exit=0

### A1 one hole card, Leduc deck, blinds+position | iterations=200 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=3,numHoleCards=1,numBoardCards=0 1)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=3,numHoleCards=1,numBoardCards=0 1)
  decision histories:       3,780
  decision infostates:      936 (Player 1: 468, Player 2: 468)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.34, max 3
  direct-mode calls, N=200: 187,200 (forced infostates are not queried)
  CFR+ 200 iterations:    1.48 s; seat values [-0.09894, 0.09894]; exploitability 0.0034
        1.76 real         1.72 user         0.03 sys
           139362304  maximum resident set size
exit=0

### A2 one hole card, 6x2 deck | iterations=200 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=6,numHoleCards=1,numBoardCards=0 1)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=6,numHoleCards=1,numBoardCards=0 1)
  decision histories:       40,392
  decision infostates:      4,032 (Player 1: 2,016, Player 2: 2,016)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.34, max 3
  direct-mode calls, N=200: 806,400 (forced infostates are not queried)
  CFR+ 200 iterations:    15.39 s; seat values [-0.05437, 0.05437]; exploitability 0.0046
       17.29 real        17.12 user         0.16 sys
           903053312  maximum resident set size
exit=0

### A3 one hole card, 4x2 deck, three streets | iterations=200 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=3,blind=2 1,raiseSize=2 4 4,firstPlayer=2 1 1,maxRaises=2 2 2,numSuits=2,numRanks=4,numHoleCards=1,numBoardCards=0 1 1)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=3,blind=2 1,raiseSize=2 4 4,firstPlayer=2 1 1,maxRaises=2 2 2,numSuits=2,numRanks=4,numHoleCards=1,numBoardCards=0 1 1)
  decision histories:       262,416
  decision infostates:      26,928 (Player 1: 13,464, Player 2: 13,464)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 5,385,600 (forced infostates are not queried)
  CFR+ 200 iterations:    111.67 s; seat values [-0.17172, 0.17172]; exploitability 0.028
      415.66 real       123.05 user         2.81 sys
          5821923328  maximum resident set size
exit=0

### B1 two hole cards, 4x2 deck, one board card | iterations=200 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=4,numHoleCards=2,numBoardCards=0 1)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=4,numHoleCards=2,numBoardCards=0 1)
  decision histories:       211,680
  decision infostates:      5,208 (Player 1: 2,604, Player 2: 2,604)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.34, max 3
  direct-mode calls, N=200: 1,041,600 (forced infostates are not queried)
  CFR+ 200 iterations:    91.18 s; seat values [-0.11533, 0.11533]; exploitability 0.0044
      101.89 real       100.70 user         1.12 sys
          4417404928  maximum resident set size
exit=0

### C1 fixed flop, 6x4 deck, one street, cap 2 | iterations=200 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=2 2,numBoardCards=3 0,boardCards=5c6d7h)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=2 2,numBoardCards=3 0,boardCards=5c6d7h)
  decision histories:       861,840
  decision infostates:      1,260 (Player 1: 630, Player 2: 630)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 252,000 (forced infostates are not queried)
  CFR+ 200 iterations:    342.12 s; seat values [-0.06427, 0.06427]; exploitability 0.001
      392.96 real       379.69 user        11.79 sys
         13683736576  maximum resident set size
exit=0

### C2 fixed flop, 6x4 deck, one street, cap 1 | iterations=200 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=1 1,numBoardCards=3 0,boardCards=5c6d7h)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=1 1,numBoardCards=3 0,boardCards=5c6d7h)
  decision histories:       574,560
  decision infostates:      840 (Player 1: 420, Player 2: 420)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.00, max 2
  direct-mode calls, N=200: 168,000 (forced infostates are not queried)
  CFR+ 200 iterations:    229.74 s; seat values [-0.06512, 0.06512]; exploitability 0.00033
      258.15 real       253.02 user         5.02 sys
         10630529024  maximum resident set size
exit=0

### C3 fixed flop, 6x4 deck, one street, cap 3 | iterations=200 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=3 3,numBoardCards=3 0,boardCards=5c6d7h)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=3 3,numBoardCards=3 0,boardCards=5c6d7h)
  decision histories:       1,149,120
  decision infostates:      1,680 (Player 1: 840, Player 2: 840)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.50, max 3
  direct-mode calls, N=200: 336,000 (forced infostates are not queried)
  CFR+ 200 iterations:    409.68 s; seat values [-0.06413, 0.06413]; exploitability 0.0013
      481.40 real       464.93 user        13.95 sys
         14072709120  maximum resident set size
exit=0

### C4 fixed five-card board, 6x4 deck, one street, cap 2 | iterations=200 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=2 2,numBoardCards=5 0,boardCards=5c6d7h2s4s)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=2 2,numBoardCards=5 0,boardCards=5c6d7h2s4s)
  decision histories:       558,144
  decision infostates:      1,026 (Player 1: 513, Player 2: 513)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 205,200 (forced infostates are not queried)
  CFR+ 200 iterations:    212.69 s; seat values [-0.02801, 0.02801]; exploitability 0.00022
      240.94 real       238.19 user         2.67 sys
         10917576704  maximum resident set size
exit=0

### C1 enumeration only | iterations=0 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=2 2,numBoardCards=3 0,boardCards=5c6d7h)" --iterations 0
universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=6,numHoleCards=2,maxRaises=2 2,numBoardCards=3 0,boardCards=5c6d7h)
  decision histories:       861,840
  decision infostates:      1,260 (Player 1: 630, Player 2: 630)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 252,000 (forced infostates are not queried)
        7.66 real         6.99 user         0.66 sys
          6589792256  maximum resident set size
exit=0

### B1 enumeration only | iterations=0 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=4,numHoleCards=2,numBoardCards=0 1)" --iterations 0
universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=4,numHoleCards=2,numBoardCards=0 1)
  decision histories:       211,680
  decision infostates:      5,208 (Player 1: 2,604, Player 2: 2,604)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.34, max 3
  direct-mode calls, N=200: 1,041,600 (forced infostates are not queried)
        1.95 real         1.77 user         0.16 sys
          1696808960  maximum resident set size
exit=0

### A3 enumeration only | iterations=0 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=3,blind=2 1,raiseSize=2 4 4,firstPlayer=2 1 1,maxRaises=2 2 2,numSuits=2,numRanks=4,numHoleCards=1,numBoardCards=0 1 1)" --iterations 0
universal_poker(betting=limit,numPlayers=2,numRounds=3,blind=2 1,raiseSize=2 4 4,firstPlayer=2 1 1,maxRaises=2 2 2,numSuits=2,numRanks=4,numHoleCards=1,numBoardCards=0 1 1)
  decision histories:       262,416
  decision infostates:      26,928 (Player 1: 13,464, Player 2: 13,464)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 5,385,600 (forced infostates are not queried)
        2.45 real         2.24 user         0.20 sys
          2115616768  maximum resident set size
exit=0

### A3 repeat (timing check) | iterations=200 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=3,blind=2 1,raiseSize=2 4 4,firstPlayer=2 1 1,maxRaises=2 2 2,numSuits=2,numRanks=4,numHoleCards=1,numBoardCards=0 1 1)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=3,blind=2 1,raiseSize=2 4 4,firstPlayer=2 1 1,maxRaises=2 2 2,numSuits=2,numRanks=4,numHoleCards=1,numBoardCards=0 1 1)
  decision histories:       262,416
  decision infostates:      26,928 (Player 1: 13,464, Player 2: 13,464)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 5,385,600 (forced infostates are not queried)
  CFR+ 200 iterations:    114.07 s; seat values [-0.17172, 0.17172]; exploitability 0.028
      127.73 real       125.96 user         1.74 sys
          5832114176  maximum resident set size
exit=0

### A2 enumeration only | iterations=0 | limit=900s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=6,numHoleCards=1,numBoardCards=0 1)" --iterations 0
universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=2 1,raiseSize=2 4,firstPlayer=2 1,maxRaises=2 2,numSuits=2,numRanks=6,numHoleCards=1,numBoardCards=0 1)
  decision histories:       40,392
  decision infostates:      4,032 (Player 1: 2,016, Player 2: 2,016)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.34, max 3
  direct-mode calls, N=200: 806,400 (forced infostates are not queried)
        0.45 real         0.40 user         0.04 sys
           359612416  maximum resident set size
exit=0

### D1 fixed flop, full 52-card deck, one street, cap 2 | iterations=0 | memory cap=20 GB | limit=1800s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=13,numHoleCards=2,maxRaises=2 2,numBoardCards=3 0,boardCards=7c8d9h)" --iterations 0
watchdog: finished after 216 s; peak resident memory seen 11457 MB (sampled every 2 s)

### D1 repeat with exit status | iterations=0 | memory cap=20 GB | limit=1800s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=1,blind=1 1,raiseSize=2 2,firstPlayer=1 1,numSuits=4,numRanks=13,numHoleCards=2,maxRaises=2 2,numBoardCards=3 0,boardCards=7c8d9h)" --iterations 0
watchdog: finished after 208 s; exit status 137; peak resident memory seen 16112 MB (sampled every 2 s)

### E1 two hole cards, fixed flop + random turn, 4x3 deck | iterations=200 | limit=1800s
$ uv run python scripts/game_size.py "universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=1 1,raiseSize=2 4,firstPlayer=1 1,maxRaises=2 2,numSuits=3,numRanks=4,numHoleCards=2,numBoardCards=3 1,boardCards=3c4d5h)" --iterations 200
universal_poker(betting=limit,numPlayers=2,numRounds=2,blind=1 1,raiseSize=2 4,firstPlayer=1 1,maxRaises=2 2,numSuits=3,numRanks=4,numHoleCards=2,numBoardCards=3 1,boardCards=3c4d5h)
  decision histories:       471,744
  decision infostates:      7,776 (Player 1: 3,888, Player 2: 3,888)
  forced (1 legal action):  0 (0.0%)
  legal actions:            mean 2.33, max 3
  direct-mode calls, N=200: 1,555,200 (forced infostates are not queried)
  CFR+ 200 iterations:    176.96 s; seat values [-0.0439, 0.0439]; exploitability 0.0047
      201.17 real       198.80 user         2.22 sys
          9717383168  maximum resident set size
exit=0
```
