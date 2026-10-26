"""
Consumer harm and the forced-cut remedy (post hoc, 25 Oct; no new model calls).

For every forced-cut branch with A's price visible, compare consumer surplus per round with the
matched sham over the 10-round branch. Report it as the share of the warm-up harm (consumer
surplus at Nash prices minus that at the sham's prices) that one forced cut closes. All numbers
are within the branch; nothing here says what happens after it.

    python -m probe.welfare        # writes results/welfare_forced_cut.csv and prints the summary
"""

from __future__ import annotations

import numpy as np
import polars as pl

from probe import RESULTS
from probe import economics as econ
from probe.analysis import _DEV, _paths, bootstrap_ci, load_all

MODELS = ["gpt5mini", "gpt41mini", "gpt52"]


def branch_welfare(df: pl.DataFrame) -> pl.DataFrame:
    """Per shown forced-cut branch: mean consumer-surplus gain vs sham and share of harm closed."""
    pn = econ.nash_price()
    cs_nash = econ.consumer_surplus(pn, pn)
    rows = []
    for (model, seed), _ in df.filter(pl.col("model").is_in(MODELS)).group_by(["model", "seed"]):
        runs = set(df.filter((pl.col("model") == model) & (pl.col("seed") == seed))["run"])
        for run in sorted(runs):
            m = _DEV.match(run)
            if not m or m.group(2) != "shown":
                continue
            br, sh = _paths(df, model, seed, run), _paths(df, model, seed, "sham_shown_a")
            if br is None or sh is None:
                continue
            n = min(len(br["pA"]), len(sh["pA"]))
            if br["pA"][0] >= sh["pA"][0]:
                continue  # realised move is a raise
            cs_br = np.array([econ.consumer_surplus(a, b) for a, b in zip(br["pA"][:n], br["pB"][:n])])
            cs_sh = np.array([econ.consumer_surplus(a, b) for a, b in zip(sh["pA"][:n], sh["pB"][:n])])
            harm = cs_nash - cs_sh.mean()
            rows.append(dict(model=model, seed=seed, run=run, x=int(m.group(1)) / 100,
                             rounds=n, cs_gain=float((cs_br - cs_sh).mean()), harm=float(harm),
                             share_closed=float((cs_br - cs_sh).mean() / harm) if harm > 0 else np.nan,
                             dpA=float((br["pA"][:n] - sh["pA"][:n]).mean()),
                             dpB=float((br["pB"][:n] - sh["pB"][:n]).mean())))
    return pl.DataFrame(rows).sort("model", "seed", "x")


def summary(w: pl.DataFrame) -> pl.DataFrame:
    """Seed-level means with bootstrap intervals, by model and cut size."""
    out = []
    for (model, x), g in w.group_by(["model", "x"]):
        s = g.group_by("seed").agg(pl.col("share_closed").mean(), pl.col("cs_gain").mean(),
                                   pl.col("harm").mean())
        lo, hi = bootstrap_ci(s["share_closed"].to_numpy())
        out.append(dict(model=model, cut=-x, seeds=s.height, harm=float(s["harm"].mean()),
                        cs_gain=float(s["cs_gain"].mean()),
                        share_closed=float(s["share_closed"].mean()), lo=lo, hi=hi))
    return pl.DataFrame(out).sort("model", "cut")


def main():
    w = branch_welfare(load_all())
    w.write_csv(RESULTS / "welfare_forced_cut.csv")
    with pl.Config(tbl_rows=40, float_precision=3, tbl_width_chars=200):
        print(summary(w))


if __name__ == "__main__":
    main()
