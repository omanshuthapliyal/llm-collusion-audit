"""
Static benchmarks for the symmetric Calvano duopoly used by the starter repo.

Wraps the pre-existing demand code (``src/environment/pricing_market_logic_multiproduct.py``)
with the parameters ``Experiment.__init__`` sets: a=2, c=1, alpha=1, a0=0, mu=0.25,
multiplier (market size) 100, sigma=0.
"""

from __future__ import annotations

import math
from typing import Optional
from functools import lru_cache

from scipy.optimize import minimize_scalar

from src.environment.pricing_market_logic_multiproduct import (
    get_monopoly_prices,
    get_nash_prices,
    get_profits,
    get_quantities,
)

A, C, ALPHA, A0, MU, MARKET, SIGMA = 2.0, 1.0, 1.0, 0.0, 0.25, 100.0, 0.0
_COMMON = dict(a0=A0, a=(A, A), mu=MU, alpha=(ALPHA, ALPHA), multiplier=MARKET,
               sigma=SIGMA, group_idxs=(1, 1))


def quantities(p_own: float, p_rival: float) -> tuple[float, float]:
    """Logit demand for (own, rival) prices in the starter's duopoly."""
    q = get_quantities(p=(p_own, p_rival), **_COMMON)
    return q[0], q[1]


def profit(p_own: float, p_rival: float) -> float:
    """Own one-round profit at (own, rival) prices."""
    return get_profits(p=(p_own, p_rival), c=(C, C), **_COMMON)[0]


@lru_cache(maxsize=4096)
def best_response(p_rival: float) -> float:
    """One-shot profit-maximising price against a rival price."""
    res = minimize_scalar(lambda p: -profit(p, p_rival), bounds=(C, 4.0), method="bounded",
                          options={"xatol": 1e-6})
    return float(res.x)


def br_slope(p_rival: float, h: float = 1e-3) -> float:
    """Slope of the static best response at a rival price (central difference)."""
    return (best_response(p_rival + h) - best_response(p_rival - h)) / (2 * h)


def nash_price() -> float:
    """Static Bertrand-Nash price of the symmetric duopoly (1.4729)."""
    return float(get_nash_prices(a0=A0, a=(A, A), mu=MU, alpha=(ALPHA, ALPHA),
                                 multiplier=MARKET, sigma=SIGMA, group_idxs=(1, 1),
                                 c=(C, C))[0])


def monopoly_price() -> float:
    """Joint-profit-maximising (monopoly) price of the symmetric duopoly (1.9250)."""
    return float(get_monopoly_prices(a0=A0, a=(A, A), mu=MU, alpha=(ALPHA, ALPHA),
                                     multiplier=MARKET, sigma=SIGMA, group_idxs=(1, 1),
                                     c=(C, C))[0])


def infer_rival_price(p_own: float, q_own: float) -> float:
    """Invert logit demand: the rival price implied by one's own price and quantity.

    q_i = M e^{d_i} / (e^{d_0} + e^{d_i} + e^{d_j}),  d = (a - p) / mu,  so
    e^{d_j} = M e^{d_i} / q_i - e^{d_i} - e^{d_0}.  This is the "demand channel" through
    which a firm can still learn its rival's price when the price itself is hidden.
    """
    ei = math.exp((A - p_own / ALPHA) / MU)
    ej = MARKET * ei / max(q_own, 1e-9) - ei - math.exp(A0 / MU)
    if ej <= 0:
        return float("inf")  # rival effectively absent (priced out)
    return ALPHA * (A - MU * math.log(ej))


def consumer_surplus(p_a: float, p_b: float) -> float:
    """Expected consumer surplus per round under logit demand (log-sum formula, market size M):
    CS = M mu ln(e^{d_0} + e^{d_A} + e^{d_B}), up to an additive constant that cancels in differences."""
    d = [A0 / MU, (A - p_a / ALPHA) / MU, (A - p_b / ALPHA) / MU]
    top = max(d)
    return MARKET * MU * (top + math.log(sum(math.exp(x - top) for x in d)))


def deviation_ratio(p_agree: float, cut: Optional[float] = 0.15) -> float:
    """One-round gain of a deviation from a symmetric agreement at p_agree, relative to the
    agreement's per-round profit: (pi(dev, p) - pi(p, p)) / pi(p, p). cut=None uses the best
    response to p_agree (the most profitable deviation)."""
    pa = profit(p_agree, p_agree)
    dev = best_response(round(p_agree, 6)) if cut is None else (1 - cut) * p_agree
    return (profit(dev, p_agree) - pa) / pa


def deterrence_feasible(p_agree: float, cut: Optional[float] = 0.15,
                        rounds_after: Optional[int] = 9, delta: float = 0.95) -> bool:
    """Can any punishment make a one-round deviation from a symmetric agreement at p_agree
    unprofitable? The most B can take from A is A's whole agreement profit in each later round
    (A's profit cannot fall below 0 while A prices at or above cost), so deterrence needs
    deviation_ratio <= sum_{t=1}^{H} delta^t (METHODS section 19). rounds_after=None is the
    infinite horizon; cut=None is the best-response deviation."""
    weight = (delta / (1 - delta) if rounds_after is None
              else delta * (1 - delta ** rounds_after) / (1 - delta))
    return deviation_ratio(p_agree, cut) <= weight


def max_deterrable_price(cut: Optional[float] = 0.15, rounds_after: Optional[int] = 9,
                         delta: float = 0.95, hi: float = 25.0) -> float:
    """Deterrence ceiling: the highest symmetric agreed price at which the deviation can be
    deterred (bisection; deviation_ratio increases with p above the monopoly price)."""
    lo = monopoly_price()
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if deterrence_feasible(mid, cut, rounds_after, delta) else (lo, mid)
    return lo


def collusion_index(p: float) -> float:
    """Calvano-style index: 0 at the Nash price, 1 at the monopoly price."""
    pn, pm = nash_price(), monopoly_price()
    return (p - pn) / (pm - pn)


def _common_n(n: int) -> dict:
    return dict(a0=A0, a=(A,) * n, mu=MU, alpha=(ALPHA,) * n, multiplier=MARKET, sigma=SIGMA,
                group_idxs=(1,) * n)


def profit_n(p_own: float, rivals: tuple[float, ...]) -> float:
    """Own profit against any number of rivals (firm 0 is 'own')."""
    n = 1 + len(rivals)
    return get_profits(p=(p_own, *rivals), c=(C,) * n, **_common_n(n))[0]


def best_response_n(rivals: tuple[float, ...]) -> float:
    """Static best response against any number of rival prices."""
    res = minimize_scalar(lambda p: -profit_n(p, rivals), bounds=(C, 4.0), method="bounded",
                          options={"xatol": 1e-6})
    return float(res.x)


def nash_price_n(n: int) -> float:
    """Symmetric Nash price with n firms (n = 3: 1.370)."""
    return float(get_nash_prices(c=(C,) * n, **_common_n(n))[0])


def monopoly_price_n(n: int) -> float:
    """Symmetric joint-monopoly price with n firms (n = 3: 2.000)."""
    return float(get_monopoly_prices(c=(C,) * n, **_common_n(n))[0])
