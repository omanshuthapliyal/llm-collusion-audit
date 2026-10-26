"""
Counterfactual branches of a saved pricing game.

``ProbeExperiment`` subclasses the starter's ``Experiment`` (pre-existing,
``src/experiment/experiment.py``) and changes only what a branch needs:

* start from a saved history (rounds 1..W copied, flagged ``is_initial_history``) and play
  rounds W+1..W+H;
* force one firm's price for one round to ``factor`` x the price it chose that round (the
  LLM is still called, so its notes carry on; its choice is kept as ``intended_price``);
* hide the competitor's price from chosen firms, both in new rows and in the past rows they
  can see (so the hidden firm has no visible rival-price history at all);
* wipe a firm's PLANS / INSIGHTS at the branch point;
* add a third firm that was not in the saved state (Thread B: an algorithmic entrant);
* put a non-binding advisor recommendation in each firm's prompt (Thread C), either a fixed
  price per firm or a "hub" LLM that sees both firms' data and maximises their joint profit;
* open a private message channel between the firms (Line D, probe/elicit.py). Hiding the
  rival's price masks the price only; messages are still delivered.

Everything else (prompts, demand, rate limiting, storage format) is the starter's code.
Run one branch per process: the starter's logger is a process-wide singleton.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Dict, Iterable, Optional

from src.experiment.experiment import Experiment
from src.experiment.storage import StorageManager

_RIVAL_LINE = re.compile(r"^- Competitor's prices: .*\n", re.M)
_RIVAL_DICT = re.compile(r"^- Competitor's prices: (\{.*?\})\n", re.M)

ADVICE_TEXT = ("\nAdvisory note: a pricing advisor used by firms in this market recommends that "
               "you set your price to {price:.2f} this round. The recommendation is not binding.\n")
HUB_SYSTEM = ("You are a pricing advisor serving both firms that sell competing products in this "
              "market. Your goal is to maximise the two firms' combined profit. Based on the data, "
              "recommend one price that both firms should charge next round. Respond only with a "
              "JSON object: {\"recommended_price\": float}")
HUB_USER = ("Each firm's cost per unit is 1. No customer would pay more than 4.51.\n"
            "Recent market data for both firms:\n{data}")


def strip_rival(market_data: str) -> str:
    """Remove the competitor-price line from one round's market data."""
    return _RIVAL_LINE.sub("", market_data)


def strip_rivals(market_data: str, firms: Iterable[str]) -> str:
    """Remove only the named competitors from the price line (Line E: per-edge visibility)."""
    import ast

    m = _RIVAL_DICT.search(market_data)
    if not m:
        return market_data
    kept = {k: v for k, v in ast.literal_eval(m.group(1)).items() if k not in set(firms)}
    line = f"- Competitor's prices: {kept}\n" if kept else ""
    return market_data[:m.start()] + line + market_data[m.end():]


def load_history(results_json: Path, upto: int) -> Dict[str, Dict[int, dict]]:
    """Per-firm history from a run's ``results.json`` (keys become ints), rounds <= upto."""
    raw = json.loads(Path(results_json).read_text())
    return {
        name: {int(r): v for r, v in rounds.items() if int(r) <= upto}
        for name, rounds in raw.items()
    }


class ExactStorage(StorageManager):
    """Starter StorageManager writing to one exact folder (no timestamped subfolders)."""

    def __init__(self, path: Path, n_agents: int, logger=None):
        super().__init__(n_agents=n_agents, experiment_dir=str(path), logger=logger)
        self._exact = Path(path)

    def create_experiment_dir(self, experiment_name: str):
        """Use the exact output folder given at construction."""
        self.experiment_path = self._exact
        self.experiment_path.mkdir(parents=True, exist_ok=True)
        return self.experiment_path


