# Figure captions (draft; regenerate figures with `bin/probe figures`)

**`fig_concept`. Two ways high prices can be sustained, and where the audit intervenes.**
- *Left, enforced (closed loop):* firm B observes A's price and responds through a policy f.
- *Right, spurious (open loop):* B holds a set point p* taken from the prompt, so its response to A's price is about zero.
- *The audit's inputs:*
  - a one-round forced change u to A's price, a cut or a raise;
  - a mask on B's view of A's price;
  - re-matching with a stranger (not drawn).
- *Not maskable:* B always sees its own sales (dashed), so hiding A's price is imperfect monitoring, not blinding.

**`fig_mechanism_map`. B's response to a forced cut vs a forced raise (A's price visible to B).**
- *Axes:* B's price change per unit of A's forced move, summed over the three rounds after the move.
- *Hollow markers:* scripted bots with known mechanisms. They place an anchored rival at (0, 0), a best responder at about (0.43, 0.36), a price matcher at (1, 1), and a punish-only rival at (3.1, 0), off the chart.
- *Filled markers:* LLMs, with 95% bootstrap intervals over seeds (6 for gpt-4.1-mini and gpt-5.2; 3 for gpt-5-mini and Qwen).
  - gpt-5-mini and gpt-4.1-mini sit near the anchored bot.
  - gpt-5.2 (low reasoning effort) responds to both cuts and raises, more strongly than a best responder, but with wide intervals.
  - Qwen2.5-7B is unresolved at T = 1 (pinned to the edge).
- *Key point:* a cut-only test cannot separate matching from punishment; the forced raise does.

**`fig_impulse_responses`. B's price change after A's forced move, per unit of the move, by direction and by whether B can see A's price.**
- *Lines:* blue = forced cut, orange = forced raise; solid = A's price visible, dashed = hidden; grey = the response a static best responder would give to the same path of A's price.
- *Bands:* 10th to 90th percentile over seeds and rungs.
- *Top rows (scripted bots):* each known mechanism is recovered. The best responder that infers A's hidden price from its own sales keeps responding when the price is hidden.

**`fig_deviator_paths`. What the deviator, A, does after its own forced move.**
- *Axes:* A's price relative to its matched sham, per unit of the forced move. 1 = A keeps the forced price; 0 = A returns.
- *gpt-5-mini:* keeps every forced cut (18 of 18 branches) and reverts every forced raise (18 of 18). The high price is not an attractor in the downward direction.
- *gpt-4.1-mini:* keeps some cuts.
- *Qwen2.5-7B:* too noisy to read.
- *Scales:* y-limits differ by panel so that every path is shown (Qwen spans about ±3.5).

**`fig_anchor_cue`. The willingness-to-pay figure in the prompt moves where prices lock.**
- *Setup:* the prompt states "No customer would pay more than {3.5, 4.51, 6.0}" from round 1. Demand does not depend on this number.
- *Points:* each line is one firm in one seed; y is the mean price over rounds 21 to 30. Dashed: (WTP + 1)/2. Dotted: the monopoly price.
- *gpt-5-mini:* the locked price rises with the stated willingness to pay (slope 0.30, 95% CI [0.13, 0.42]), and several firms lock exactly on (WTP + 1)/2.
- *gpt-4.1-mini:* the cue moves only the opening price (round-1 slope 0.31); the locked slope is 0.05, CI [−0.07, 0.15].

**`fig_warmups`. Warm-up price paths (rival's price visible), each seed.**
- *Lines:* blue = firm A, orange = firm B. Dotted: the Nash price (1.47). Dashed: the monopoly price (1.92).
- *Most GPT firms* lock above the monopoly price, which a profit-maximising cartel would not choose.

**`fig_elicit`. Line D: eliciting collusion (gpt-4.1-mini; dots = seeds).**
- *Conditions:* compete (R−), emergent (no channel, reference), permitted (R1), instructed (R2), instructed and told to punish (R2plus).
- *Left:* price level over rounds 21 to 30, against the Nash and monopoly prices. It rises with elicitation strength.
- *Middle:* B's response to A's forced 15% cut, with A's price visible (blue) or hidden (grey). Only R2plus responds (3 of 3 seeds), and only when the price is visible.
- *Right:* the deviator's return rate ρ after its own forced cut (1 = keeps the cut, 0 = returns).
  - Under agreements (R1, R2) the deviator returns at once, giving up a cut that would have paid, although nobody punishes it.
  - The told-to-compete agent keeps profitable cuts.
  - Emergent gpt-4.1-mini gives up profitable, unpunished cuts in 4 of 12 such branches (RESULTS §15), so this is an observation, not a validated detector.

**`fig_designed`. Line E: a designed stubborn third firm at the triopoly Nash price (gpt-5.2).**
- *Left:* change in incumbent prices vs no entrant (rounds 41 to 50; 3 seeds; blue A, orange B), by who observes the designed firm.
  - In "A only", B never observes it, yet falls in 3 of 3 seeds. That is propagation through B's observation of A.
  - The demand channel alone ("nobody") also moves prices when the incumbents start far above. A random entrant moves prices as much.
- *Right:* 40-round paths, seed 0.
  - Visible to both: the incumbents settle at 1.38 (A) and 1.36 (B), close to the stubborn price of 1.37.
  - Visible to A only: the pair settles together at 1.46 (partial consensus).

**`fig_probe`. Line D2: activation probes, Qwen2.5-7B, layer 20 (dots = runs; one seed; exploratory).**
- *Blue, the probe trained on compete vs instructed:* scores instructed cartels about 1, but cartels whose instruction was withdrawn (still colluding in behaviour) only about 0.2. It reads the instruction.
- *Orange, the prompt-matched probe* (trained on withdrawn branches, which share one prompt): separates collusive from competitive history when the prompt is fixed, but does not transfer to a different prompt format (instructed cartels about 0.4). Emergent scores therefore cannot be read.

**`fig_protocol`. The audit as a decision procedure (rules v2).**
- *Boxes:* decision boxes are shaded; verdicts are plain; the enforced verdict is highlighted.
- *Dashed boxes* are checks added after the data: the deterrence-ceiling gate (Proposition 4, METHODS §19) and the longer-window check suggested by the held-out bot test (METHODS §16). They are not part of rules v2.
- *Status:* v1 was pre-registered; v2 is post hoc.

**`fig_ceiling`. Agreed prices against the deterrence ceiling (Proposition 4, delta = 0.95).**
- *Dots:* one per firm-run, the mean warm-up price, grouped by condition.
- *Lines:* Nash (1.47), monopoly (1.93), the best-deviation ceiling (3.07, any horizon) and the 15% cut, 10-round ceiling (3.86). Above 3.07 no punishment can deter the best deviation.
- *Counts:* 18 of 18 instructed-cartel firm-runs lie above 3.07; 3 of 32 emergent ones do.

**`fig_intensity`. Punishment intensity after a forced cut.**
- *Bars:* the share of the deviator's feasible loss that the rival imposes, with A's path held fixed (95% seed-bootstrap intervals). Grey bars are scripted bots with known rules.
- *Reading:* gpt-5.2 exceeds its best-response benchmark by 0.048, on visible cuts only; the instructed-punish condition (R3) imposes 0.0% in the pooled estimate, with one seed reaching 30%.
