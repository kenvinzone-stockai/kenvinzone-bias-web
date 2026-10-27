"""
Market Bias Platform — Liquidity Metrics
Computes Net Liquidity, Global M2 proxy, and Fed Balance Sheet momentum.

Net Liquidity = Fed Total Assets (WALCL) - TGA (WTREGEN) - ON RRP (RRPONTSYD)
"""
from __future__ import annotations

import logging

import pandas as pd

from metrics.statistics import compute_all_windows, rate_of_change

logger = logging.getLogger(__name__)


def compute_net_liquidity(
    walcl: pd.Series,   # Fed Total Assets in Millions USD (weekly)
    tga: pd.Series,     # TGA in Millions USD (weekly)
    rrp: pd.Series,     # ON RRP in Billions USD (daily) — will be *1000
) -> pd.Series:
    """
    Standard macro net liquidity formula.
    Net Liquidity = WALCL - TGA - (RRP * 1000)
    Returns series in Millions USD.
    All inputs are forward-filled to align on a common weekly index.
    """
    # Align on weekly frequency (last observation of each week)
    combined = pd.DataFrame({
        "walcl": walcl,
        "tga": tga,
        "rrp_m": rrp * 1_000,  # B → M
    }).ffill()

    net_liq = combined["walcl"] - combined["tga"] - combined["rrp_m"]
    net_liq.name = "net_liquidity"
    return net_liq


def compute_global_m2_proxy(
    us_m2: pd.Series,       # US M2 (Billions USD)
    dxy: pd.Series,         # US Dollar Index (for USD-conversion proxy)
) -> pd.Series:
    """
    Global M2 proxy using US M2 adjusted by DXY as a USD-strength correction.
    When DXY rises, the USD-equivalent of foreign M2 falls (and vice versa).
    This is a simplified proxy; a full computation would add EUR/CNY/JPY M2.

    Returns an index normalized to 100 at the start of the series.
    """
    combined = pd.DataFrame({"us_m2": us_m2, "dxy": dxy}).ffill().dropna()

    # DXY-adjusted M2: as DXY rises, global M2 (in USD) decreases
    # Proxy: us_m2 / (dxy / baseline_dxy)
    baseline_dxy = combined["dxy"].iloc[:252].mean() if len(combined) >= 252 else combined["dxy"].mean()
    if baseline_dxy == 0:
        return us_m2

    adj_m2 = combined["us_m2"] / (combined["dxy"] / baseline_dxy)
    adj_m2.name = "global_m2_proxy"
    return adj_m2


def compute_liquidity_metrics(raw_data: dict[str, pd.Series]) -> dict[str, pd.Series]:
    """
    Takes a dict of named raw series and returns derived liquidity metrics.

    Input keys: fed_balance_sheet, fed_reserves, on_rrp, tga, us_m2, dxy
    Output: dict with additional computed series
    """
    out = {}

    walcl = raw_data.get("fed_balance_sheet", pd.Series(dtype=float))
    tga = raw_data.get("tga", pd.Series(dtype=float))
    rrp = raw_data.get("on_rrp", pd.Series(dtype=float))
    us_m2 = raw_data.get("us_m2", pd.Series(dtype=float))
    dxy = raw_data.get("dxy", pd.Series(dtype=float))

    # Net Liquidity
    if not walcl.empty and not tga.empty and not rrp.empty:
        try:
            net_liq = compute_net_liquidity(walcl, tga, rrp)
            out["net_liquidity"] = net_liq
            # Weekly change
            out["net_liquidity_1w_chg"] = rate_of_change(net_liq, 1)
            out["net_liquidity_4w_chg"] = rate_of_change(net_liq, 4)
        except Exception as exc:
            logger.warning("Net liquidity compute error: %s", exc)

    # Fed BS weekly change
    if not walcl.empty:
        out["fed_bs_1w_chg"] = rate_of_change(walcl, 1)
        out["fed_bs_4w_chg"] = rate_of_change(walcl, 4)

    # ON RRP level change
    if not rrp.empty:
        out["on_rrp_1w_chg"] = rate_of_change(rrp, 1)

    # TGA drawdown
    if not tga.empty:
        out["tga_1w_chg"] = rate_of_change(tga, 1)

    # Global M2 proxy
    if not us_m2.empty and not dxy.empty:
        try:
            out["global_m2_proxy"] = compute_global_m2_proxy(us_m2, dxy)
        except Exception as exc:
            logger.warning("Global M2 proxy error: %s", exc)

    return out
