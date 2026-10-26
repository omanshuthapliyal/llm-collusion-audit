"""
Line D2 (METHODS 13): residual-stream activations of a local Qwen2.5-7B-Instruct at the
decision point (last prompt token) for every logged Qwen call, and linear probes on them.

Prompts were not logged at call time, so they are rebuilt from each run's saved history with
the same code that produced them (the starter's PromptManager, the agent's system messages,
and the Line D channel section). Rounds 1..r-1 of a firm's saved history are exactly what its
prompt at round r was built from.

    # the starter environment plus torch / transformers / scikit-learn (not added to it)
    uv run --project starter/algorithmic-pricing-llms --with torch --with transformers \\
        --with accelerate --with scikit-learn python -m probe.activations extract
    ... python -m probe.activations probe
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from probe import RESULTS, ROOT

MODEL_DIR = ROOT / "models" / "Qwen2.5-7B-Instruct"
OUT = RESULTS / "activations"
LAYERS = [8, 14, 20, 26]
FIRMS = ["Firm A", "Firm B"]


def rebuild_prompts(run_dir: Path):
    """Yield (round, firm, messages) for every LLM call made in this run."""
    from probe.run_branch import build_agents
    from probe.branching import load_history
    from probe.elicit import channel_text
    from src.prompts.prompt_manager import PromptManager

    spec = json.loads((run_dir / "spec.json").read_text())
    hist = load_history(run_dir / "results.json", 10 ** 6)
    spec_local = {**spec, "agent_kind": "bot", "bots": {f: {"policy": "anchor"} for f in FIRMS}}
    agents = build_agents(spec_local, "replay")  # bots carry the same template and schema
    pm = PromptManager()
    first = 1 + (spec.get("branch_round") or 0)
    from probe.elicit import CONDITIONS
    from src.prompts.prompts import P1

    prefix = P1 + CONDITIONS[spec["condition"]] if spec.get("condition") else P1
    from probe.run_branch import AdvisedLLMAgent  # noqa: F401  (schema string as LLMAgent builds it)

    for r in range(first, spec["rounds"] + 1):
        for agent in agents:
            if agent.name not in hist or r not in hist[agent.name]:
                continue
            past = {k: v for k, v in hist[agent.name].items() if k < r}
            prompt = pm.generate_prompt(agent, past, r)
            if spec.get("condition"):
                prompt += channel_text({n: {k: v for k, v in h.items() if k < r}
                                        for n, h in hist.items()}, agent.name, r)
            schema = "Respond only with a JSON object with this schema:\n{\n" + "\n".join(
                f'  "{n}": {f.annotation.__name__}'
                for n, f in agent.response_model.model_fields.items()
                if f.json_schema_extra.get("in_answer", True)) + "\n}"
            yield r, agent.name, [{"role": "system", "content": schema},
                                  {"role": "system", "content": prefix},
                                  {"role": "user", "content": prompt}]


def runs_to_extract():
    """Qwen runs: Line D pilots (all) and emergent R0 warm-ups and shams."""
    for d in sorted(RESULTS.glob("qwen7b__*/s*/*")):
        if (d / "results.json").exists():
            yield d
    for d in sorted(RESULTS.glob("qwen7b/s*/*")):
        if d.name in ("warmup_shown", "sham_shown_a", "sham_hidden_a") and (d / "results.json").exists():
            yield d


def extract():
    """Run the local model over every rebuilt prompt and save last-token activations per run."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForCausalLM.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16).to("mps")
    model.eval()
    OUT.mkdir(parents=True, exist_ok=True)
    for run in runs_to_extract():
        tag = f"{run.parent.parent.name}__{run.parent.name}__{run.name}"
        path = OUT / f"{tag}.npz"
        if path.exists():
            continue
        rows, acts = [], []
        for r, firm, messages in rebuild_prompts(run):
            text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            ids = tok(text, return_tensors="pt").to("mps")
            with torch.no_grad():
                out = model(**ids, output_hidden_states=True)
            acts.append(np.stack([out.hidden_states[L][0, -1].float().cpu().numpy() for L in LAYERS]))
            rows.append((r, firm))
        np.savez_compressed(path, acts=np.array(acts, dtype=np.float32),
                            rounds=np.array([x[0] for x in rows]),
                            firms=np.array([x[1] for x in rows]))
        print(f"{tag}: {len(rows)} prompts", flush=True)


def load(tag_glob: str):
    """Load saved activations whose file stem matches a glob: {tag: (acts, rounds, firms)}."""
    out = {}
    for f in sorted(OUT.glob(f"{tag_glob}.npz")):
        z = np.load(f)
        out[f.stem] = (z["acts"], z["rounds"], z["firms"])
    return out


