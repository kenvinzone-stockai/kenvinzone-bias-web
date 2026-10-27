"""Directional US-dollar metrics for macro bias scoring."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from metrics.statistics import periods_for_frequency, rolling_zscore


def signed_log_return(series: pd.Series, periods: int) -> pd.Series:
    """Signed continuously compounded return in percentage points."""
    clean = pd.to_numeric(series, errors="coerce").where(lambda values: values > 0)
    return np.log(clean / clean.shift(periods)) * 100.0


def _latest_finite(series: pd.Series) -> Optional[float]:
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(clean.iloc[-1]) if not clean.empty else None


def _weighted_available(values: list[tuple[Optional[float], float]]) -> Optional[float]:
    available = [(value, weight) for value, weight in values if value is not None]
    total_weight = sum(weight for _value, weight in available)
    if not available or total_weight <= 0:
        return None
    return float(sum(value * weight for value, weight in available) / total_weight)


def _rolling_vol_scaled(series: pd.Series, window: int) -> pd.Series:
    """Scale a signed return by rolling volatility without changing its sign."""
    min_periods = max(6, window // 2)
    volatility = series.rolling(window=window, min_periods=min_periods).std()
    return series / volatility.replace(0, np.nan)


def compute_usd_direction_metrics(
    dxy: pd.Series,
    frequency: str,
) -> dict[str, Optional[float]]:
    """Build signed 4W/13W direction and unsigned shock metrics for DXY.

    Direction is a 65/35 blend of volatility-scaled signed 4W and 13W log
    returns. It is deliberately not mean-centered, so normalization can never
    flip the observed direction. Shock is the Z-score of the absolute shortest supported
    horizon (1W for daily/weekly data, 1M for monthly data).
    """
    clean = pd.to_numeric(dxy, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return {}

    periods = periods_for_frequency(frequency)
    period_4w = periods["4w"]
    period_13w = periods["13w"]
    period_shock = periods["1w"] or period_4w
    year_periods = periods["year"] or 252

    log_4w = signed_log_return(clean, period_4w)
    log_13w = signed_log_return(clean, period_13w)
    shock = signed_log_return(clean, period_shock).abs()

    strength_4w = _rolling_vol_scaled(log_4w.dropna(), year_periods)
    strength_13w = _rolling_vol_scaled(log_13w.dropna(), year_periods)
    shock_z = rolling_zscore(shock.dropna(), year_periods, freq=frequency)

    latest_log_4w = _latest_finite(log_4w)
    latest_log_13w = _latest_finite(log_13w)
    latest_strength_4w = _latest_finite(strength_4w)
    latest_strength_13w = _latest_finite(strength_13w)

    return {
        "dxy_log_return_4w": latest_log_4w,
        "dxy_log_return_13w": latest_log_13w,
        "dxy_signed_log_momentum": _weighted_available([
            (latest_log_4w, 0.65),
            (latest_log_13w, 0.35),
        ]),
        "dxy_direction_strength_1y": _weighted_available([
            (latest_strength_4w, 0.65),
            (latest_strength_13w, 0.35),
        ]),
        "dxy_abs_move": _latest_finite(shock),
        "dxy_shock_zscore_1y": _latest_finite(shock_z),
    }
