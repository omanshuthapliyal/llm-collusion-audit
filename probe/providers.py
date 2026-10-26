"""
Provider that logs token usage and cost for every call and enforces the spend caps.

Implements the starter's ``Provider`` interface (pre-existing, ``src/agents/llm_providers.py``)
so ``LLMAgent`` uses it unchanged. Every call appends one line to ``logs/usage.jsonl``; the
cumulative spend per provider is re-read from that ledger before each call, so the cap holds
across the parallel branch subprocesses (it can overshoot by at most the calls in flight).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from openai import (
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from probe import LOGS
from probe.config import SPEND_CAPS_USD, ModelSpec
from src.agents.llm_providers import FatalProviderError, Provider, strip_code_fence

LEDGER = LOGS / "usage.jsonl"
BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
KEY_ENV = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


class SpendLedger:
    """Append-only JSONL ledger; reads new lines incrementally to keep totals current."""

    def __init__(self, path: Path = LEDGER):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._offset = 0
        self.totals: dict[str, float] = {}

    def refresh(self) -> dict[str, float]:
        """Read ledger lines added since the last call; return cumulative cost per provider."""
        if not self.path.exists():
            return self.totals
        with open(self.path) as f:
            f.seek(self._offset)
            for line in f:
                if not line.endswith("\n"):
                    break  # partial line from a concurrent writer; read it next time
                rec = json.loads(line)
                self.totals[rec["provider"]] = self.totals.get(rec["provider"], 0.0) + rec["cost"]
                self._offset += len(line.encode())
        return self.totals

    def append(self, rec: dict):
        """Append one call record to the ledger."""
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")


class TrackedProvider(Provider):
    """OpenAI-compatible chat client for one ``ModelSpec``, with usage logging and caps."""

    def __init__(self, spec: ModelSpec, run_name: str = "", ledger: Optional[SpendLedger] = None):
        from poseidon_compute import llm_config

        llm_config._load()  # pre-existing: loads compute.env into os.environ
        key = os.environ.get(KEY_ENV[spec.provider])
        if not key:
            raise FatalProviderError(f"{KEY_ENV[spec.provider]} not set in compute.env")
        self.spec = spec
        self.name = spec.provider
        self.model_name = spec.model_id
        self.is_remote = True
        self.run_name = run_name
        self.ledger = ledger or SpendLedger()
        self._client = AsyncOpenAI(base_url=BASE_URLS[spec.provider], api_key=key)

    def _check_cap(self):
        spent = self.ledger.refresh().get(self.spec.provider, 0.0)
        cap = SPEND_CAPS_USD[self.spec.provider]
        if spent >= cap:
            raise FatalProviderError(
                f"Spend cap reached for {self.spec.provider}: ${spent:.2f} >= ${cap:.2f}"
            )

    def _cost(self, usage) -> float:
        reported = getattr(usage, "cost", None)  # OpenRouter reports its own cost
        if reported is not None:
            return float(reported)
        details = getattr(usage, "prompt_tokens_details", None)
        cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
        s = self.spec
        return (
            (usage.prompt_tokens - cached) * s.price_in
            + cached * s.price_cached
            + usage.completion_tokens * s.price_out
        ) / 1e6

    async def complete(self, messages, temperature, seed):
        """One chat call in JSON mode: checks the spend cap, logs usage and cost, returns the text."""
        self._check_cap()
        kwargs = dict(self.spec.extra)
        if seed is not None:
            kwargs["seed"] = seed
        t0 = time.time()
        try:
            response = await self._client.chat.completions.create(
                model=self.spec.model_id,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
                **kwargs,
            )
        except (NotFoundError, AuthenticationError, PermissionDeniedError, BadRequestError) as e:
            raise FatalProviderError(f"{self.spec.model_id}: {e}") from e
        except RateLimitError as e:
            if "insufficient_quota" in str(e) or "credit" in str(e).lower():
                raise FatalProviderError(f"{self.spec.model_id}: out of credit: {e}") from e
            raise  # ordinary rate limit: let the starter's retry loop back off
        usage = response.usage
        cdet = getattr(usage, "completion_tokens_details", None)
        pdet = getattr(usage, "prompt_tokens_details", None)
        self.ledger.append({
            "ts": round(t0, 2),
            "latency_s": round(time.time() - t0, 2),
            "run": self.run_name,
            "provider": self.spec.provider,
            "model": self.spec.model_id,
            "served_by": getattr(response, "provider", None),
            "tokens_in": usage.prompt_tokens,
            "tokens_cached": (getattr(pdet, "cached_tokens", 0) or 0) if pdet else 0,
            "tokens_out": usage.completion_tokens,
            "tokens_reasoning": (getattr(cdet, "reasoning_tokens", 0) or 0) if cdet else 0,
            "cost": round(self._cost(usage), 8),
        })
        if not response.choices:
            raise RuntimeError(f"{self.spec.model_id}: empty response")
        return strip_code_fence(response.choices[0].message.content or "")
