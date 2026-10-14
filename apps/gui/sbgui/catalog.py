"""Game catalogue: the registered StrategyBench games plus any turn-based OpenSpiel game string.

A ``GameEntry`` is what the rest of the app works with. When the game has a ``GameSpec``
(it is registered, or its OpenSpiel parameters match a registered game exactly) the spec's
plain-language rendering is used; otherwise the app falls back to OpenSpiel's own strings.

Game size decides what the app will do with a game. Decision nodes are counted exactly for
small games and otherwise estimated with Knuth's random-walk estimator (the mean, over random
root-to-leaf walks, of the summed products of branching factors), which costs milliseconds.
"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass

import pyspiel

from strategybench.games.base import GameSpec

#: Decision nodes up to which the tree is counted exactly (a few tenths of a second).
EXACT_COUNT_LIMIT = 200_000
#: Largest game (decision nodes) for which a CFR profile is computed.
SOLVE_LIMIT = 2_000_000
#: Largest game (decision nodes) whose infostates are enumerated in Python (explorer, hints).
ENUMERATE_LIMIT = 200_000
MAX_PLAYERS = 8
MAX_GAME_STRING = 200
_GAME_STRING = re.compile(r"^[A-Za-z0-9_]+(\([A-Za-z0-9_=,.() \-]*\))?$")


class GameError(ValueError):
    """The game string cannot be used (unknown, malformed or not turn-based)."""


def seat_name(player: int) -> str:
    return f"Player {player + 1}"


def canonical_key(game: pyspiel.Game) -> str:
    """Identity of a game: short name plus every parameter, defaults included."""
    params = game.get_parameters()
    inner = ",".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{game.get_type().short_name}({inner})"


def registered_specs() -> tuple[dict[str, GameSpec], str | None]:
    """Every registered GameSpec by name, discovered at runtime, plus an import error if any.

    Reads the package's private ``_REGISTRY``; a public ``list_games()`` would be cleaner.
    """
    try:
        import strategybench.games as games

        names = sorted(getattr(games, "_REGISTRY", {}))
        return {name: games.get_game_spec(name) for name in names}, None
    except Exception as e:  # a half-written game module must not take the app down
        return {}, f"{type(e).__name__}: {e}"


@dataclass
class GameSize:
    decision_nodes: float
    exact: bool
    #: Decision infostates per player (exact counts only).
    infostates: list[int] | None = None

    @property
    def solvable(self) -> bool:
        return self.decision_nodes <= SOLVE_LIMIT

    @property
    def enumerable(self) -> bool:
        return self.decision_nodes <= ENUMERATE_LIMIT

    def as_dict(self) -> dict[str, object]:
        finite = self.decision_nodes != float("inf")
        return {
            "decision_nodes": round(self.decision_nodes) if finite else None,
            "exact": self.exact,
            "infostates": self.infostates,
            "infostates_total": sum(self.infostates) if self.infostates else None,
            "solvable": self.solvable,
            "enumerable": self.enumerable,
            "solve_limit": SOLVE_LIMIT,
            "enumerate_limit": ENUMERATE_LIMIT,
        }


def estimate_decision_nodes(
    game: pyspiel.Game, rollouts: int = 500, seed: int = 0, cap: float = 1e10, time_budget: float = 0.5
) -> float:
    """Knuth's unbiased estimate of the number of decision nodes; ``inf`` if above ``cap``."""
    rng = random.Random(seed)
    total, done = 0.0, 0
    deadline = time.monotonic() + time_budget
    while done < rollouts and (done < 20 or time.monotonic() < deadline):
        state, weight, estimate = game.new_initial_state(), 1.0, 0.0
        while not state.is_terminal():
            if state.is_chance_node():
                outcomes = state.chance_outcomes()
                action = outcomes[rng.randrange(len(outcomes))][0]
                weight *= len(outcomes)
            else:
                legal = state.legal_actions()
                estimate += weight
                action = legal[rng.randrange(len(legal))]
                weight *= len(legal)
            if total + estimate > cap * rollouts:  # the mean must exceed the cap
                return float("inf")
            state.apply_action(action)
        total += estimate
        done += 1
    return total / done


