"""
Algorithmic entrants for Thread B (a third firm joining an LLM duopoly at the branch point).

    mw       multiplicative weights over a price grid with full-information counterfactual
             profits and a decaying rate eta_t = lam * t^-beta, beta in (0, 1). Nisan & Zerah
             (arXiv 2606.01275) show this learner is domination-avoiding. It is also a
             no-regret learner, so against rivals whose prices do not respond it converges
             to its best response to them (Arunachaleswaran et al., arXiv 2409.03956).
    random   uniform draws on the same grid: the same price support without learning,
             a control in the spirit of Garra's random entrant (arXiv 2609.13037).
    stubborn always the designed price p_s (Line E: a stubborn agent in the sense of
             Friedkin & Johnsen 1990 and Acemoglu et al. 2013).

The entrant reads the same MARKET DATA text the LLM firms see, which lists every rival's
price, and keeps its weights in memory (a branch runs in one process).
"""

from __future__ import annotations

import ast
import re

import numpy as np

from probe import economics as econ
from probe.bots import parse_market_data
from src.agents.base_agent import Agent

GRID = np.round(np.linspace(1.30, 2.30, 15), 4)
_RIVALS = re.compile(r"- Competitor's prices: (\{.*?\})")


def last_rival_prices(prompt: str) -> tuple[float, ...] | None:
    """All rival prices in the newest MARKET DATA row of a prompt (None if hidden or absent)."""
    rows = parse_market_data(prompt)
    if not rows:
        return None
    section = prompt.split("Section name: MARKET DATA (read-only)", 1)[1]
    first_row = section.split("Round ", 2)[1]  # newest row comes first
    m = _RIVALS.search(first_row)
    return tuple(ast.literal_eval(m.group(1)).values()) if m else None


class EntrantAgent(Agent):
    """A non-LLM third firm: multiplicative weights, random, or stubborn pricing."""
    def __init__(self, name: str, policy: str, seed: int = 0, lam: float = 2.0,
                 beta: float = 0.5, p_s: float = 1.37, prompt_template: str = "",
                 response_model=None,
                 memory_length: int = 100, env_params=None, logger=None):
        super().__init__(name=name, prefix=f"[algorithmic entrant: {policy}]",
                         prompt_template=prompt_template, env_params=env_params, logger=logger)
        assert policy in {"mw", "random", "stubborn"}, policy
        self.policy = policy
        self.p_s = p_s
        self.lam, self.beta = lam, beta
        self.rng = np.random.default_rng(seed)
        self.log_w = np.zeros(len(GRID))
        self.t = 0
        self.response_model = response_model
        self.memory_length = memory_length
        self.model_name = f"entrant:{policy}"
        self.temperature = None
        self.is_remote = False

    @property
    def type(self) -> str:
        return "algorithmic_entrant"

    def _update(self, rivals: tuple[float, ...]):
        payoff = np.array([econ.profit_n(float(g), rivals) for g in GRID])
        top = payoff.max()
        reward = payoff / top if top > 0 else payoff
        self.t += 1
        self.log_w += self.lam * self.t ** (-self.beta) * reward

    def probs(self) -> np.ndarray:
        """Current mixed strategy over the price grid."""
        w = np.exp(self.log_w - self.log_w.max())
        return w / w.sum()

    async def act(self, prompt: str) -> dict:
        """Agent interface: update on the last observed rival prices, then draw a price."""
        if self.policy == "stubborn":
            return {"agent_name": self.name,
                    "content": {"observations": "", "plans": "", "insights": "",
                                "chosen_price": self.p_s, "mode_price": self.p_s}}
        rivals = last_rival_prices(prompt)
        if self.policy == "mw" and rivals:
            self._update(rivals)
        p = self.probs() if self.policy == "mw" else np.full(len(GRID), 1 / len(GRID))
        price = float(self.rng.choice(GRID, p=p))
        return {"agent_name": self.name,
                "content": {"observations": "", "plans": "", "insights": "",
                            "chosen_price": price, "mode_price": float(GRID[np.argmax(p)])}}
