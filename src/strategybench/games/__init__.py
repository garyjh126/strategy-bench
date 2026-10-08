"""Game registry wrapping OpenSpiel games (GameSpec: load string, infostate rendering, action parsing)."""

from strategybench.games.base import GameSpec
from strategybench.games.kuhn import KuhnSpec
from strategybench.games.leduc import LeducSpec
from strategybench.games.liars_dice import LiarsDiceSpec

_REGISTRY: dict[str, type[GameSpec]] = {spec.name: spec for spec in (KuhnSpec, LeducSpec, LiarsDiceSpec)}


def get_game_spec(name: str) -> GameSpec:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise KeyError(f"unknown game {name!r}; available: {sorted(_REGISTRY)}") from None


__all__ = ["GameSpec", "get_game_spec"]