def count_tree(game: pyspiel.Game, limit: int = EXACT_COUNT_LIMIT) -> GameSize | None:
    """Exact decision-node and per-player infostate counts, or None if the tree exceeds ``limit``."""
    nodes = 0
    infos: list[set[str]] = [set() for _ in range(game.num_players())]
    has_infostates = game.get_type().provides_information_state_string
    stack = [game.new_initial_state()]
    while stack:
        state = stack.pop()
        if state.is_terminal():
            continue
        if state.is_chance_node():
            stack.extend(state.child(a) for a, _ in state.chance_outcomes())
            continue
        nodes += 1
        if nodes > limit:
            return None
        if has_infostates:
            infos[state.current_player()].add(state.information_state_string())
        stack.extend(state.child(a) for a in state.legal_actions())
    return GameSize(nodes, True, [len(s) for s in infos] if has_infostates else None)


@dataclass
class GameEntry:
    #: Canonical identity (see ``canonical_key``).
    key: str
    #: What the client sends back to refer to this game: a registered name or a game string.
    ref: str
    load_string: str
    game: pyspiel.Game
    spec: GameSpec | None
    registered: bool
    title: str
    summary: str
    size: GameSize

    @property
    def num_players(self) -> int:
        return self.game.num_players()

    @property
    def two_player_zero_sum(self) -> bool:
        utility = self.game.get_type().utility
        return self.num_players == 2 and utility in (
            pyspiel.GameType.Utility.ZERO_SUM,
            pyspiel.GameType.Utility.CONSTANT_SUM,
        )

    @property
    def has_infostates(self) -> bool:
        return self.game.get_type().provides_information_state_string

    @property
    def unit(self) -> str:
        return self.spec.payoff_unit if self.spec else "payoff unit"

    @property
    def unit_size(self) -> float:
        return self.spec.unit_size if self.spec else 1.0

    def info(self) -> dict[str, object]:
        t = self.game.get_type()
        return {
            "ref": self.ref,
            "key": self.key,
            "load_string": self.load_string,
            "title": self.title,
            "summary": self.summary,
            "registered": self.registered,
            "has_spec": self.spec is not None,
            "players": self.num_players,
            "two_player_zero_sum": self.two_player_zero_sum,
            "utility": t.utility.name.lower().replace("_", "-"),
            "chance": t.chance_mode != pyspiel.GameType.ChanceMode.DETERMINISTIC,
            "perfect_information": t.information == pyspiel.GameType.Information.PERFECT_INFORMATION,
            "has_infostates": self.has_infostates,
            "unit": self.unit,
            "unit_size": self.unit_size,
            "size": self.size.as_dict(),
        }

    # Text for the board. Spec text when there is a spec, OpenSpiel's strings otherwise.

    def action_labels(self, state: pyspiel.State) -> dict[int, str]:
        if self.spec is not None:
            return self.spec.action_labels(state)
        player = state.current_player()
        return {a: state.action_to_string(player, a) for a in state.legal_actions()}

    def describe_chance(self, state: pyspiel.State, action: int) -> str:
        if self.spec is not None:
            return self.spec.describe_chance(state, action)
        return f"Chance: {state.action_to_string(pyspiel.PlayerId.CHANCE, action)}"

    def situation(self, state: pyspiel.State) -> tuple[str, bool]:
        """The current player's view and whether it is the spec's plain-language text."""
        if self.spec is not None:
            return self.spec.render_infostate(state), True
        player = state.current_player()
        t = self.game.get_type()
        parts = []
        if t.provides_observation_string:
            parts.append("Observation:\n" + state.observation_string(player))
        if t.provides_information_state_string:
            parts.append("Information state:\n" + state.information_state_string(player))
        if not parts:
            parts.append(str(state))
        return "\n\n".join(parts), False

    def short_label(self, state: pyspiel.State) -> str:
        if self.spec is not None:
            return self.spec.short_label(state)
        return state.information_state_string()

    def observers(self, state: pyspiel.State, action: int) -> list[int]:
        """Players who can tell ``action`` apart from the alternatives at ``state``.

        Generic test: a player observes the event if their information state after it
        differs from their information state after some other outcome. When OpenSpiel cannot
        say (no information-state strings), the event is treated as public.
        """
        players = list(range(self.num_players))
        if state.is_chance_node():
            alternatives = [a for a, _ in state.chance_outcomes()]
        else:
            alternatives = state.legal_actions()
        if len(alternatives) <= 1 or not self.has_infostates:
            return players
        after = {a: state.child(a) for a in alternatives}
        seen = []
        for p in players:
            try:
                mine = after[action].information_state_string(p)
                if any(after[b].information_state_string(p) != mine for b in alternatives if b != action):
                    seen.append(p)
            except Exception:  # some games cannot describe terminal or chance states
                seen.append(p)
        return seen


