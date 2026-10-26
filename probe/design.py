"""
The experimental design: which warm-ups and branches exist for a model and seed.

Fixed before any screen is run (see METHODS.md); change it only with a logged reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from probe import RESULTS

W_DEFAULT = 30  # warm-up rounds (state saved at round W)
H_DEFAULT = 10  # rounds played after the branch point
DEVIATIONS = {"full": [-0.30, -0.15, -0.05, 0.05, 0.15, 0.30], "lite": [-0.10, 0.10]}
SHAM_SEED_OFFSET = 1000  # sham "b" re-samples with a different seed: the noise floor
CUE_WTP = [3.5, 6.0]  # willingness-to-pay cue values (demand is unchanged)

# Scripted validation pairs: A reverts to p* at a known rate, B has a known mechanism.
BOT_P_STAR = 1.80
BOT_RHO = 0.5
BOT_PAIRS = {
    f"bot_{b}": {"Firm A": {"policy": "revert", "p_star": BOT_P_STAR, "rho": BOT_RHO},
                 "Firm B": {"policy": b, "p_star": BOT_P_STAR}}
    for b in ["anchor", "br", "br_infer", "match", "punish"]
}


ROOT_DIR = RESULTS  # run_screen --smoke points this at results/_smoke


def run_dir(model: str, seed: int, name: str) -> Path:
    """Output folder of one run: results/<model>/s<seed>/<name> (or results/_smoke/... in smoke mode)."""
    return ROOT_DIR / model / f"s{seed}" / name


def _base(model: str, seed: int, name: str, rounds: int) -> dict:
    spec = {"name": name, "out": str(run_dir(model, seed, name)), "seed": seed,
            "rounds": rounds, "model": model}
    if model in BOT_PAIRS:
        spec.update(agent_kind="bot", bots=BOT_PAIRS[model])
    else:
        spec.update(agent_kind="llm")
    return spec


def warmup_specs(model: str, seed: int, design: str = "full", W: int = W_DEFAULT) -> List[dict]:
    """Warm-up run specs for a model and seed (shown; hidden for the full design; WTP cues for 'cue')."""
    if design == "cue":  # METHODS 11a: the willingness-to-pay cue changed from round 1
        return [{**_base(model, seed, f"warmup_wtp{w}", W), "wtp": w} for w in CUE_WTP]
    specs = [_base(model, seed, "warmup_shown", W)]
    if design == "full":
        hidden = _base(model, seed, "warmup_hidden", W)
        hidden["hide"] = {"Firm A": 1, "Firm B": 1}
        specs.append(hidden)
    return specs


def branch_specs(model: str, seed: int, seeds: List[int], design: str = "full",
                 W: int = W_DEFAULT, H: int = H_DEFAULT) -> List[dict]:
    """Thread A branch specs: forced moves x visibility, shams, re-match, cue and notes branches."""
    parent = str(run_dir(model, seed, "warmup_shown") / "results.json")
    hide_b = {"Firm B": W + 1}

    def branch(name: str, *, force: Optional[float] = None, hidden: bool = False,
               seed_offset: int = 0, start_from: Optional[Dict[str, str]] = None,
               **extra) -> dict:
        s = _base(model, seed, name, W + H)
        s.update(seed=seed + seed_offset, branch_round=W,
                 start_from=start_from or {"Firm A": parent, "Firm B": parent})
        if force is not None:
            s["force"] = {"agent": "Firm A", "factor": round(1 + force, 4)}
        if hidden:
            s["hide"] = hide_b
        s.update(extra)
        return s

    specs = []
    for x in DEVIATIONS[design]:
        for hidden in (False, True):
            specs.append(branch(f"dev{round(x * 100):+d}_{'hidden' if hidden else 'shown'}",
                                force=x, hidden=hidden))
    specs += [branch("sham_shown_a"), branch("sham_shown_b", seed_offset=SHAM_SEED_OFFSET),
              branch("sham_hidden_a", hidden=True)]
    if design == "full":
        specs.append(branch("sham_hidden_b", hidden=True, seed_offset=SHAM_SEED_OFFSET))
        if len(seeds) > 1:
            other = seeds[(seeds.index(seed) + 1) % len(seeds)]
            specs.append(branch("rematch", start_from={
                "Firm A": parent,
                "Firm B": str(run_dir(model, other, "warmup_shown") / "results.json")}))
        specs += [branch(f"wtp{w}", wtp=w) for w in CUE_WTP]
        specs.append(branch("notes_wiped", wipe_notes=["Firm A", "Firm B"]))
    return specs


H_ENTRY = 30  # Thread B: rounds after entry (the learner needs time)
H_ADVICE = 20  # Thread C: rounds with advice
ADVICE_ARMS = {"adv_mono": "monopoly", "adv_nash": "nash", "adv_split": "split", "adv_hub": "hub"}


def extension_specs(model: str, seed: int, design: str, W: int = W_DEFAULT) -> List[dict]:
    """Thread B ("entry") and Thread C ("advice") branches from the same saved state."""
    from probe import economics as econ

    parent = str(run_dir(model, seed, "warmup_shown") / "results.json")
    H = H_ENTRY if design == "entry" else H_ADVICE

    def branch(name: str, **extra) -> dict:
        s = _base(model, seed, name, W + H)
        s.update(branch_round=W, start_from={"Firm A": parent, "Firm B": parent}, **extra)
        return s

    specs = [branch(f"long_sham_{design}")]
    if design == "entry":
        specs += [branch("entry_random", entrant={"policy": "random"}),
                  branch("entry_mw", entrant={"policy": "mw"})]
    else:
        pn, pm = round(econ.nash_price(), 2), round(econ.monopoly_price(), 2)
        fixed = {"monopoly": (pm, pm), "nash": (pn, pn), "split": (pn, pm)}
        for name, arm in ADVICE_ARMS.items():
            if arm == "hub":
                if model not in BOT_PAIRS:  # bots have no LLM to act as the hub
                    specs.append(branch(name, advice={"mode": "hub"}))
            else:
                a, b = fixed[arm]
                specs.append(branch(name, advice={"mode": "fixed",
                                                  "prices": {"Firm A": a, "Firm B": b}}))
    return specs


def n_calls(specs: List[dict]) -> int:
    """LLM calls: two LLM firms per round played (warm-ups play 1..W, branches W+1..W+H),
    plus one hub call per round in the hub-advisor arm."""
    total = 0
    for s in specs:
        if s["agent_kind"] != "llm":
            continue
        played = s["rounds"] - (s["branch_round"] if s.get("start_from") else 0)
        hub = 1 if (s.get("advice") or {}).get("mode") == "hub" else 0
        total += (2 + hub) * played
    return total


ELICIT_CONDITIONS = ["Rminus", "R1", "R2", "R2plus"]
H_WITHDRAWN = 20  # rounds after the instruction is withdrawn


def elicit_specs(model: str, seed: int, cond: str, W: int = W_DEFAULT,
                 H: int = H_DEFAULT) -> tuple[List[dict], List[dict]]:
    """Line D (METHODS 12): warm-up under condition `cond` with the message channel, then the
    pilot battery (+-15% forced price, shown / hidden, shams). Instructed conditions also get a
    branch in which the instruction is withdrawn (channel kept) for H_WITHDRAWN rounds."""
    tag = f"{model}__{cond}"

    def base(name: str, rounds: int, **extra) -> dict:
        s = _base(model, seed, name, rounds)
        s.update({"out": str(ROOT_DIR / tag / f"s{seed}" / name), "condition": cond, **extra})
        return s

    parent = str(ROOT_DIR / tag / f"s{seed}" / "warmup_shown" / "results.json")
    start = {"Firm A": parent, "Firm B": parent}

    def branch(name: str, *, force: Optional[float] = None, hidden: bool = False,
               seed_offset: int = 0, rounds: int = W + H, **extra) -> dict:
        s = base(name, rounds, branch_round=W, start_from=start, **extra)
        s["seed"] = seed + seed_offset
        if force is not None:
            s["force"] = {"agent": "Firm A", "factor": round(1 + force, 4)}
        if hidden:
            s["hide"] = {"Firm B": W + 1}
        return s

    warm = [base("warmup_shown", W)]
    branches = [branch("dev-15_shown", force=-0.15), branch("dev+15_shown", force=0.15),
                branch("dev-15_hidden", force=-0.15, hidden=True),
                branch("sham_shown_a"), branch("sham_shown_b", seed_offset=SHAM_SEED_OFFSET),
                branch("sham_hidden_a", hidden=True)]
    # every condition gets a withdrawn branch, so all end with the same channel-only prompt (C0)
    # and differ only in their history: the prompt-matched contrast for the D2 probe (METHODS log)
    branches.append(branch("withdrawn", rounds=W + H_WITHDRAWN, condition="C0"))
    return warm, branches


H_DESIGNED = 20  # Line E: rounds with the designed third firm


def designed_specs(model: str, seed: int, W: int = W_DEFAULT, long: bool = False) -> List[dict]:
    """Line E (METHODS 14): a designed third firm joins the saved duopoly at round W+1.
    long=True: the 40-round horizon check (sham, stubborn_both, stubborn_A only)."""
    from probe import economics as econ

    p_s = round(econ.nash_price_n(3), 2)
    parent = str(run_dir(model, seed, "warmup_shown") / "results.json")

    H = 2 * H_DESIGNED if long else H_DESIGNED
    suffix = "_h40" if long else ""

    def branch(name: str, **extra) -> dict:
        s = _base(model, seed, name + suffix, W + H)
        s.update(branch_round=W, start_from={"Firm A": parent, "Firm B": parent}, **extra)
        return s

    stubborn = {"policy": "stubborn", "p_s": p_s}
    if long:
        return [branch("long_sham_designed"), branch("stubborn_both", entrant=stubborn),
                branch("stubborn_A", entrant=stubborn, hide_edges={"Firm B": ["Firm C"]})]
    return [
        branch("long_sham_designed"),
        branch("stubborn_both", entrant=stubborn),
        branch("stubborn_A", entrant=stubborn, hide_edges={"Firm B": ["Firm C"]}),
        branch("stubborn_none", entrant=stubborn,
               hide_edges={"Firm A": ["Firm C"], "Firm B": ["Firm C"]}),
        branch("random_both", entrant={"policy": "random"}),
    ]
