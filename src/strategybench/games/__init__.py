"""Game registry wrapping OpenSpiel games (GameSpec: load string, infostate rendering, action parsing)."""

from strategybench.games.base import GameSpec
from strategybench.games.kuhn import KuhnSpec

_REGISTRY: dict[str, type[GameSpec]] = {KuhnSpec.name: KuhnSpec}


def get_game_spec(name: str) -> GameSpec:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise KeyError(f"unknown game {name!r}; available: {sorted(_REGISTRY)}") from None


__all__ = ["GameSpec", "get_game_spec"]
