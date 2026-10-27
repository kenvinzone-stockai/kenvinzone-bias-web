"""
Market Bias Platform — Statistical Utilities
Rolling window statistics: Z-score, percentile rank, momentum, moving averages.
These are pure functions that operate on pandas Series.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ── Moving Averages ───────────────────────────────────────────────────────────

def simple_moving_average(series: pd.Series, window: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=window, min_periods=max(1, window // 2)).mean()


def exponential_moving_average(series: pd.Series, span: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()


# ── Z-Score ───────────────────────────────────────────────────────────────────

from typing import Optional


def infer_frequency(series: pd.Series) -> str:
    """Infer daily/weekly/monthly sampling from a datetime index."""
    if len(series) < 2 or not pd.api.types.is_datetime64_any_dtype(series.index):
        return "daily"
    index = pd.DatetimeIndex(series.index).drop_duplicates().sort_values()
    median_days = index.to_series().diff().dropna().dt.total_seconds().median() / 86_400
    if median_days >= 25:
        return "monthly"
    if median_days >= 5:
        return "weekly"
    return "daily"


def periods_for_frequency(freq: str) -> dict[str, Optional[int]]:
    """Map named calendar horizons to observation counts."""
    if freq == "monthly":
        return {"1w": None, "4w": 1, "13w": 3, "26w": 6, "52w": 12,
                "ma_21": 1, "ma_50": 3, "ma_200": 10, "year": 12}
    if freq == "weekly":
        return {"1w": 1, "4w": 4, "13w": 13, "26w": 26, "52w": 52,
                "ma_21": 4, "ma_50": 10, "ma_200": 40, "year": 52}
    return {"1w": 5, "4w": 21, "13w": 63, "26w": 126, "52w": 252,
            "ma_21": 21, "ma_50": 50, "ma_200": 200, "year": 252}

def get_window_min_periods(series: pd.Series, freq: Optional[str] = None) -> tuple[int, int]:
    if freq == "monthly":
        return 12, 6
    elif freq == "weekly":
        return 52, 26
    elif freq == "daily":
        return 252, 126
    
    if len(series) > 1 and pd.api.types.is_datetime64_any_dtype(series.index):
        delta = series.index.to_series().diff().median()
        if pd.notna(delta):
            if delta.days >= 25:
                return 12, 6
            elif delta.days >= 5:
                return 52, 26
    return 252, 126

def rolling_zscore(series: pd.Series, window: Optional[int] = None, freq: Optional[str] = None) -> pd.Series:
    """
    Rolling Z-score: (x - rolling_mean) / rolling_std
    Positive = above historical average, Negative = below.
    """
    if window is None:
        window, min_periods = get_window_min_periods(series, freq)
    else:
        min_periods = max(1, window // 2)
        
    roll = series.rolling(window=window, min_periods=min_periods)
    mean = roll.mean()
    std = roll.std()
    z = (series - mean) / std.replace(0, np.nan)
    return z


# ── Percentile Rank ───────────────────────────────────────────────────────────

def rolling_percentile_rank(series: pd.Series, window: Optional[int] = None, freq: Optional[str] = None) -> pd.Series:
    """
    Rolling percentile rank (0–100).
    100 = highest value in lookback window, 0 = lowest.
    """
    if window is None:
        window, min_periods = get_window_min_periods(series, freq)
    else:
        min_periods = max(1, window // 2)
        
    def _rank(arr: np.ndarray) -> float:
        if len(arr) == 0 or np.isnan(arr[-1]):
            return np.nan
        return float(np.sum(arr[:-1] <= arr[-1]) / max(len(arr) - 1, 1) * 100)

    return series.rolling(window=window, min_periods=min_periods).apply(_rank, raw=True)


# ── Momentum / Rate of Change ─────────────────────────────────────────────────

def rate_of_change(series: pd.Series, periods: int) -> pd.Series:
    """
    Percentage change over N periods.
    ROC = (current - n_periods_ago) / |n_periods_ago| * 100
    """
    prev = series.shift(periods)
    return (series - prev) / prev.abs().replace(0, np.nan) * 100


def absolute_change(series: pd.Series, periods: int) -> pd.Series:
    """Absolute change over N periods."""
    return series - series.shift(periods)


# ── Momentum Scoring ──────────────────────────────────────────────────────────

def compute_all_windows(series: pd.Series, freq: Optional[str] = None) -> pd.DataFrame:
    """
    Compute 1W, 4W, 13W, 26W, 52W rate-of-change for a series.
    Trading days: 1W≈5, 4W≈21, 13W≈63, 26W≈126, 52W≈252
    Returns a DataFrame with columns: value, chg_1w, chg_4w, chg_13w, chg_26w, chg_52w,
                                       ma_21, ma_50, ma_200, zscore_1y, pct_rank_1y
    """
    resolved_freq = freq or infer_frequency(series)
    periods = periods_for_frequency(resolved_freq)
    df = pd.DataFrame({"value": series})

    def _roc(period: Optional[int]) -> pd.Series:
        if period is None:
            return pd.Series(np.nan, index=series.index, dtype=float)
        return rate_of_change(series, period)

    df["chg_1w"]  = _roc(periods["1w"])
    df["chg_4w"]  = _roc(periods["4w"])
    df["chg_13w"] = _roc(periods["13w"])
    df["chg_26w"] = _roc(periods["26w"])
    df["chg_52w"] = _roc(periods["52w"])
    df["ma_21"]   = simple_moving_average(series, periods["ma_21"] or 1)
    df["ma_50"]   = simple_moving_average(series, periods["ma_50"] or 1)
    df["ma_200"]  = simple_moving_average(series, periods["ma_200"] or 1)
    df["zscore_1y"]   = rolling_zscore(series, periods["year"], freq=resolved_freq)
    df["pct_rank_1y"] = rolling_percentile_rank(series, periods["year"], freq=resolved_freq)
    return df


# ── Normalization ─────────────────────────────────────────────────────────────

def clamp(val: float, lo: float = -100.0, hi: float = 100.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, val))


def zscore_to_score(z: float, multiplier: float = 25.0) -> float:
    """
    Convert a Z-score to a bias score in [-100, +100].
    A Z of +2 → +50, Z of +4 → +100 (clamped).
    multiplier controls how sensitive the mapping is.
    """
    if np.isnan(z):
        return 0.0
    return clamp(z * multiplier)


def percentile_to_score(pct: float) -> float:
    """
    Map a 0–100 percentile rank to a -100…+100 score.
    50th percentile → 0 (neutral), 100th → +100, 0th → -100.
    """
    if np.isnan(pct):
        return 0.0
    return clamp((pct - 50) * 2)


def min_max_normalize(val: float, min_val: float, max_val: float,
                      target_lo: float = -100.0, target_hi: float = 100.0) -> float:
    """
    Min-max normalize val from [min_val, max_val] to [target_lo, target_hi].
    Used for COT Index computation.
    """
    if max_val == min_val:
        return 0.0
    return target_lo + (val - min_val) / (max_val - min_val) * (target_hi - target_lo)


# ── COT Index ─────────────────────────────────────────────────────────────────

def cot_index(series: pd.Series, window: int = 156) -> pd.Series:
    """
    3-Year COT Index: min-max normalization over the rolling window.
    Output: 0–100, where 0=extreme short, 100=extreme long.
    """
    roll_min = series.rolling(window=window, min_periods=window // 2).min()
    roll_max = series.rolling(window=window, min_periods=window // 2).max()
    return (series - roll_min) / (roll_max - roll_min).replace(0, np.nan) * 100
