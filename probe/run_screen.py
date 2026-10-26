"""
Run a sweep: warm-ups first, then all branches, each in its own subprocess.

    python -m probe.run_screen --model gpt41mini --seeds 0 1 2            # full design
    python -m probe.run_screen --model gpt52 --seeds 0 1 2 --design lite
    python -m probe.run_screen --model bot_match --seeds 0               # free, no API

Prints the number of LLM calls and the estimated cost. A paid sweep starts only if
--approved-usd is given and the estimate does not exceed it (the amount OT approved).
Finished runs (metadata with a summary) are skipped, so a sweep can be resumed. Every sweep appends one line with its actual cost to logs/sweep_log.txt.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

from probe import LOGS, RESULTS, ROOT
from probe import design
from probe.config import MODELS, estimate_call_cost
from probe.design import (BOT_PAIRS, ELICIT_CONDITIONS, H_DEFAULT, W_DEFAULT, branch_specs,
                          designed_specs, elicit_specs, extension_specs, n_calls,
                          warmup_specs)


def is_done(spec: dict) -> bool:
    """True if the run's metadata already holds an end-of-run summary."""
    meta = Path(spec["out"]) / "metadata.json"
    return meta.exists() and "summary" in json.loads(meta.read_text())


def ledger_rates(model_id: str):
    """Mean tokens per call for a model from the ledger, if there is enough data."""
    path = LOGS / "usage.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows = [r for r in rows if r["model"] == model_id]
    if len(rows) < 20:
        return None
    n = len(rows)
    return (sum(r["tokens_in"] for r in rows) / n, sum(r["tokens_out"] for r in rows) / n,
            sum(r["cost"] for r in rows) / n)


def sweep_cost(model_id, since: float, run_names: list[str]) -> float:
    """Cost of this sweep's calls: ledger rows for this model, run names, since t0."""
    path = LOGS / "usage.jsonl"
    if model_id is None or not path.exists():
        return 0.0
    names = set(run_names)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return sum(r["cost"] for r in rows
               if r["model"] == model_id and r["ts"] >= since and r["run"] in names)


async def run_all(specs: list[dict], concurrency: int, tag: str) -> list[str]:
    """Run specs as subprocesses with bounded concurrency; return the folders that failed."""
    sem = asyncio.Semaphore(concurrency)
    failures = []

    async def one(spec):
        async with sem:
            out = Path(spec["out"])
            out.mkdir(parents=True, exist_ok=True)
            spec_path = out / "spec.json"
            spec_path.write_text(json.dumps(spec, indent=2))
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "probe.run_branch", str(spec_path), cwd=str(ROOT),
                stdout=asyncio.subprocess.DEVNULL, stderr=open(out / "stderr.txt", "w"))
            code = await proc.wait()
            status = "ok" if code == 0 and is_done(spec) else f"FAILED (exit {code})"
            print(f"  [{tag}] {Path(spec['out']).relative_to(ROOT)}: {status}", flush=True)
            if status != "ok":
                failures.append(spec["out"])

    await asyncio.gather(*(one(s) for s in specs))
    return failures


