# StrategyBench Play (local GUI)

A local web app for playing the project's games and inspecting strategies. You can sit at a
table against bots, see what the CFR profile would do in your situation, see what each action is
worth against the bot's actual policy, and browse a measured run's strategy next to the CFR
profile, situation by situation.

Nothing here calls a model. A run's measured strategy (`runs/<id>/strategy.json`) stands in for
the model that produced it. The app sits on top of the `strategybench` package and changes
nothing in it.

## Start it

```bash
uv run python apps/gui/server.py              # http://127.0.0.1:8765/
uv run python apps/gui/server.py --port 9000  # another port
uv run python apps/gui/server.py --runs-dir path/to/runs --verbose
```

Stop it with Ctrl+C. The server listens on 127.0.0.1 only.

## Screens

**Play: setup.** Choose a game, who sits in each seat, and the options.

* **Games.** The registered games (Kuhn, Leduc, Liar's Dice) use their `GameSpec`, so situations
  and actions read in plain language. Any turn-based OpenSpiel game string also works, for
  example `kuhn_poker(players=3)`; those games show OpenSpiel's own strings. A string with the
  same parameters as a registered game opens the registered game.
* **Seats.** Human, uniform random, the CFR profile, or a run's measured strategy. Run seats are
  offered only for registered games. Runs with fewer than 30 samples per situation are labelled
  as smoke tests, the same rule the site uses.
* **CFR profile box.** Whether the profile is ready, still being computed, or refused, and how to
  read it (see below).
* **Options.** How fast bots and chance move (instantly, with a pause, or one step per click);
  whether to show hidden information during a hand; whether bot-only tables deal the next hand
  automatically; an optional random seed.

**Play: table.** The seat strip shows each seat's running total and mean per hand. The main panel
is the current decision; below it is the hand's log, with chance odds and, once the hand is
over, each bot's full action distribution. The side panels are:

* **Coach.** The CFR profile's action probabilities in exactly your situation.
* **Best-response values** (two-player games). For each of your actions: the expected payoff
  of the whole hand if you take it and then best-respond, assuming the other seat keeps playing
  its policy and you know that policy. It weights the other seat's possible private
  information by how likely its policy makes it. This is the per-visit value used in
  `analysis/breakdown.py`.
* **Hand history.** The last 30 finished hands; "Export hands (JSON)" saves all of them.

**Explorer.** Every decision situation of a game, most likely first. Likelihood ("reach") is
the probability that the situation arises when every seat plays the selected run's strategy,
chance included, the same weighting the project uses for coverage. Without a run it uses the
CFR profile, or uniform play if there is no profile. Bars show the run's strategy and ticks show
the CFR profile. "Distance from CFR" is half the sum of absolute differences between the two
distributions (0 means identical, 1 means no overlap). Situations with a single legal action
are hidden unless you ask for them; shown, they say "forced" instead of a sample count, because
direct mode does not ask the subject there. Filter by seat or by text.

## Reading the numbers

* **Hidden information.** While a hand is in progress, a table with a human seat is shown from
  that human's point of view: events the seat cannot observe (an opponent's card) appear as
  placeholders, and bots' action probabilities are withheld because they depend on private
  information. Everything is revealed when the hand ends. "Show hidden" reveals it earlier.
  Tables without humans always show everything.
* **CFR profiles.** Registered two-player zero-sum games use the project's reference
  equilibrium: `solve_equilibrium` (OpenSpiel C++ CFR+, 2,000 iterations), cached in
  `runs/equilibria`. Other games get an OpenSpiel C++ CFR+ (two-player zero-sum) or vanilla CFR
  average policy, with 10⁸ / (decision nodes) iterations, clamped to between 100 and 2,000.
* **What a profile guarantees.** In two-player zero-sum games the CFR average strategy is an
  approximate Nash equilibrium, and the app shows its exploitability. With three or more players
  CFR has no Nash guarantee: only the empirical distribution of joint play converges, to a coarse
  correlated equilibrium. The app then shows NashConv, the total gain available to players
  deviating one at a time, and says plainly that there is no guarantee. See
  `docs/research/multiway.md` for why this matters.
