"""
Run one warm-up or one branch from a JSON spec (one process per run; see branching.py).

    python -m probe.run_branch path/to/spec.json

Spec fields:
    name, out                 run name and exact output folder
    agent_kind                "llm" or "bot"
    model                     key in probe.config.MODELS (llm)
    bots                      {firm: {"policy": ..., **params}} (bot)
    seed                      sampling seed passed to the provider
    rounds                    last round to play (W for a warm-up, W+H for a branch)
    start_from                {firm: results.json} saved state per firm (None for a warm-up)
    branch_round              W: rounds <= W are copied from start_from
    force                     {"agent", "factor"}: in round W+1 the agent's price is set to
                              factor x the price it chose that round
    hide                      {firm: first round masked}
    wipe_notes                [firm, ...]
    wtp                       willingness-to-pay cue shown in the prompt (default 4.51)
    entrant                   {"policy": "mw" | "random", ...}: Firm C joins from round W+1
    advice                    {"mode": "fixed", "prices": {firm: p}} or {"mode": "hub"}
    condition                 Line D condition key in probe.elicit.CONDITIONS: adds the message
                              channel and the condition's sentences to the P1 prefix
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import probe  # noqa: F401  (sets sys.path and certificates)
from probe.bots import ScriptedAgent
from probe.branching import ProbeExperiment, load_history
from probe.config import MODELS
from probe.learners import EntrantAgent
from probe.providers import TrackedProvider

import src.agents.LLM_agent as llm_agent_module
from src.agents.LLM_agent import LLMAgent
from src.environment.calvano import CalvanoDemandEnvironment
from src.prompts.prompts import GENERAL_PROMPT, P1
from src.prompts.prompts_models import create_pricing_response_model

FIRMS = ["Firm A", "Firm B"]
ENV_PARAMS = {"a": 2.0, "alpha": 1.0, "c": 1.0}
DEFAULT_WTP = 4.51

# The starter retries a bad answer 15 times inside the agent and again in the round wrapper;
# cap both so a misbehaving model cannot run up hundreds of paid calls for one decision.
llm_agent_module.MAX_RETRIES = 4
ROUND_RETRIES = 3


class AdvisedLLMAgent(LLMAgent):
    """Starter LLMAgent whose prompt ends with the round's extra sections: the advisor's note
    (Thread C) and the competitor's messages (Line D)."""

    advice_text = ""
    channel_text = ""

    def build_messages(self, prompt: str) -> list[dict]:
        """Starter messages with the round's competitor messages and advisor note appended."""
        return super().build_messages(prompt + self.channel_text + self.advice_text)


def build_agents(spec: dict, run_name: str):
    """Agents for a spec: LLM firms (with channel or advice where set), bots, and any entrant."""
    cond = spec.get("condition")
    if cond:
        from probe.elicit import CONDITIONS, create_channel_response_model

        response_model = create_channel_response_model(spec.get("wtp", DEFAULT_WTP))
        prefix = P1 + CONDITIONS[cond]
    else:
        response_model = create_pricing_response_model(
            include_wtp=True, wtp_value=spec.get("wtp", DEFAULT_WTP), include_notes=True
        )
        prefix = P1
    common = dict(prompt_template=GENERAL_PROMPT, response_model=response_model,
                  memory_length=100, env_params=ENV_PARAMS)
    if spec["agent_kind"] == "bot":
        agents = [ScriptedAgent(firm, **spec["bots"][firm], **common) for firm in FIRMS]
    else:
        model = MODELS[spec["model"]]
        provider = TrackedProvider(model, run_name=run_name)
        cls = AdvisedLLMAgent if (spec.get("advice") or cond) else LLMAgent
        agents = [cls(firm, prefix=prefix, provider=provider, temperature=model.temperature,
                      seed=spec["seed"], **common) for firm in FIRMS]
    if spec.get("entrant"):
        agents.append(EntrantAgent("Firm C", seed=spec["seed"], **spec["entrant"], **common))
    return agents


def main(spec_path: str):
    """Run one warm-up or branch from its JSON spec."""
    spec = json.loads(Path(spec_path).read_text())
    out = Path(spec["out"])
    start_history = None
    force = None
    if spec.get("start_from"):
        W = spec["branch_round"]
        start_history = {firm: load_history(path, W)[firm] for firm, path in
                         spec["start_from"].items()}
        if spec.get("force"):
            f = spec["force"]
            force = {"agent": f["agent"], "round": W + 1, "factor": f["factor"]}
    agents = build_agents(spec, spec["name"])
    if spec.get("entrant"):
        # The starter's end-of-run SVG assumes every firm played every round; an entrant did
        # not, so skip that plot (the data files are unaffected).
        import src.experiment.experiment as experiment_module
        experiment_module.plot_experiment_svg = lambda **kwargs: None
    exp = ProbeExperiment(
        name=spec["name"],
        agents=agents,
        num_rounds=spec["rounds"],
        environment=CalvanoDemandEnvironment(name="Calvano Market",
                                             description="duopoly, Calvano 2020 demand"),
        experiment_dir=str(out),
        max_retries=ROUND_RETRIES,
        plot_every=0,
        seed=spec["seed"],
        summary_window=10,
        out_dir=out,
        start_history=start_history,
        force=force,
        hide=spec.get("hide"),
        wipe_notes=spec.get("wipe_notes", ()),
        advice=spec.get("advice"),
        hub_provider=(TrackedProvider(MODELS[spec["model"]], run_name=spec["name"])
                      if (spec.get("advice") or {}).get("mode") == "hub" else None),
        channel=bool(spec.get("condition")),
        hide_edges=spec.get("hide_edges"),
        probe_meta={"spec": spec},
    )
    asyncio.run(exp.run())


if __name__ == "__main__":
    main(sys.argv[1])