class Catalog:
    """Resolves game references to cached ``GameEntry`` objects."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, GameEntry] = {}
        self._ref_keys: dict[str, str] = {}
        self.specs, self.registry_error = registered_specs()
        self._spec_by_key: dict[str, tuple[str, GameSpec]] = {}
        for name, spec in self.specs.items():
            try:
                self._spec_by_key[canonical_key(spec.load())] = (name, spec)
            except pyspiel.SpielError:
                continue

    def registered(self) -> list[GameEntry]:
        return [self.resolve(name) for name in self.specs]

    def resolve(self, ref: str) -> GameEntry:
        if not isinstance(ref, str) or not ref.strip():
            raise GameError("choose a game")
        ref = ref.strip()
        with self._lock:
            known = self._ref_keys.get(ref)
            if known is not None:
                return self._entries[known]
        if ref in self.specs:
            spec = self.specs[ref]
            game = spec.load()
        else:
            game = self._load_custom(ref)
        key = canonical_key(game)
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            entry = self._build(key, game)
        with self._lock:
            entry = self._entries.setdefault(key, entry)
            self._ref_keys[ref] = key
            return entry

    @staticmethod
    def _load_custom(text: str) -> pyspiel.Game:
        if len(text) > MAX_GAME_STRING or not _GAME_STRING.match(text):
            raise GameError(
                "not a game string: use an OpenSpiel name with optional parameters, "
                "for example kuhn_poker(players=3)"
            )
        try:
            game = pyspiel.load_game(text)
        except pyspiel.SpielError as e:
            reason = str(e).split(" Available games are:")[0].strip()
            raise GameError(f"OpenSpiel could not load {text!r}: {reason}") from None
        t = game.get_type()
        if t.dynamics != pyspiel.GameType.Dynamics.SEQUENTIAL:
            raise GameError(f"{t.short_name} is not turn-based (simultaneous or mean-field moves)")
        if t.chance_mode == pyspiel.GameType.ChanceMode.SAMPLED_STOCHASTIC:
            raise GameError(f"{t.short_name} samples chance internally, so its odds cannot be shown")
        if not 1 <= game.num_players() <= MAX_PLAYERS:
            raise GameError(f"between 1 and {MAX_PLAYERS} players are supported")
        return game

    def _build(self, key: str, game: pyspiel.Game) -> GameEntry:
        registered = self._spec_by_key.get(key)
        if registered is not None:
            name, spec = registered
            ref, load_string, title, summary = name, spec.load_string, spec.title or name, spec.summary
        else:
            spec = None
            ref = load_string = str(game)
            title = load_string
            summary = game.get_type().long_name
        size = count_tree(game) if estimate_decision_nodes(game) <= 2 * EXACT_COUNT_LIMIT else None
        if size is None:
            size = GameSize(estimate_decision_nodes(game, rollouts=2000, time_budget=1.0), exact=False)
        return GameEntry(
            key=key,
            ref=ref,
            load_string=load_string,
            game=game,
            spec=spec,
            registered=registered is not None,
            title=title,
            summary=summary,
            size=size,
        )