* **Fallbacks are always reported.** If a run or profile has nothing for a situation (not
  measured, no valid samples, labels that do not match), the seat plays uniformly and the log or
  the explorer row says so.

## Limits

| What | Limit |
|---|---|
| Players | 1 to 8; turn-based games only (no simultaneous moves or internally sampled chance) |
| Exact counts of decision nodes and infostates | up to 200,000 decision nodes; larger games are estimated by random walks |
| CFR profile | up to 2,000,000 decision nodes; at most 2 long computations at a time |
| Explorer and best-response values | up to 200,000 decision nodes |
| Tables | 64 at a time, in memory (lost when the server stops); 5,000 hands per table |

A profile expected to take under 15 seconds starts as soon as its game is chosen. Longer ones
wait for "Compute now", show progress, and can be cancelled.

## Keyboard and links

Keys **1** to **9** choose an action, **S** steps a bot or chance move, **N** deals the next hand.
The address bar keeps the table (`?table=<id>`), so a reload returns to it while the server runs.
`?game=<ref>` preselects a game, `?coach=1` and `?hint=1` open the side panels, and `#explore`
opens the explorer.

## Files it writes

Only caches under the runs directory: `runs/gui_cache/profiles/` (CFR profiles as JSON, keyed
on game, method, iterations and OpenSpiel version) and `runs/equilibria/` (the registered games'
reference equilibria, shared with the rest of the project). Run directories are only read.

## Safety

The server binds to 127.0.0.1 and accepts API requests only from its own page: requests with
another `Host` or `Origin` are refused, which guards against DNS rebinding and cross-site
requests. Request bodies must be JSON and at most 64 KB. Pages are served with a
Content-Security-Policy that allows only the app's own files, and every piece of game text is
inserted as text, never as HTML. The page makes no external requests.

## JSON API

| Method and path | Purpose |
|---|---|
| `GET /api/games` | Registered games, example game strings, size limits |
| `POST /api/inspect` `{game}` | A game's facts, profile status, runs and seat kinds |
| `GET /api/profile?game=` | Profile status |
| `POST /api/profile/start` `{game}`, `POST /api/profile/cancel` `{game}` | Start or cancel a profile computation |
| `POST /api/sessions` `{game, seats, seed?, reveal?}` | New table; each seat is `{kind}` or `{kind: "run", run}` |
| `GET /api/sessions/<id>?reveal=1` | The table's current view |
| `POST /api/sessions/<id>/act` `{action, ply}` | A human move |
| `POST /api/sessions/<id>/step` `{ply}` | One chance event or bot move |
| `POST /api/sessions/<id>/next` `{hand}` | Deal the next hand |
| `GET /api/sessions/<id>/hint?ply=` | Best-response values at the human's decision |
| `GET /api/sessions/<id>/export` | Every finished hand as JSON |
| `GET /api/explore?game=&run=&player=&q=&forced=&offset=&limit=` | One page of explorer rows |

Moves carry the ply (or hand number) they were made for. A stale one gets `409`, so two browser
tabs cannot both act on the same decision.

## Tests

```bash
uv run pytest apps/gui/tests
```

They run in a few seconds, never touch the real `runs/` directory, and are also part of the
default `uv run pytest` (and so of CI). They cover game sizes against exact counts
(including Ganzfried's 288 decision nodes for three-player Kuhn), hidden information,
move validation, totals and export, run and profile fallbacks, best-response values against
values worked out by hand, explorer reach and paging, background solving with its cache and
cancellation, and the HTTP layer's same-origin and body checks.

## Layout

```
apps/gui/
  server.py        HTTP server: static files, routing, same-origin and body checks
  sbgui/app.py     the JSON API, independent of HTTP
  sbgui/catalog.py games, game strings and sizes
  sbgui/session.py tables: moves, hidden information, totals, export
  sbgui/policies.py what bot seats play (uniform, CFR profile, run strategy)
  sbgui/profiles.py CFR profiles in background processes, with an on-disk cache
  sbgui/hints.py   best-response values for two-player games
  sbgui/explorer.py explorer rows: reach, run against CFR profile
  sbgui/runs.py    reads runs/<id>/strategy.json (read-only)
  static/          the single page: index.html, app.js, style.css, theme.js
  tests/
```
