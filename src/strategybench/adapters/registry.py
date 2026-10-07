"""Load subject definitions from ``models.yaml`` and build clients for them."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from strategybench.adapters.providers import AnthropicClient, GeminiClient, OpenAICompatibleClient


@dataclass
class ModelSpec:
    name: str
    provider: str
    model: str
    params: dict[str, Any] = field(default_factory=dict)
    price_input: float = 0.0  # USD per million tokens
    price_output: float = 0.0
    price_source: str = ""
    est_output_tokens: int = 5
    concurrency: int = 1
    rpm: float | None = None
    base_url: str | None = None
    key_env: str | None = None
    provider_name: str | None = None

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.price_input + output_tokens * self.price_output) / 1e6


def load_models(path: str | Path = "models.yaml") -> dict[str, ModelSpec]:
    raw = yaml.safe_load(Path(path).read_text())["models"]
    specs = {}
    for name, cfg in raw.items():
        price = cfg.get("price_per_mtok", {})
        specs[name] = ModelSpec(
            name=name,
            provider=cfg["provider"],
            model=cfg["model"],
            params=cfg.get("params", {}),
            price_input=float(price.get("input", 0.0)),
            price_output=float(price.get("output", 0.0)),
            price_source=cfg.get("price_source", ""),
            est_output_tokens=int(cfg.get("est_output_tokens", 5)),
            concurrency=int(cfg.get("concurrency", 1)),
            rpm=cfg.get("rpm"),
            base_url=cfg.get("base_url"),
            key_env=cfg.get("key_env"),
            provider_name=cfg.get("provider_name"),
        )
    return specs


def build_client(spec: ModelSpec):
    if spec.provider == "anthropic":
        return AnthropicClient(spec.model, spec.params, spec.rpm)
    if spec.provider == "gemini":
        return GeminiClient(spec.model, spec.params, spec.rpm)
    if spec.provider == "openai_compatible":
        if not spec.base_url:
            raise ValueError(f"{spec.name}: openai_compatible needs base_url")
        return OpenAICompatibleClient(
            spec.model,
            spec.params,
            spec.base_url,
            spec.key_env,
            spec.provider_name or "openai_compatible",
            spec.rpm,
        )
    raise ValueError(f"{spec.name}: unknown provider {spec.provider!r}")