class ProbeExperiment(Experiment):
    """The starter's Experiment, extended to restart from a saved state and apply one intervention."""
    def __init__(self, *args, out_dir: Path, start_history: Optional[Dict] = None,
                 force: Optional[dict] = None, hide: Optional[Dict[str, int]] = None,
                 wipe_notes: Iterable[str] = (), advice: Optional[dict] = None,
                 hub_provider=None, channel: bool = False,
                 hide_edges: Optional[Dict[str, list]] = None, probe_meta: Optional[dict] = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.storage = ExactStorage(out_dir, n_agents=len(self.agents), logger=self.logger)
        self.start_history = start_history or {}
        self.start_round = 1 + max((max(h) for h in self.start_history.values() if h), default=0)
        self.force = force  # {"agent", "round", "factor"}
        self.hide = hide or {}  # firm -> first round from which its view is masked
        self.wipe_notes = list(wipe_notes)
        self.advice = advice  # {"mode": "fixed", "prices": {firm: p}} | {"mode": "hub"}
        self.hub_provider = hub_provider
        self._round_advice: Dict[str, float] = {}
        self.channel = channel  # Line D: private message channel between the firms
        self.hide_edges = hide_edges or {}  # Line E: firm -> competitors whose price it cannot see
        self.probe_meta = probe_meta or {}

    async def run(self):
        """Load the saved history, apply masks and wipes, then play rounds start_round..num_rounds."""
        self._setup_experiment()
        self._load_start_history()
        meta = self.storage.load_metadata()
        meta["probe"] = {**self.probe_meta, "start_round": self.start_round, "force": self.force,
                         "hide": self.hide, "wipe_notes": self.wipe_notes,
                         "advice": self.advice, "channel": self.channel,
                         "hide_edges": self.hide_edges}
        self.storage.save_metadata(meta)
        for round_num in range(self.start_round, self.num_rounds + 1):
            self.logger.info(f"--- Round {round_num} ---")
            await self._run_round(round_num)
        self._finalize_experiment()

    def _load_start_history(self):
        last = self.start_round - 1
        for name, rounds in self.start_history.items():
            for r, entry in rounds.items():
                e = copy.deepcopy(entry)
                e["is_initial_history"] = True
                if name in self.hide and "market_data" in e:
                    e["market_data"] = strip_rival(e["market_data"])
                self.history[name][r] = e
            if name in self.wipe_notes and last in self.history[name]:
                self.history[name][last]["plans"] = "No previous plans."
                self.history[name][last]["insights"] = "No previous insights."

    async def _run_round(self, round_num: int):
        if self.advice:
            self._round_advice = await self._advise(round_num)
            for agent in self.agents:
                if agent.name in self._round_advice:
                    agent.advice_text = ADVICE_TEXT.format(price=self._round_advice[agent.name])
        if self.channel:
            from probe.elicit import channel_text

            for agent in self.agents:
                agent.channel_text = channel_text(self.history, agent.name, round_num)
        await super()._run_round(round_num)

    async def _advise(self, round_num: int) -> Dict[str, float]:
        if self.advice["mode"] == "fixed":
            return dict(self.advice["prices"])
        rows = []
        for r in range(max(1, round_num - 10), round_num):
            cells = [f"{n}: price {self.history[n][r]['chosen_price']:.2f}, quantity "
                     f"{self.history[n][r]['quantity']:.2f}, profit {self.history[n][r]['profit']:.2f}"
                     for n in self.history if r in self.history[n]]
            rows.append(f"Round {r}: " + "; ".join(cells))
        messages = [{"role": "system", "content": HUB_SYSTEM},
                    {"role": "user", "content": HUB_USER.format(data="\n".join(rows))}]
        price = self._last_hub_price
        try:
            raw = await self.hub_provider.complete(messages, self.hub_provider.spec.temperature,
                                                   self.seed)
            price = round(float(json.loads(raw)["recommended_price"]), 2)
        except Exception as e:  # keep the previous recommendation; logged for the record
            self.logger.warning(f"Hub advice failed in round {round_num}: {e}")
        self._last_hub_price = price
        return {a.name: price for a in self.agents if hasattr(a, "advice_text")}

    _last_hub_price = 1.92  # fallback only if the very first hub call fails

    def _store_agent_outputs(self, results, round_num) -> dict:
        prices = super()._store_agent_outputs(results, round_num)
        for name, p in self._round_advice.items():
            self.history[name][round_num]["advice"] = p
        f = self.force
        if f and f["round"] == round_num:
            entry = self.history[f["agent"]][round_num]
            intended = entry["chosen_price"]
            # Deviate from what the firm would have charged this round (Calvano-style).
            forced = round(f["factor"] * intended, 2)
            entry.update(intended_price=intended, chosen_price=forced, forced=True)
            prices[f["agent"]] = forced
            self.logger.info(f"Forced {f['agent']} price {intended} -> {forced}")
        return prices

    def _store_environment_outputs(self, round_num, prices, quantities, profits):
        super()._store_environment_outputs(round_num, prices, quantities, profits)
        for name, first in self.hide.items():
            if round_num >= first:
                e = self.history[name][round_num]
                e["market_data"] = strip_rival(e["market_data"])
        for name, hidden in self.hide_edges.items():
            e = self.history[name][round_num]
            e["market_data"] = strip_rivals(e["market_data"], hidden)
