"""
Market Bias Platform — Breadth Data Plugin

Fetches price data for S&P 500 constituents and computes:
- % above 20/50/200 DMA
- Advance/Decline Line
- McClellan Oscillator & Summation
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from plugins.data.base import DataPlugin, FetchResult, make_records, PluginType, DataFrequency, HealthStatus
from metrics import breadth

logger = logging.getLogger(__name__)

MIN_SPX_UNIVERSE_SIZE = 400
MIN_DAILY_COVERAGE_RATIO = 0.80


def has_sufficient_daily_coverage(
    prices: pd.Series,
    expected_constituents: int,
    minimum_ratio: float = MIN_DAILY_COVERAGE_RATIO,
) -> bool:
    """Return whether a daily cross-section is broad enough to be credible."""
    required = math.ceil(expected_constituents * minimum_ratio)
    return int(prices.notna().sum()) >= required


class BreadthPlugin(DataPlugin):
    """Computes breadth metrics using SPX constituent data."""

    @property
    def name(self) -> str:
        return "breadth"

    @property
    def description(self) -> str:
        return "Market Breadth (A/D Line, % > MA, McClellan)"

    @property
    def plugin_type(self) -> PluginType:
        return PluginType.MARKET
        
    @property
    def supported_frequencies(self) -> list[DataFrequency]:
        return [DataFrequency.DAILY, DataFrequency.WEEKLY]

    def health_check(self) -> HealthStatus:
        if not self.is_available:
            return HealthStatus(healthy=False, message="Disabled")
        # Wikipedia fetch test
        import time
        t0 = time.time()
        try:
            tickers = breadth.get_sp500_tickers()
            lat = (time.time() - t0) * 1000
            if len(tickers) > 400:
                return HealthStatus(healthy=True, latency_ms=lat, message="OK")
            return HealthStatus(healthy=False, message="Low ticker count")
        except Exception as exc:
            return HealthStatus(healthy=False, message=str(exc))

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        rows = []
        errors = []
        warnings_list = []
        
        # A true 52-week high/low needs 252 trading sessions.  The extra
        # calendar buffer covers weekends, holidays and occasional gaps.
        query_start = start_date - timedelta(days=420)
        
        try:
            tickers = breadth.get_sp500_tickers()
            if len(tickers) < MIN_SPX_UNIVERSE_SIZE:
                raise ValueError(
                    f"Breadth universe contains only {len(tickers)} symbols; "
                    f"at least {MIN_SPX_UNIVERSE_SIZE} are required"
                )
            logger.info("Fetching price data for %d SPX constituents...", len(tickers))
            
            # yfinance bulk download
            data = yf.download(
                tickers, 
                start=query_start.isoformat(), 
                end=(end_date + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                progress=False,
                threads=True
            )
            
            if data.empty:
                raise ValueError("No data returned from yfinance")
                
            closes = data['Close']
            
            # Count daily advances and declines
            daily_returns = closes.pct_change()
            advances = (daily_returns > 0).sum(axis=1)
            declines = (daily_returns < 0).sum(axis=1)
            
            # Compute metrics
            mcclellan_osc = breadth.compute_mcclellan_oscillator(advances, declines)
            mcclellan_sum = breadth.compute_mcclellan_summation(mcclellan_osc)
            ad_line = breadth.compute_advance_decline_line(advances, declines)
            
            pct_above_20 = breadth.compute_pct_above_ma(closes, 20)
            pct_above_50 = breadth.compute_pct_above_ma(closes, 50)
            pct_above_200 = breadth.compute_pct_above_ma(closes, 200)
            
            net_new_highs = breadth.compute_highs_lows_ratio(closes, 252)
            
            # Filter output to requested date range
            mask = (closes.index.date >= start_date) & (closes.index.date <= end_date)
            
            dates = closes.index[mask]
            for dt in dates:
                if not has_sufficient_daily_coverage(closes.loc[dt], len(tickers)):
                    available = int(closes.loc[dt].notna().sum())
                    warnings_list.append(
                        f"Skipped {dt.date()}: only {available}/{len(tickers)} "
                        "constituents have prices"
                    )
                    continue

                dt_str = dt.date()
                daily_rows = [
                    {"indicator": "mcclellan_oscillator", "date": dt_str, "value": float(mcclellan_osc.loc[dt]), "source": "yf_breadth", "unit": "idx"},
                    {"indicator": "spx_mcclellan_sum", "date": dt_str, "value": float(mcclellan_sum.loc[dt]), "source": "yf_breadth", "unit": "idx"},
                    {"indicator": "advance_decline_line", "date": dt_str, "value": float(ad_line.loc[dt]), "source": "yf_breadth", "unit": "idx"},
                    {"indicator": "pct_above_20ma", "date": dt_str, "value": float(pct_above_20.loc[dt]), "source": "yf_breadth", "unit": "%"},
                    {"indicator": "pct_above_50ma", "date": dt_str, "value": float(pct_above_50.loc[dt]), "source": "yf_breadth", "unit": "%"},
                    {"indicator": "pct_above_200ma", "date": dt_str, "value": float(pct_above_200.loc[dt]), "source": "yf_breadth", "unit": "%"},
                    {"indicator": "spx_net_new_highs", "date": dt_str, "value": float(net_new_highs.loc[dt]), "source": "yf_breadth", "unit": "%"},
                ]
                finite_rows = [row for row in daily_rows if pd.notna(row["value"])]
                if len(finite_rows) != len(daily_rows):
                    missing = [row["indicator"] for row in daily_rows if pd.isna(row["value"])]
                    warnings_list.append(
                        f"Skipped immature metrics for {dt.date()}: {', '.join(missing)}"
                    )
                rows.extend(finite_rows)
                
        except Exception as exc:
            errors.append(f"Breadth fetch failed: {exc}")
            logger.exception("Breadth fetch exception: %s", exc)
            
        df = make_records(rows)
        return FetchResult(plugin_name=self.name, records=df, errors=errors, warnings=warnings_list)
