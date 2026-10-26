"""
Static benchmarks for the symmetric Calvano duopoly used by the starter repo.

Wraps the pre-existing demand code (``src/environment/pricing_market_logic_multiproduct.py``)
with the parameters ``Experiment.__init__`` sets: a=2, c=1, alpha=1, a0=0, mu=0.25,
multiplier (market size) 100, sigma=0.
"""

from __future__ import annotations

import math
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
