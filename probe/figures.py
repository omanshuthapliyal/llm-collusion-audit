"""
Report figures (static PNG + PDF in figures/).

    python -m probe.figures

Palette: validated reference categorical slots (dataviz skill), light mode. Cut = slot 1
(blue), raise = slot 2 (orange); shown arms are solid, hidden arms dashed; the static
best-response prediction is a thin grey line. Text stays in neutral ink.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from probe import ROOT  # noqa: E402
from probe import economics as econ  # noqa: E402
from probe.analysis import _paths, load_all  # noqa: E402

FIG = ROOT / "figures"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#fcfcfb"
CUT, RAISE = "#2a78d6", "#eb6834"
MODEL_LABEL = {
    "bot_anchor": "bot: anchor", "bot_br": "bot: best response", "bot_br_infer":
    "bot: best response\n(infers hidden price)", "bot_match": "bot: price matching",
    "bot_punish": "bot: punish-only", "qwen7b": "Qwen2.5-7B", "gpt41mini": "gpt-4.1-mini",
    "gpt5mini": "gpt-5-mini (low)", "gpt52": "gpt-5.2 (low)",
}
ORDER = list(MODEL_LABEL)

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
    "axes.titlesize": 9, "legend.frameon": False, "lines.linewidth": 2,
})


def _limits(values, must=(0.0,), pad=0.08):
    """Axis limits that contain every value (and the reference levels in `must`), padded."""
    v = np.concatenate([np.ravel(np.asarray(x, float)) for x in values] + [np.asarray(must, float)])
    v = v[np.isfinite(v)]
    lo, hi = float(v.min()), float(v.max())
    span = max(hi - lo, 1e-6)
    return lo - pad * span, hi + pad * span


def _save(fig, name: str):
    FIG.mkdir(exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(FIG / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def _normalised_response(df, model, seed, run, sham):
    br, sh = _paths(df, model, seed, run), _paths(df, model, seed, sham)
    if br is None or sh is None:
        return None
    n = min(len(br["pA"]), len(sh["pA"]))
    dA0 = br["pA"][0] - sh["pA"][0]
    if abs(dA0) < 1e-9:
        return None
    dB = (br["pB"][:n] - sh["pB"][:n]) / dA0
    dBR = np.array([0.0] + [(econ.best_response(round(br["pA"][h - 1], 4))
                             - econ.best_response(round(sh["pA"][h - 1], 4))) / dA0
                            for h in range(1, n)])
    dA = (br["pA"][:n] - sh["pA"][:n]) / dA0
    return dB, dBR, dA, np.sign(dA0)


def impulse_grid(df: pl.DataFrame, models: list[str], name: str = "fig_impulse_responses"):
    """B's response to A's one-round forced move, per unit of the move, by sign and visibility."""
    models = [m for m in ORDER if m in models]
    fig, axes = plt.subplots(len(models), 2, figsize=(6.4, 1.55 * len(models)), sharex=True,
                             squeeze=False)
    for i, model in enumerate(models):
        sub = df.filter(pl.col("model") == model)
        row_values = []
        for j, vis in enumerate(("shown", "hidden")):
            ax = axes[i, j]
            curves = {"cut": [], "raise": []}
            preds = []
            for seed in sorted(set(sub["seed"])):
                for run in sorted(set(sub.filter(pl.col("seed") == seed)["run"])):
                    if not (run.startswith("dev") and run.endswith(vis)):
                        continue
                    r = _normalised_response(df, model, seed, run, f"sham_{vis}_a")
                    if r is None:
                        continue
                    dB, dBR, _, sgn = r
                    curves["cut" if sgn < 0 else "raise"].append(dB)
                    preds.append(dBR)
            h = None
            for key, color in (("cut", CUT), ("raise", RAISE)):
                if not curves[key]:
                    continue
                arr = np.vstack([c[:min(map(len, curves[key]))] for c in curves[key]])
                h = np.arange(arr.shape[1])
                ax.plot(h, arr.mean(0), color=color, ls="-" if vis == "shown" else "--",
                        label=f"forced {key}")
                row_values.append(arr.mean(0))
                if arr.shape[0] > 1:
                    lo, hi = np.percentile(arr, [10, 90], axis=0)
                    ax.fill_between(h, lo, hi, color=color, alpha=0.12, lw=0)
                    row_values += [lo, hi]
            if preds:
                p = np.vstack([q[:min(map(len, preds))] for q in preds]).mean(0)
                ax.plot(np.arange(len(p)), p, color=MUTED, lw=1, label="best-response prediction")
                row_values.append(p)
            ax.axhline(0, color=MUTED, lw=0.8)
            if i == 0:
                ax.set_title(f"A's price {'visible' if vis == 'shown' else 'hidden'} to B",
                             color=INK)
            if j == 0:
                ax.set_ylabel(MODEL_LABEL[model], rotation=0, ha="right", va="center", color=INK)
        lim = _limits(row_values, must=(0.0, 0.5))
        for ax in axes[i]:
            ax.set_ylim(*lim)
    for ax in axes[-1]:
        ax.set_xlabel("rounds after the forced move (h)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, bbox_to_anchor=(0.55, 1.02))
    fig.text(0.0, 0.5, "B's price change per unit of A's forced move", rotation=90,
             va="center", color=INK2)
    fig.tight_layout(rect=(0.02, 0, 1, 0.97))
    _save(fig, name)


def mechanism_map(ms: pl.DataFrame, name: str = "fig_mechanism_map"):
    """B's pass-through of a forced cut vs a forced raise (raw beta, rival price shown), with
    seed-bootstrap intervals for LLMs. Bots mark where known mechanisms land."""
    shown = ms.filter(pl.col("vis") == "shown")
    lim = (-0.25, 1.35)
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    ax.plot(lim, lim, color=GRID, lw=1.2, zorder=0)
    ax.text(1.12, 1.02, "symmetric response", ha="right", va="bottom", fontsize=7.5,
            color=MUTED, rotation=45, rotation_mode="anchor")
    offsets = {"bot_anchor": (-6, -14), "bot_br": (6, -12), "bot_match": (-8, 8),
               "bot_punish": (-6, 8), "gpt41mini": (6, -14), "gpt5mini": (8, 2),
               "gpt52": (8, 4), "qwen7b": (8, 6)}
    for model in [m for m in ORDER if m in set(shown["model"]) and m != "bot_br_infer"]:
        g = shown.filter(pl.col("model") == model)
        cut, rai = g.filter(pl.col("sign") == "cut"), g.filter(pl.col("sign") == "raise")
        if cut.is_empty() or rai.is_empty():
            continue
        x, y = float(cut["beta"][0]), float(rai["beta"][0])
        bot = model.startswith("bot_")
        label = MODEL_LABEL[model].replace("\n", " ")
        if not bot and not (lim[0] <= x <= lim[1] and lim[0] <= y <= lim[1]):
            # an LLM estimate off the chart (Qwen: unresolved, see RESULTS): pin to the edge
            xc, yc = min(max(x, lim[0]), lim[1]), min(max(y, lim[0]), lim[1])
            ax.plot(xc, yc, "v" if y < lim[0] else "o", ms=8, mfc=INK, mec=INK, clip_on=False)
            ax.annotate(f"{label} (cut {x:.2f}, raise {y:.2f}; unresolved)", (xc, yc),
                        xytext=(8, 2), textcoords="offset points", fontsize=7.5, color=INK)
            continue
        if x > lim[1]:  # punish-only bot: off the chart to the right
            ax.annotate(f"{label} (cut {x:.1f}) →", (lim[1], y), xytext=(-4, 8),
                        textcoords="offset points", ha="right", fontsize=7.5, color=INK2)
            ax.plot(lim[1] - 0.01, y, ">", ms=8, mfc=SURFACE, mec=INK, mew=1.5, clip_on=False)
            continue
        if not bot:
            xe = [[x - cut["beta_lo"][0]], [cut["beta_hi"][0] - x]]
            ye = [[y - rai["beta_lo"][0]], [rai["beta_hi"][0] - y]]
            ax.errorbar(x, y, xerr=xe, yerr=ye, fmt="none", ecolor=MUTED, elinewidth=1,
                        capsize=2, zorder=1)
        ax.plot(x, y, "o", ms=8, mfc=SURFACE if bot else INK, mec=INK, mew=1.5, zorder=2)
        ax.annotate(label, (x, y), xytext=offsets.get(model, (6, 4)),
                    textcoords="offset points", fontsize=7.5, color=INK2 if bot else INK,
                    ha="right" if offsets.get(model, (6, 4))[0] < 0 else "left")
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.set_xlim(*lim)
    ax.set_ylim(*lim)
    ax.set_xlabel("B's price change per unit of a forced cut")
    ax.set_ylabel("B's price change per unit of a forced raise")
    ax.set_title("A's price visible. Hollow: bots. Filled: LLMs, 95% seed CI.", color=INK2)
    _save(fig, name)


def warmup_paths(df: pl.DataFrame, models: list[str], name: str = "fig_warmups"):
    """Warm-up price paths (rival price shown), each seed, against Nash and monopoly."""
    models = [m for m in ORDER if m in models and not m.startswith("bot_")]
    if not models:
        return
    fig, axes = plt.subplots(1, len(models), figsize=(2.3 * len(models), 2.4), sharey=True,
                             squeeze=False)
    pn, pm = econ.nash_price(), econ.monopoly_price()
    for ax, model in zip(axes[0], models):
        sub = df.filter((pl.col("model") == model) & (pl.col("run") == "warmup_shown"))
        for seed in sorted(set(sub["seed"])):
            for firm, color in (("Firm A", CUT), ("Firm B", RAISE)):
                s = sub.filter((pl.col("seed") == seed) & (pl.col("agent") == firm)).sort("round")
                ax.plot(s["round"], s["price"], color=color, lw=1.2, alpha=0.8,
                        label=firm if seed == 0 else None)
        ax.axhline(pn, color=MUTED, lw=1, ls=":")
        ax.axhline(pm, color=MUTED, lw=1, ls="--")
        ax.set_title(MODEL_LABEL[model], color=INK)
        ax.set_xlabel("round")
    axes[0, 0].set_ylabel("price")
    fig.legend(handles=[plt.Line2D([], [], color=CUT, label="Firm A"),
                        plt.Line2D([], [], color=RAISE, label="Firm B"),
                        plt.Line2D([], [], color=MUTED, ls="--", label="monopoly price (1.92)"),
                        plt.Line2D([], [], color=MUTED, ls=":", label="Nash price (1.47)")],
               loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.08))
    fig.tight_layout()
    _save(fig, name)


def deviator_paths(df: pl.DataFrame, models: list[str], name: str = "fig_deviator_paths"):
    """A's own price relative to its sham after the forced move, per unit of the move.
    1 = A stays at the forced price; 0 = A returns to where it would have been."""
    models = [m for m in ORDER if m in models and not m.startswith("bot_")]
    if not models:
        return
    fig, axes = plt.subplots(1, len(models), figsize=(2.5 * len(models), 2.6), squeeze=False)
    for ax, model in zip(axes[0], models):
        sub = df.filter(pl.col("model") == model)
        panel_values = []
        for seed in sorted(set(sub["seed"])):
            for run in sorted(set(sub.filter(pl.col("seed") == seed)["run"])):
                if not (run.startswith("dev") and run.endswith("_shown")):
                    continue
                r = _normalised_response(df, model, seed, run, "sham_shown_a")
                if r is None:
                    continue
                _, _, dA, sgn = r
                ax.plot(np.arange(len(dA)), dA, color=CUT if sgn < 0 else RAISE, lw=1.2,
                        alpha=0.7)
                panel_values.append(dA)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.axhline(1, color=MUTED, lw=0.8, ls=":")
        ax.set_title(MODEL_LABEL[model], color=INK)
        ax.set_xlabel("rounds after the forced move (h)")
        ax.set_ylim(*_limits(panel_values, must=(0.0, 1.0)))
    axes[0, 0].set_ylabel("A's price change / forced move")
    handles = [plt.Line2D([], [], color=CUT, label="forced cut"),
               plt.Line2D([], [], color=RAISE, label="forced raise")]
    fig.legend(handles=handles, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.06))
    fig.tight_layout()
    _save(fig, name)


def cue_plot(name: str = "fig_anchor_cue"):
    """Locked price (rounds 21-30) against the stated willingness-to-pay cue, per firm-run."""
    path = FIG.parent / "results" / "metrics_cue.csv"
    if not path.exists():
        return
    c = pl.read_csv(path)
    models = [m for m in ORDER if m in set(c["model"])]
    if not models:
        return
    wtp = np.array([3.5, 4.51, 6.0])
    fig, axes = plt.subplots(1, len(models), figsize=(2.7 * len(models), 2.6), sharey=True,
                             squeeze=False)
    pm = econ.monopoly_price()
    for ax, model in zip(axes[0], models):
        for row in c.filter(pl.col("model") == model).iter_rows(named=True):
            locked = [row["locked_wtp35"], row["locked_wtp451"], row["locked_wtp60"]]
            ax.plot(wtp, locked, "-o", color=CUT if row["agent"] == "Firm A" else RAISE,
                    lw=1.2, ms=4, alpha=0.8)
        ax.plot(wtp, (wtp + 1) / 2, color=INK, lw=1, ls="--")
        ax.axhline(pm, color=MUTED, lw=1, ls=":")
        ax.set_title(MODEL_LABEL[model], color=INK)
        ax.set_xlabel("stated WTP (in prompt only)")
        ax.set_xticks(wtp)
    axes[0, 0].set_ylabel("locked price, rounds 21 to 30")
    handles = [plt.Line2D([], [], color=CUT, marker="o", label="Firm A"),
               plt.Line2D([], [], color=RAISE, marker="o", label="Firm B"),
               plt.Line2D([], [], color=INK, lw=1, ls="--", label="(WTP + 1) / 2"),
               plt.Line2D([], [], color=MUTED, lw=1, ls=":", label="monopoly price")]
    fig.legend(handles=handles, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.07))
    fig.tight_layout()
    _save(fig, name)


def concept_diagram(name: str = "fig_concept"):
    """Closed-loop (enforced) vs open-loop (anchored) supracompetitive pricing, and where the
    audit's interventions enter: a forced price u, a mask on the observation channel, and
    the demand channel that a mask cannot remove."""
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9))

    def box(ax, xy, text, w=0.26, h=0.16, fill=SURFACE):
        x, y = xy
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.01",
                                    fc=fill, ec=INK, lw=1.2))
        ax.text(x, y, text, ha="center", va="center", fontsize=8, color=INK)

    def arrow(ax, a, b, label=None, color=INK, ls="-", rad=0.0, lpos=(0, 0.04)):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=10, lw=1.3,
                                     color=color, ls=ls, connectionstyle=f"arc3,rad={rad}"))
        if label:
            mx, my = (a[0] + b[0]) / 2 + lpos[0], (a[1] + b[1]) / 2 + lpos[1]
            ax.text(mx, my, label, ha="center", va="center", fontsize=7, color=INK2)

    for ax, title in zip(axes, ("Enforced (closed loop)", "Spurious (open loop)")):
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.12)
        ax.axis("off")
        ax.set_title(title, color=INK)
        closed = ax is axes[0]
        box(ax, (0.18, 0.72), "Firm A")
        box(ax, (0.5, 0.42), "Market\n(logit demand)", w=0.28)
        box(ax, (0.82, 0.72), "Firm B\n" + ("$p_B = f(p_A$ history$)$" if closed
                                             else "$p_B \\approx p^*$"), w=0.32, h=0.18)
        arrow(ax, (0.24, 0.63), (0.42, 0.5), "$p_A$", lpos=(-0.05, 0.0))
        arrow(ax, (0.76, 0.63), (0.58, 0.5), "$p_B$", lpos=(0.05, 0.0))
        arrow(ax, (0.6, 0.36), (0.84, 0.62), "own sales", color=MUTED, ls="--", rad=0.35,
              lpos=(0.13, -0.08))
        # forced price u enters at A
        arrow(ax, (0.03, 0.92), (0.12, 0.79), None, color=CUT)
        ax.text(0.02, 0.95, "forced move $u$", fontsize=7, color=CUT, va="bottom")
    # closed loop: B observes p_A and responds
    a0 = axes[0]
    arrow(a0, (0.3, 0.76), (0.66, 0.76), "observes $p_A$\n(mask here)", color=INK, lpos=(0, 0.08))
    a0.text(0.5, 0.1, "Deviation is seen and answered;\nraises and hiding $p_A$ identify $f$.",
            ha="center", fontsize=7.5, color=INK2)
    # open loop: set point from the prompt; observation has ~zero gain
    a1 = axes[1]
    box(a1, (0.82, 1.03), "prompt cue (WTP)", w=0.32, h=0.08, fill=GRID)
    arrow(a1, (0.82, 0.99), (0.82, 0.82), None, color=INK)
    a1.text(0.85, 0.9, "$p^*$", fontsize=8, color=INK)
    arrow(a1, (0.3, 0.76), (0.66, 0.76), "observes $p_A$\ngain $\\approx 0$", color=MUTED,
          ls=":", lpos=(0, 0.08))
    a1.text(0.5, 0.1, "High price is a held set point;\na forced cut is kept, not punished.",
            ha="center", fontsize=7.5, color=INK2)
    fig.tight_layout()
    _save(fig, name)


COND_ORDER = [("gpt41mini__Rminus", "compete"), ("gpt41mini", "emergent\n(no channel)"),
              ("gpt41mini__R1", "permitted"), ("gpt41mini__R2", "instructed"),
              ("gpt41mini__R2plus", "instructed\n+ punish")]


def elicit_panels(name: str = "fig_elicit"):
    """Line D: price level, B's response to a forced 15% cut, and the deviator's return, by
    condition (gpt-4.1-mini; dots = seeds)."""
    res = FIG.parent / "results"
    w = pl.read_csv(res / "metrics_warmups.csv")
    bm = pl.read_csv(res / "metrics_branches.csv")
    fig, axes = plt.subplots(1, 3, figsize=(7.4, 2.6))
    xs = np.arange(len(COND_ORDER))
    rng = np.random.default_rng(0)
    for i, (model, _) in enumerate(COND_ORDER):
        lv = w.filter((pl.col("model") == model) & (pl.col("run") == "warmup_shown"))
        lv = lv.group_by("seed").agg(pl.col("mean_price").mean()).sort("seed")["mean_price"].to_numpy()
        axes[0].plot(i + rng.uniform(-0.12, 0.12, len(lv)), lv, "o", color=INK, ms=4, alpha=0.8)
        for vis, color, dx in (("shown", CUT, -0.15), ("hidden", MUTED, 0.15)):
            g = bm.filter((pl.col("model") == model) & (pl.col("vis") == vis) & (pl.col("x") == -0.15))
            b = g["beta"].to_numpy()
            axes[1].plot(i + dx + rng.uniform(-0.05, 0.05, len(b)), b, "o", color=color, ms=4,
                         label=("A's price visible" if vis == "shown" else "hidden") if i == 0 else None)
        g = bm.filter((pl.col("model") == model) & (pl.col("vis") == "shown") & (pl.col("x") == -0.15))
        axes[2].plot(i + rng.uniform(-0.12, 0.12, g.height), g["rho"].to_numpy(), "o", color=CUT, ms=4)
    pn, pm = econ.nash_price(), econ.monopoly_price()
    axes[0].axhline(pn, color=MUTED, lw=1, ls=":")
    axes[0].axhline(pm, color=MUTED, lw=1, ls="--")
    axes[0].text(4.45, pm, "monopoly", fontsize=6.5, color=INK2, va="bottom", ha="right")
    axes[0].text(4.45, pn, "Nash", fontsize=6.5, color=INK2, va="bottom", ha="right")
    axes[0].set_title("price level (rounds 21-30)", color=INK)
    axes[1].set_title("rival's response to a 15% cut", color=INK)
    axes[1].axhline(0, color=MUTED, lw=0.8)
    axes[1].legend(loc="upper left", fontsize=6.5)
    axes[2].set_title("deviator keeps the cut? (ρ)", color=INK)
    axes[2].set_ylim(-0.15, 1.15)
    axes[2].set_yticks([0, 0.25, 0.5, 0.75, 1])
    axes[2].set_yticklabels(["0 returns", "0.25", "0.5", "0.75", "1 keeps"])
    for ax in axes:
        ax.set_xticks(xs)
        ax.set_xticklabels([c[1] for c in COND_ORDER], fontsize=6.5, rotation=35, ha="right")
    fig.tight_layout()
    _save(fig, name)


def designed_panels(name: str = "fig_designed"):
    """Line E: incumbent price change vs sham by who observes the stubborn firm (dots = seeds,
    A and B), and the 40-round paths on seed 0."""
    import json

    res = FIG.parent / "results" / "gpt52"
    arms = [("stubborn_none", "nobody\n(demand only)"), ("stubborn_A", "A only"),
            ("stubborn_both", "both"), ("random_both", "random\nentrant")]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.7), gridspec_kw={"width_ratios": [1, 1.25]})
    rng = np.random.default_rng(1)

    def mean_p(r, firm, lo, hi):
        return float(np.mean([r[firm][str(k)]["chosen_price"] for k in range(lo, hi + 1)]))

    for s in (0, 1, 2):
        sham = json.loads((res / f"s{s}" / "long_sham_designed" / "results.json").read_text())
        for i, (arm, _) in enumerate(arms):
            r = json.loads((res / f"s{s}" / arm / "results.json").read_text())
            for firm, color, dx in (("Firm A", CUT, -0.12), ("Firm B", RAISE, 0.12)):
                d = mean_p(r, firm, 41, 50) - mean_p(sham, firm, 41, 50)
                axes[0].plot(i + dx + rng.uniform(-0.04, 0.04), d, "o", color=color, ms=4.5,
                             label=firm if (s == 0 and i == 0) else None)
    axes[0].axhline(0, color=MUTED, lw=0.8)
    axes[0].set_xticks(range(len(arms)))
    axes[0].set_xticklabels([a[1] for a in arms], fontsize=7)
    axes[0].set_xlabel("who observes the designed firm")
    axes[0].set_ylabel("price change vs no entrant\n(rounds 41-50)")
    axes[0].set_title("3 seeds; B never sees it in 'A only'", color=INK)
    axes[0].legend(loc="center right", bbox_to_anchor=(1.0, 0.4), fontsize=7)
    styles = {"long_sham_designed_h40": ("no entrant", ":"), "stubborn_A_h40": ("A only", "--"),
              "stubborn_both_h40": ("both", "-")}
    for run, (label, ls) in styles.items():
        r = json.loads((res / "s0" / run / "results.json").read_text())
        h = np.arange(31, 71)
        for firm, color in (("Firm A", CUT), ("Firm B", RAISE)):
            axes[1].plot(h, [r[firm][str(k)]["chosen_price"] for k in h], color=color, ls=ls, lw=1.4,
                         label=label if firm == "Firm A" else None)
    axes[1].axhline(1.37, color=INK, lw=0.8, label="designed firm (1.37)")
    axes[1].set_xlabel("round")
    axes[1].set_ylabel("price (blue A, orange B)")
    axes[1].set_title("seed 0, 40 rounds", color=INK)
    axes[1].legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=7)
    fig.tight_layout()
    _save(fig, name)


def probe_panel(name: str = "fig_probe"):
    """Line D2: mean probe score by group, layer 20, pre-registered vs prompt-matched probe."""
    import json

    act = FIG.parent / "results" / "activations"
    if not (act / "probe_matched_report.json").exists():
        return
    pre = json.loads((act / "probe_report.json").read_text())["layers"]["20"]["mean_score_by_run"]
    mat = json.loads((act / "probe_matched_report.json").read_text())["layers"]["20"]["mean_score_by_run"]
    groups = [
        ("compete", lambda k: "__Rminus__" in k and not k.endswith("withdrawn")),
        ("instructed\ncartel", lambda k: ("__R2__" in k or "__R2plus__" in k) and not k.endswith("withdrawn")),
        ("cartel, instruction\nwithdrawn", lambda k: k.endswith("withdrawn") and ("__R2__" in k or "__R2plus__" in k)),
        ("compete,\nwithdrawn", lambda k: k == "qwen7b__Rminus__s0__withdrawn"),
        ("permitted", lambda k: "__R1__" in k),
        ("emergent\n(no channel)", lambda k: k.startswith("qwen7b__s")),
    ]
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for gi, (label, f) in enumerate(groups):
        for scores, color, dx, name_ in ((pre, CUT, -0.15, "instructed-vs-compete probe"),
                                         (mat, RAISE, 0.15, "prompt-matched probe")):
            v = [x for k, x in scores.items() if f(k)]
            if v:
                ax.plot(np.full(len(v), gi + dx), v, "o", color=color, ms=4, alpha=0.7,
                        label=name_ if gi == 0 else None)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([g[0] for g in groups], fontsize=7)
    ax.set_ylabel("mean probe score per run")
    ax.set_ylim(-0.05, 1.05)
    ax.set_title("Qwen2.5-7B, layer 20 (dots = runs)", color=INK)
    ax.legend(loc="upper right", fontsize=7)
    fig.tight_layout()
    _save(fig, name)


def protocol_flow(name: str = "fig_protocol"):
    """The audit as a decision procedure: rules v2 (robustness.classify_v2), with the
    deterrence-ceiling gate (METHODS section 19) and the held-out blind spot (section 16) marked."""
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    fig, ax = plt.subplots(figsize=(9.4, 5.2))
    ax.set_xlim(0, 1.45)
    ax.set_ylim(0, 1)
    ax.axis("off")
    Q, V = "#e7eefb", "#dfe9f7"  # decision boxes, the enforced verdict
    B = {}

    def box(key, xy, text, w=0.28, h=0.085, fill=SURFACE, bold=False, ls="-"):
        x, y = xy
        B[key] = (x, y, w, h)
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.008",
                                    fc=fill, ec=INK, lw=1.1, ls=ls))
        ax.text(x, y, text, ha="center", va="center", fontsize=7.2, color=INK,
                fontweight="bold" if bold else "normal")

    def down(a, b, label=None):
        xa, ya, _, ha = B[a]
        xb, yb, _, hb = B[b]
        p0, p1 = (xa, ya - ha / 2 - 0.008), (xb, yb + hb / 2 + 0.008)
        ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=9, lw=1.0,
                                     color=INK2, shrinkA=0, shrinkB=0))
        if label:
            ax.text((p0[0] + p1[0]) / 2 + (0.025 if xb >= xa else -0.025), (p0[1] + p1[1]) / 2,
                    label, fontsize=7, color=INK2, ha="center", va="center")

    box("branch", (0.72, 0.93), "Branch from a saved state: forced cut and raise,\n"
        "A's price shown / hidden, matched shams", w=0.5)
    box("gate", (0.72, 0.79), "Gate: agreed price below the deterrence ceiling\n"
        "for this cut and branch length? (Prop. 4)", w=0.5, fill=Q)
    box("lengthen", (1.27, 0.79), "No: lengthen the branch;\n'not deterred' is uninformative",
        w=0.33, ls="--")
    box("resp", (0.72, 0.645), "B responds? (interval excludes 0,\n"
        "at least half of the rungs detected)", w=0.42, fill=Q)
    box("deter", (0.36, 0.49), "Cut deterred anyway?\n(\u0394\u03a0 < 0)", w=0.26, fill=Q)
    box("beyond", (1.1, 0.49), "About what a best responder\nwould do? (type best response)", w=0.33, fill=Q)
    box("window", (0.175, 0.325), "v2: non-responsive (other);\ncheck a longer window for delayed\n"
        "or thresholded punishment", w=0.335, h=0.105, ls="--")
    box("gives", (0.555, 0.325), "Deviator gives up profitable,\nunpunished cuts?", w=0.31, fill=Q)
    box("visible", (0.98, 0.325), "Matching or punish-only, only when\nA is visible, and the cut does not pay?", w=0.39, fill=Q)
    box("br", (1.33, 0.325), "best response,\nnot collusive", w=0.19)
    box("coord", (0.4, 0.15), "coordinated,\nunenforced", w=0.17)
    box("spur", (0.655, 0.15), "spurious\n(if above Nash)", w=0.19, bold=True)
    box("resp_ne", (0.88, 0.15), "responsive,\nnot enforced", w=0.17)
    box("enf", (1.1, 0.15), "enforced", w=0.15, bold=True, fill=V)

    down("branch", "gate")
    down("gate", "resp", "yes")
    xg, yg, wg, _ = B["gate"]
    xl, _, wl, _ = B["lengthen"]
    ax.add_patch(FancyArrowPatch((xg + wg / 2 + 0.008, yg), (xl - wl / 2 - 0.008, yg), arrowstyle="-|>",
                                 mutation_scale=9, lw=1.0, color=INK2, shrinkA=0, shrinkB=0))
    ax.text((xg + wg / 2 + xl - wl / 2) / 2, yg + 0.022, "no", fontsize=7, color=INK2, ha="center")
    down("resp", "deter", "no")
    down("resp", "beyond", "yes")
    down("deter", "window", "yes")
    down("deter", "gives", "no")
    down("gives", "coord", "yes")
    down("gives", "spur", "no")
    down("beyond", "visible", "no")
    down("beyond", "br", "yes")
    down("visible", "resp_ne", "no")
    down("visible", "enf", "yes")
    ax.text(0.72, 0.035, "Rules v2 (post hoc; v1 was pre-registered). Dashed boxes: checks added after the "
            "held-out bot test and Proposition 4.", ha="center", fontsize=6.8, color=INK2)
    _save(fig, name)


def ceiling_strip(name: str = "fig_ceiling"):
    """Warm-up price of every firm-run against the deterrence ceilings of Proposition 4
    (delta = 0.95; METHODS section 19): emergent models versus instructed cartels."""
    path = FIG.parent / "results" / "metrics_warmups.csv"
    w = pl.read_csv(path).filter(pl.col("run") == "warmup_shown")
    groups = [("gpt5mini", "gpt-5-mini", CUT), ("gpt41mini", "gpt-4.1-mini", CUT),
              ("gpt52", "gpt-5.2 (low)", CUT), ("gpt52med", "gpt-5.2 (medium)", CUT),
              ("gpt41mini__R2", "instructed", RAISE), ("gpt41mini__R2plus", "instructed + punish", RAISE),
              ("gpt41mini__R3", "instructed deterrence", RAISE)]
    best = econ.max_deterrable_price(cut=None, rounds_after=None)
    cut15 = econ.max_deterrable_price(cut=0.15, rounds_after=9)
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    ax.axvspan(best, 4.6, color="#F2E5E1", zorder=0)
    ax.text(best + 0.05, 3.0, "no punishment can\ndeter the best deviation", fontsize=7,
            color=INK2, va="center", ha="left")
    rng = np.random.default_rng(2)
    for i, (m, label, color) in enumerate(groups):
        y = len(groups) - 1 - i
        x = w.filter(pl.col("model") == m)["mean_price"].to_numpy()
        ax.plot(x, y + rng.uniform(-0.15, 0.15, len(x)), "o", ms=5, color=color, alpha=0.85, zorder=3)
    ax.set_yticks(range(len(groups)))
    ax.set_yticklabels([g[1] for g in groups][::-1])
    for v, lab, ls in ((econ.nash_price(), "Nash", ":"), (econ.monopoly_price(), "monopoly", "--"),
                       (best, f"ceiling {best:.2f}", "-"), (cut15, f"15% cut, 10 rounds {cut15:.2f}", "-.")):
        ax.axvline(v, color=MUTED if lab in ("Nash", "monopoly") else INK, lw=1, ls=ls, zorder=1)
        left = lab.startswith("ceiling")
        ax.text(v + (0.02 if left else -0.02), len(groups) - 0.45, lab, rotation=90, fontsize=7, color=INK2,
                ha="left" if left else "right", va="top")
    ax.axhline(2.5, color=GRID, lw=1)
    ax.set_xlim(1.3, 4.6)
    ax.set_ylim(-0.6, len(groups) - 0.4)
    ax.set_xlabel("agreed price (warm-up mean, rounds 21 to 30)")
    ax.grid(axis="y", visible=False)
    _save(fig, name)


def intensity_bars(name: str = "fig_intensity"):
    """Punishment intensity (share of A's feasible loss B imposes after a forced cut, A's price
    visible) for scripted bots and LLM groups, with 95% seed intervals (RESULTS section 24)."""
    path = FIG.parent / "results" / "punishment_intensity.csv"
    pi = pl.read_csv(path).filter(pl.col("vis") == "shown")
    from probe.analysis import bootstrap_ci
    rows = [("bot_grim", "bot: grim trigger", MUTED), ("bot_punish", "bot: punish-only", MUTED),
            ("bot_match", "bot: price matching", MUTED), ("bot_br", "bot: best response", MUTED),
            ("gpt52", "gpt-5.2 (low)", CUT), ("gpt41mini", "gpt-4.1-mini", CUT), ("gpt5mini", "gpt-5-mini", CUT),
            ("gpt41mini__R2plus", "instructed + punish", RAISE), ("gpt41mini__R3", "instructed deterrence", RAISE)]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    for i, (m, label, color) in enumerate(rows):
        s = pi.filter(pl.col("model") == m).group_by("seed").agg(pl.col("intensity").mean()).sort("seed")
        v = s["intensity"].to_numpy()
        mean = float(v.mean())
        y = len(rows) - 1 - i
        ax.barh(y, mean, color=color, height=0.62, zorder=2)
        if len(v) > 1:
            lo, hi = bootstrap_ci(v)
            ax.errorbar(mean, y, xerr=[[mean - lo], [hi - mean]], fmt="none", ecolor=INK, elinewidth=1, capsize=2, zorder=3)
        right = mean
        if len(v) > 1:
            right = max(right, hi)
        ax.text(max(right, 0) + 0.012, y, f"{abs(mean):.2f}", va="center", fontsize=7.5, color=INK2)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[1] for r in rows][::-1])
    ax.axhline(4.5, color=GRID, lw=1)
    ax.set_xlim(0, 0.6)
    ax.set_xlabel("share of the deviator's profit the rival takes after a forced cut")
    ax.grid(axis="y", visible=False)
    _save(fig, name)


def main():
    """Regenerate every report figure from the metrics tables and saved runs."""
    from probe.analysis import branch_metrics, model_summary

    df = load_all()
    models = sorted(set(df["model"]))
    impulse_grid(df, models)
    mechanism_map(model_summary(branch_metrics(df)))
    warmup_paths(df, models)
    deviator_paths(df, models)
    cue_plot()
    concept_diagram()
    elicit_panels()
    designed_panels()
    probe_panel()
    protocol_flow()
    ceiling_strip()
    intensity_bars()
    print(f"figures written to {FIG}")


if __name__ == "__main__":
    main()
