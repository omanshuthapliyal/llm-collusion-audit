"""
Model registry, prices and spend caps.

Prices are USD per 1M tokens (standard tier), read from developers.openai.com/api/docs/pricing
and openrouter.ai/api/v1/models on 25 Oct 2026. OpenRouter calls report their own cost, which
takes precedence over the table.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

# Hard caps on cumulative spend, read from the usage ledger before every call.
SPEND_CAPS_USD = {"openai": 48.0, "openrouter": 9.9}  # OT: OpenRouter $10 loaded for the final approved set (25 Oct)


@dataclass(frozen=True)
class ModelSpec:
    """One model: provider, id, USD prices per 1M tokens, temperature and extra request parameters."""
    key: str  # short name used in folder names
    provider: str  # "openai" | "openrouter"
    model_id: str
    price_in: float  # USD / 1M input tokens
    price_cached: float  # USD / 1M cached input tokens
    price_out: float  # USD / 1M output tokens (reasoning tokens bill as output)
    temperature: float = 1.0
    extra: Dict = field(default_factory=dict)  # extra request params
    reasoning: bool = False


MODELS: Dict[str, ModelSpec] = {
    m.key: m
    for m in [
        ModelSpec("gpt41mini", "openai", "gpt-4.1-mini", 0.40, 0.10, 1.60),
        ModelSpec(
            "gpt5mini", "openai", "gpt-5-mini", 0.25, 0.025, 2.00,
            extra={"reasoning_effort": "low"}, reasoning=True,
        ),
        ModelSpec(
            "gpt52", "openai", "gpt-5.2", 1.75, 0.175, 14.00,
            extra={"reasoning_effort": "low"}, reasoning=True,
        ),
        ModelSpec(
            # gpt-5.2 at medium effort through OpenRouter (OT, 25 Oct: spend the OpenRouter
            # credit on one pilot seed). Pinned to OpenAI as the host; same model as gpt52.
            "gpt52med", "openrouter", "openai/gpt-5.2", 1.75, 0.175, 14.00,
            extra={"extra_body": {"reasoning": {"effort": "medium"},
                                  "provider": {"order": ["OpenAI"], "allow_fallbacks": False},
                                  "usage": {"include": True}}},
            reasoning=True,
        ),
        ModelSpec(
            "qwen7b", "openrouter", "qwen/qwen-2.5-7b-instruct", 0.10, 0.10, 0.20,
            # Phala is the only host; pin it so the backend never changes mid-run.
            extra={"extra_body": {"provider": {"order": ["Phala"], "allow_fallbacks": False},
                                  "usage": {"include": True}}},
        ),
    ]
}

# Planning figures for the pre-sweep estimate (replaced by ledger data once runs exist).
EST_TOKENS_IN = 2500
EST_TOKENS_OUT = 300
EST_REASONING = 600  # low effort


def estimate_call_cost(spec: ModelSpec, n_calls: int,
                       tokens_out_total: Optional[float] = None) -> float:
    """Input at the planning figure (smoke prompts are too short to calibrate it); output,
    including reasoning, from the ledger when available."""
    tout = tokens_out_total or (EST_TOKENS_OUT + (EST_REASONING if spec.reasoning else 0))
    return n_calls * (EST_TOKENS_IN * spec.price_in + tout * spec.price_out) / 1e6
