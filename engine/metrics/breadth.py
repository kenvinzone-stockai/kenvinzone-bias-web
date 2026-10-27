"""
Market Bias Platform — Breadth Metrics
Computes McClellan Oscillator, Advance/Decline Line, and % stocks above MAs
using constituent price data fetched via yfinance.
"""
from __future__ import annotations

import logging
from io import StringIO
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def compute_mcclellan_oscillator(advances: pd.Series, declines: pd.Series) -> pd.Series:
    """
    McClellan Oscillator = EMA_19(Net Advances) - EMA_39(Net Advances)
    Net Advances = Advances - Declines
    """
    net_advances = advances - declines
    ema_19 = net_advances.ewm(span=19, adjust=False).mean()
    ema_39 = net_advances.ewm(span=39, adjust=False).mean()
    return ema_19 - ema_39


def compute_mcclellan_summation(oscillator: pd.Series) -> pd.Series:
    """McClellan Summation Index = cumulative sum of Oscillator values."""
    return oscillator.cumsum()


def compute_advance_decline_line(advances: pd.Series, declines: pd.Series) -> pd.Series:
    """
    Advance/Decline Line = cumulative sum of (Advances - Declines).
    Rising A/D = broad participation in trend.
    """
    return (advances - declines).cumsum()


def compute_pct_above_ma(prices_df: pd.DataFrame, ma_window: int = 200) -> pd.Series:
    """
    Compute the percentage of stocks in a universe above their N-day moving average.
    
    Args:
        prices_df: DataFrame where each column is a stock's closing price
        ma_window: Moving average window (e.g., 50 or 200)
    
    Returns:
        Series of percentages (0-100)
    """
    # A stock is eligible only after it has a complete N-session history.
    # Counting a stock that has a current quote but no MA in the denominator
    # silently classifies it as "below MA" and can turn a partial Yahoo row
    # into a false 0% breadth reading.
    ma = prices_df.rolling(window=ma_window, min_periods=ma_window).mean()
    eligible = prices_df.notna() & ma.notna()
    above_ma = ((prices_df > ma) & eligible).sum(axis=1)
    eligible_stocks = eligible.sum(axis=1)
    return (above_ma / eligible_stocks.replace(0, np.nan)) * 100


def compute_highs_lows_ratio(prices_df: pd.DataFrame, lookback: int = 252) -> pd.Series:
    """
    Net New Highs = (New 52W Highs - New 52W Lows) / Total Stocks
    """
    # A 52-week high/low requires the full 252-session lookback.  A shorter
    # history is not equivalent and must not be labelled as a 52-week signal.
    rolling_max = prices_df.rolling(lookback, min_periods=lookback).max()
    rolling_min = prices_df.rolling(lookback, min_periods=lookback).min()

    eligible = prices_df.notna() & rolling_max.notna() & rolling_min.notna()
    new_highs = ((prices_df >= rolling_max) & eligible).sum(axis=1)
    new_lows = ((prices_df <= rolling_min) & eligible).sum(axis=1)
    total = eligible.sum(axis=1).replace(0, np.nan)

    return (new_highs - new_lows) / total * 100


def get_sp500_tickers() -> list[str]:
    """
    Fetch S&P 500 constituent tickers from Wikipedia.
    Returns a list of ticker strings.
    """
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        # pandas 2.x treats an unwrapped HTML string as a filesystem path.
        tables = pd.read_html(StringIO(resp.text))
        sp500_table = tables[0]
        tickers = sp500_table["Symbol"].str.replace(".", "-", regex=False).tolist()
        return tickers
    except Exception as exc:
        logger.warning("Failed to fetch S&P 500 tickers from Wikipedia: %s", exc)
        # Fallback: return a minimal subset
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "BRK-B",
            "JPM", "UNH", "V", "XOM", "MA", "LLY", "HD", "CVX", "MRK", "ABBV",
            "PEP", "COST", "AVGO", "KO", "WMT", "BAC", "MCD", "CRM", "ACN",
            "CSCO", "ADBE", "PFE", "AMD", "NFLX", "LIN", "TMO", "ORCL", "ABT",
            "DHR", "TXN", "PM", "DIS", "VZ", "INTC", "UPS", "NEE", "MS", "RTX",
            "GS", "INTU", "SPGI", "HON",
        ]