def main():
    """CLI: build the sweep, print calls and estimated cost, enforce the approval gate, run, log."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, choices=[*MODELS, *BOT_PAIRS])
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--design", choices=["full", "lite", "entry", "advice", "cue", "elicit",
                                         "designed"],
                    default="full",
                    help="full / lite: Thread A; entry: Thread B; advice: Thread C; "
                         "cue: warm-ups with the willingness-to-pay cue changed from round 1")
    ap.add_argument("--W", type=int, default=W_DEFAULT)
    ap.add_argument("--H", type=int, default=H_DEFAULT)
    ap.add_argument("--only", nargs="*", help="run only branches with these names")
    ap.add_argument("--conditions", nargs="+", choices=ELICIT_CONDITIONS,
                    default=ELICIT_CONDITIONS, help="Line D conditions (--design elicit)")
    ap.add_argument("--warmups-only", action="store_true")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--long", action="store_true", help="Line E 40-round horizon check")
    ap.add_argument("--smoke", action="store_true",
                    help="write under results/_smoke (kept out of the analysis)")
    ap.add_argument("--approved-usd", type=float, default=None,
                    help="cost OT approved for this sweep; required for paid models")
    args = ap.parse_args()
    if args.smoke:
        design.ROOT_DIR = RESULTS / "_smoke"

    extension = args.design in ("entry", "advice")
    if args.design == "elicit":
        pairs = [elicit_specs(args.model, seed, c, args.W, args.H)
                 for seed in args.seeds for c in args.conditions]
        warm = [s for w, _ in pairs for s in w]
        branches = [] if args.warmups_only else [s for _, b in pairs for s in b]
    else:
        warm = [s for seed in args.seeds
                for s in warmup_specs(args.model, seed, "lite" if extension else args.design,
                                      args.W)]
        if args.warmups_only or args.design == "cue":
            branches = []
        elif args.design == "designed":
            branches = [s for seed in args.seeds
                        for s in designed_specs(args.model, seed, args.W, long=args.long)]
        elif extension:
            branches = [s for seed in args.seeds
                        for s in extension_specs(args.model, seed, args.design, args.W)]
        else:
            branches = [s for seed in args.seeds
                        for s in branch_specs(args.model, seed, args.seeds, args.design,
                                              args.W, args.H)]
    if args.only:
        branches = [s for s in branches if s["name"] in args.only]
    todo_w = [s for s in warm if not is_done(s)]
    todo_b = [s for s in branches if not is_done(s)]
    calls = n_calls(todo_w + todo_b)

    is_bot = args.model in BOT_PAIRS
    usd = 0.0
    if is_bot:
        est = "free (scripted bots, no API calls)"
    else:
        spec = MODELS[args.model]
        rates = ledger_rates(spec.model_id)
        if rates:
            usd = estimate_call_cost(spec, calls, tokens_out_total=rates[1])
            est = (f"~${usd:.2f} ({rates[1]:.0f} output tokens per call from the ledger, "
                   f"input at the planning figure)")
        else:
            usd = estimate_call_cost(spec, calls)
            est = f"~${usd:.2f} (planning estimate, +/-50%)"
    print(f"Sweep: {args.model} | seeds {args.seeds} | design {args.design} | W={args.W} H={args.H}")
    print(f"  {len(todo_w)} warm-ups + {len(todo_b)} branches to run "
          f"({len(warm) - len(todo_w) + len(branches) - len(todo_b)} already done)")
    print(f"  {calls:,} LLM calls, estimated cost {est}")
    if not is_bot and calls and (args.approved_usd is None or usd > args.approved_usd):
        print(f"Not started: needs --approved-usd >= {usd:.2f} (OT's approval).")
        return

    t0 = dt.datetime.now(dt.timezone.utc)
    fails = asyncio.run(run_all(todo_w, args.concurrency, "warm-up"))
    if not fails:
        fails += asyncio.run(run_all(todo_b, args.concurrency, "branch"))
    else:
        print("Warm-ups failed; branches not started.")
    cost = sweep_cost(None if is_bot else MODELS[args.model].model_id, t0.timestamp(),
                      [s["name"] for s in todo_w + todo_b])
    line = (f"{t0.isoformat(timespec='seconds')} sweep {args.model} seeds={args.seeds} "
            f"design={args.design} W={args.W} H={args.H}{' SMOKE' if args.smoke else ''} runs={len(todo_w) + len(todo_b)} "
            f"planned_calls={calls} actual_cost=${cost:.4f} failures={len(fails)}")
    with open(LOGS / "sweep_log.txt", "a") as f:
        f.write(line + "\n")
    print(line)
    for path in fails:
        print(f"  see {path}/stderr.txt")


if __name__ == "__main__":
    main()
