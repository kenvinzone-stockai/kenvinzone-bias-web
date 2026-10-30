"""
Market Bias Platform — Options Metrics
GEX (Gamma Exposure) computation using Black-Scholes gamma from option chain data.
Also computes approximate Gamma Flip level and key OI walls.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

logger = logging.getLogger(__name__)


def _finite_float(value, default: float = 0.0) -> float:
    """Coerce provider fields without allowing NaN/inf to poison aggregates."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def black_scholes_gamma(
    S: float, K: float, T: float, r: float, sigma: float
) -> float:
    """
    Compute Black-Scholes Gamma for a European option.

    Args:
        S: Spot price of the underlying
        K: Strike price
        T: Time to expiration in years
        r: Risk-free rate (e.g., 0.045 for 4.5%)
        sigma: Implied volatility (annualised, e.g., 0.20 for 20%)

    Returns:
        Gamma (∂²V/∂S²)
    """
    if not all(np.isfinite(value) for value in (S, K, T, r, sigma)):
        return 0.0
    if T <= 1e-6 or sigma <= 1e-6 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        return float(gamma)
    except Exception:
        return 0.0


def compute_gex_from_chain(
    spot: float,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    risk_free_rate: float = 0.045,
    multiplier: int = 100,
) -> tuple[float, Optional[float]]:
    """
    Compute aggregate Net GEX and approximate Gamma Flip level.

    Formula per strike:
        GEX_call = Gamma * OI * multiplier * S^2 * 0.01
        GEX_put  = -Gamma * OI * multiplier * S^2 * 0.01  (puts subtract)
        Net GEX  = sum(GEX_call) + sum(GEX_put)

    Args:
        spot: Current price of the underlying
        calls: DataFrame with columns: strike, openInterest, impliedVolatility, daysToExpiration
        puts:  Same schema for puts
        risk_free_rate: Annualised risk-free rate
        multiplier: Contract multiplier (100 for equity options)

    Returns:
        (net_gex_dollars, gamma_flip_price_or_None)
    """
    spot_sq_0_01 = spot ** 2 * 0.01

    def _strike_gex(row: pd.Series, sign: float) -> float:
        oi = _finite_float(row.get("openInterest", 0))
        iv = _finite_float(row.get("impliedVolatility", 0))
        K = _finite_float(row.get("strike", 0))
        dte = _finite_float(row.get("daysToExpiration", 0))
        T = dte / 365.0
        if oi == 0 or iv == 0 or K == 0:
            return 0.0
        gamma = black_scholes_gamma(spot, K, T, risk_free_rate, iv)
        return sign * gamma * oi * multiplier * spot_sq_0_01

    total_gex = 0.0
    # Accumulate call GEX
    for _, row in calls.iterrows():
        total_gex += _strike_gex(row, +1.0)

    # Accumulate put GEX (subtract)
    for _, row in puts.iterrows():
        total_gex += _strike_gex(row, -1.0)

    # ── Gamma Flip Level ──────────────────────────────────────────────────
    # Walk through price levels near spot; find where net GEX crosses zero
    gamma_flip = _find_gamma_flip(spot, calls, puts, risk_free_rate, multiplier)

    return total_gex, gamma_flip


def _find_gamma_flip(
    spot: float,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    r: float,
    multiplier: int,
) -> Optional[float]:
    """
    Find the approximate Gamma Flip level by scanning price levels ±20% from spot.
    Returns the price level where Net GEX changes sign (negative → positive = flip up).
    """
    try:
        levels = np.arange(spot * 0.80, spot * 1.20, spot * 0.001)
        gex_by_level = []

        for price_level in levels:
            spot_sq_0_01 = price_level ** 2 * 0.01
            gex = 0.0
            for _, row in calls.iterrows():
                K = _finite_float(row.get("strike", 0))
                T = _finite_float(row.get("daysToExpiration", 30)) / 365
                iv = _finite_float(row.get("impliedVolatility", 0))
                oi = _finite_float(row.get("openInterest", 0))
                gamma = black_scholes_gamma(price_level, K, T, r, iv)
                gex += gamma * oi * multiplier * spot_sq_0_01
            for _, row in puts.iterrows():
                K = _finite_float(row.get("strike", 0))
                T = _finite_float(row.get("daysToExpiration", 30)) / 365
                iv = _finite_float(row.get("impliedVolatility", 0))
                oi = _finite_float(row.get("openInterest", 0))
                gamma = black_scholes_gamma(price_level, K, T, r, iv)
                gex -= gamma * oi * multiplier * spot_sq_0_01
            gex_by_level.append(gex)

        gex_arr = np.array(gex_by_level)
        # Find zero crossing (sign change)
        sign_changes = np.where(np.diff(np.sign(gex_arr)))[0]
        if len(sign_changes) > 0:
            # Return the level closest to spot
            flip_indices = sign_changes
            flip_prices = levels[flip_indices]
            closest_idx = np.argmin(np.abs(flip_prices - spot))
            return float(flip_prices[closest_idx])
    except Exception as exc:
        logger.debug("Gamma flip calculation failed: %s", exc)

    return None


def compute_oi_walls(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    top_n: int = 5,
    spot: Optional[float] = None,
) -> dict:
    """
    Identify the highest open-interest strikes for calls and puts (option walls).
    If spot is provided, prioritizes actionable strikes in the near-term trading corridor.

    Returns:
        {
            "call_walls": [(strike, oi), ...],
            "put_walls":  [(strike, oi), ...],
        }
    """
    def _top_strikes(df: pd.DataFrame, min_ratio: float = 0.5, max_ratio: float = 1.5) -> list[tuple[float, float]]:
        if df.empty or "strike" not in df.columns:
            return []
        valid = df.copy()
        valid["strike_num"] = pd.to_numeric(valid["strike"], errors="coerce")
        valid["oi_num"] = pd.to_numeric(valid.get("openInterest", 0), errors="coerce").fillna(0)
        valid = valid.dropna(subset=["strike_num"])
        if spot and spot > 0:
            near = valid[valid["strike_num"].between(spot * min_ratio, spot * max_ratio)]
            if not near.empty and near["oi_num"].sum() > 0:
                valid = near
        grouped = valid.groupby("strike_num")["oi_num"].sum().sort_values(ascending=False)
        return [(float(k), float(v)) for k, v in grouped.head(top_n).items()]

    return {
        "call_walls": _top_strikes(calls, min_ratio=0.88, max_ratio=1.15),
        "put_walls":  _top_strikes(puts, min_ratio=0.85, max_ratio=1.12),
    }