def probe():
    """METHODS 13: train R- vs R2 + R2plus on seed-0 warm-up rounds 6..30. Evaluate on
    held-out runs (the D1 branches of the same conditions, never seen in training), then
    score R1 and the emergent R0 runs."""
    from sklearn.linear_model import LogisticRegressionCV
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    data = load("*")

    def rows(tag, lo=None, hi=None):
        a, r, _ = data[tag]
        m = np.ones(len(r), bool) if lo is None else (r >= lo) & (r <= hi)
        return a[m]

    train_neg = ["qwen7b__Rminus__s0__warmup_shown"]
    train_pos = ["qwen7b__R2__s0__warmup_shown", "qwen7b__R2plus__s0__warmup_shown"]
    test_neg = [t for t in data if t.startswith("qwen7b__Rminus__") and t not in train_neg]
    test_pos = [t for t in data if (t.startswith("qwen7b__R2__") or t.startswith("qwen7b__R2plus__"))
                and t not in train_pos and not t.endswith("__withdrawn")]
    report = {"train": train_neg + train_pos, "held_out_neg": test_neg, "held_out_pos": test_pos,
              "layers": {}}
    for li, L in enumerate(LAYERS):
        neg = np.concatenate([rows(t, 6, 30)[:, li] for t in train_neg])
        pos = np.concatenate([rows(t, 6, 30)[:, li] for t in train_pos])
        X, y = np.concatenate([neg, pos]), np.r_[np.zeros(len(neg)), np.ones(len(pos))]
        clf = make_pipeline(StandardScaler(), LogisticRegressionCV(Cs=10, cv=5, max_iter=5000))
        clf.fit(X, y)
        hn = np.concatenate([rows(t)[:, li] for t in test_neg]) if test_neg else np.empty((0, X.shape[1]))
        hp = np.concatenate([rows(t)[:, li] for t in test_pos]) if test_pos else np.empty((0, X.shape[1]))
        auc = (float(roc_auc_score(np.r_[np.zeros(len(hn)), np.ones(len(hp))],
                                   clf.predict_proba(np.concatenate([hn, hp]))[:, 1]))
               if len(hn) and len(hp) else None)
        scores = {t: float(clf.predict_proba(a[:, li])[:, 1].mean()) for t, (a, _, _) in data.items()}
        report["layers"][L] = {"held_out_auroc": auc, "mean_score_by_run": scores}
    (OUT / "probe_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({L: v["held_out_auroc"] for L, v in report["layers"].items()}, indent=2))





def probe_matched():
    """Exploratory (METHODS change log, 25 Oct): prompt-matched contrast. All `withdrawn`
    branches end with the same channel-only prompt (C0), so they differ only in history.
    Train withdrawn-R2/R2plus (collusive history) vs withdrawn-R- (competitive history) on
    rounds 31..40, test on rounds 41..50 of the same runs (a within-run split: optimistic,
    flagged), then score withdrawn-R1 and the emergent R0 runs."""
    from sklearn.linear_model import LogisticRegressionCV
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    data = load("*")
    pos_t = ["qwen7b__R2__s0__withdrawn", "qwen7b__R2plus__s0__withdrawn"]
    neg_t = ["qwen7b__Rminus__s0__withdrawn"]

    def part(tags, lo, hi, li):
        out = []
        for t in tags:
            a, r, _ = data[t]
            out.append(a[(r >= lo) & (r <= hi)][:, li])
        return np.concatenate(out)

    report = {"note": "within-run time split; optimistic", "layers": {}}
    for li, L in enumerate(LAYERS):
        Xp, Xn = part(pos_t, 31, 40, li), part(neg_t, 31, 40, li)
        X, y = np.concatenate([Xp, Xn]), np.r_[np.ones(len(Xp)), np.zeros(len(Xn))]
        clf = make_pipeline(StandardScaler(), LogisticRegressionCV(Cs=10, cv=5, max_iter=5000))
        clf.fit(X, y)
        Tp, Tn = part(pos_t, 41, 50, li), part(neg_t, 41, 50, li)
        auc = float(roc_auc_score(np.r_[np.ones(len(Tp)), np.zeros(len(Tn))],
                                  clf.predict_proba(np.concatenate([Tp, Tn]))[:, 1]))
        scores = {t: float(clf.predict_proba(a[:, li])[:, 1].mean()) for t, (a, _, _) in data.items()
                  if t.endswith("withdrawn") or t.startswith("qwen7b__s")
                  or t.endswith("warmup_shown")}
        report["layers"][L] = {"time_split_auroc": auc, "mean_score_by_run": scores}
    (OUT / "probe_matched_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({L: v["time_split_auroc"] for L, v in report["layers"].items()}, indent=2))


if __name__ == "__main__":
    {"extract": extract, "probe": probe, "probe_matched": probe_matched}[sys.argv[1]]()
