"""
Scripted pricing agents with a known mechanism, used to validate the audit before it is
applied to LLMs.

Each bot receives exactly the prompt an LLM agent would receive (same template, same
memory window, same masking) and parses its MARKET DATA section, so the bots see only what
an LLM sees. Every decision is a function of the visible history alone, so a bot resumed
from a saved state behaves as if it had played the whole game.

Policies (p* is the bot's set point):
    anchor    always p*                                          -> attraction, no response
    revert    p* + rho (own last price - p*)                     -> deviator with known rho
    br        best response to the last rival price it has seen  -> myopic best response
    br_infer  as br, but infers a hidden rival price from its own quantity (demand channel)
    match     copy the last rival price it has seen              -> price matching (k=1, e=0)
    punish    Nash price for K rounds after seeing a cut, else p* -> punish-only (asymmetric)
"""

from __future__ import annotations

import ast
import re
from typing import Optional

from probe import economics as econ
from src.agents.base_agent import Agent

_ROUND = re.compile(r"Round (\d+)\n(.*?)(?=\nRound \d+\n|\Z)", re.S)
_FIELD = {
    "my_price": re.compile(r"- My price: ([-\d.]+)"),
    "quantity": re.compile(r"- My quantity sold: ([-\d.]+)"),
    "profit": re.compile(r"- My profit earned: ([-\d.]+)"),
}
_RIVAL = re.compile(r"- Competitor's prices: (\{.*?\})")


def parse_market_data(prompt: str) -> list[dict]:
    """Rows of the MARKET DATA section, oldest first. ``rival`` is None when hidden."""
    try:
        section = prompt.split("Section name: MARKET DATA (read-only)\n+++++++++++++++++++++\n", 1)[1]
        section = section.split("\n+++++++++++++++++++++", 1)[0]
    except IndexError:
        return []
    rows = []
    for m in _ROUND.finditer(section):
        body = m.group(2)
        row = {"round": int(m.group(1))}
        for k, rx in _FIELD.items():
            f = rx.search(body)
            row[k] = float(f.group(1)) if f else None
        r = _RIVAL.search(body)
        row["rival"] = min(ast.literal_eval(r.group(1)).values()) if r else None
        rows.append(row)
    return sorted(rows, key=lambda r: r["round"])


class ScriptedAgent(Agent):
    """A pricing agent with a known mechanism that reads the same prompt an LLM agent would."""
    def __init__(self, name: str, policy: str, p_star: float = 1.80, rho: float = 0.5,
                 punish_rounds: int = 3, tol: float = 0.02, prompt_template: str = "",
                 response_model=None, memory_length: int = 100, env_params: Optional[dict] = None,
                 logger=None):
        super().__init__(name=name, prefix=f"[scripted bot: {policy}]",
                         prompt_template=prompt_template, env_params=env_params, logger=logger)
        assert policy in {"anchor", "revert", "br", "br_infer", "match", "punish"}, policy
        self.policy = policy
        self.p_star = p_star
        self.rho = rho
        self.punish_rounds = punish_rounds
        self.tol = tol
        self.response_model = response_model
        self.memory_length = memory_length
        self.model_name = f"bot:{policy}"
        self.temperature = None
        self.is_remote = False

    @property
    def type(self) -> str:
        return "scripted_bot"

    def _last_seen_rival(self, rows: list[dict]) -> Optional[float]:
        seen = [r["rival"] for r in rows if r["rival"] is not None]
        return seen[-1] if seen else None

    def decide(self, rows: list[dict]) -> float:
        """Price for this round from the visible market history (oldest row first)."""
        if not rows:
            return self.p_star
        last = rows[-1]
        if self.policy == "anchor":
            return self.p_star
        if self.policy == "revert":
            gap = self.rho * (last["my_price"] - self.p_star)
            # prices are shown to 2 dp; snap home once the gap is below display precision
            return self.p_star if abs(gap) < 0.01 else self.p_star + gap
        if self.policy == "br":
            rival = self._last_seen_rival(rows)
            return self.p_star if rival is None else econ.best_response(round(rival, 4))
        if self.policy == "br_infer":
            rival = last["rival"]
            if rival is None:
                rival = econ.infer_rival_price(last["my_price"], last["quantity"])
            return econ.best_response(round(min(rival, 4.0), 4))
        if self.policy == "match":
            rival = self._last_seen_rival(rows)
            return self.p_star if rival is None else rival
        if self.policy == "punish":
            recent = [r["rival"] for r in rows[-self.punish_rounds:] if r["rival"] is not None]
            if any(p < self.p_star * (1 - self.tol) for p in recent):
                return econ.nash_price()
            return self.p_star
        raise ValueError(self.policy)

    async def act(self, prompt: str) -> dict:
        """Agent interface: parse the prompt, decide, and return the starter's result dict."""
        price = round(float(self.decide(parse_market_data(prompt))), 4)
        return {"agent_name": self.name,
                "content": {"observations": "", "plans": "", "insights": "",
                            "chosen_price": price}}
