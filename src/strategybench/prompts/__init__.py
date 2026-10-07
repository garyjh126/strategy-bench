"""Versioned per-game prompt templates."""

from strategybench.prompts.base import PromptTemplate
from strategybench.prompts.kuhn import KUHN_V1

DEFAULT_TEMPLATES: dict[str, PromptTemplate] = {"kuhn": KUHN_V1}

__all__ = ["DEFAULT_TEMPLATES", "PromptTemplate"]
