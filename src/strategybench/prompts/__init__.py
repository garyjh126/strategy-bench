"""Versioned per-game prompt templates."""

from strategybench.prompts.base import PromptTemplate
from strategybench.prompts.kuhn import KUHN_V1, KUHN_V1_PARA
from strategybench.prompts.leduc import LEDUC_V1, LEDUC_V1_PARA

DEFAULT_TEMPLATES: dict[str, PromptTemplate] = {"kuhn": KUHN_V1, "leduc": LEDUC_V1}

#: Every registered template by version, including robustness variants.
TEMPLATES: dict[str, PromptTemplate] = {
    t.version: t for base in (KUHN_V1, KUHN_V1_PARA, LEDUC_V1, LEDUC_V1_PARA) for t in (base, base.shuffled())
}


def get_template(game: str, version: str | None = None) -> PromptTemplate:
    """Default template for ``game``, or a specific version such as ``kuhn-v1-para+shuffled``."""
    if version is None:
        return DEFAULT_TEMPLATES[game]
    if version not in TEMPLATES or not version.startswith(game):
        raise KeyError(f"unknown prompt {version!r} for {game}; available: {sorted(TEMPLATES)}")
    return TEMPLATES[version]


__all__ = ["DEFAULT_TEMPLATES", "TEMPLATES", "PromptTemplate", "get_template"]
