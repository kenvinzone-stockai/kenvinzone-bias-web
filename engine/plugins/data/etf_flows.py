"""
Market Bias Platform — Signed Turnover Proxy Plugin
Computes signed dollar turnover from volume and price direction. This is a
market-activity proxy and must not be presented as primary-market ETF flow.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from plugins.data.base import DataPlugin, FetchResult, make_records, PluginType, DataFrequency, HealthStatus

logger = logging.getLogger(__name__)

# ETF Tickers mapped to their platform indicators
ETFS = {
    "SPY": "spy_signed_turnover_proxy",
    "QQQ": "qqq_signed_turnover_proxy",
    "GLD": "gld_signed_turnover_proxy",
    "IAU": "iau_signed_turnover_proxy",
    "TLT": "tlt_signed_turnover_proxy",
    "HYG": "hyg_signed_turnover_proxy",
    "LQD": "lqd_signed_turnover_proxy",
}

class ETFFlowsPlugin(DataPlugin):
    """Computes signed turnover; does not estimate ETF creations/redemptions."""

    @property
    def name(self) -> str:
        return "etf_flows"

    @property
    def description(self) -> str:
        return "ETF Signed Turnover Proxy (not creations/redemptions)"

    @property
    def plugin_type(self) -> PluginType:
        return PluginType.MARKET
        
    @property
    def supported_frequencies(self) -> list[DataFrequency]:
        return [DataFrequency.DAILY]

    def health_check(self) -> HealthStatus:
        if not self.is_available:
            return HealthStatus(healthy=False, message="Disabled")
        try:
            # Just do a quick yfinance fetch
            import time
            t0 = time.time()
            ticker = yf.Ticker("SPY")
            info = ticker.history(period="1d")
            lat = (time.time() - t0) * 1000
            if not info.empty:
                return HealthStatus(healthy=True, latency_ms=lat, message="OK")
            return HealthStatus(healthy=False, message="No data returned")
        except Exception as exc:
            return HealthStatus(healthy=False, message=str(exc))

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        rows = []
        errors = []
        warnings_list = []
        
        # Need a slightly larger window to calculate price change
        query_start = start_date - timedelta(days=5)

        for ticker, indicator in ETFS.items():
            try:
                t = yf.Ticker(ticker)
                df = t.history(start=query_start.isoformat(), end=(end_date + timedelta(days=1)).isoformat())
                
                if df.empty:
                    warnings_list.append(f"ETFFlows: No data for {ticker}")
                    continue
                    
                # Calculate daily return to determine flow direction
                df["Prev_Close"] = df["Close"].shift(1)
                df["Ret"] = df["Close"] / df["Prev_Close"] - 1
                
                # Filter to requested date range
                df = df[df.index.date >= start_date]
                
                for dt, row in df.iterrows():
                    # Signed turnover = Volume * Typical Price * sign(Return).
                    typical_price = (row["High"] + row["Low"] + row["Close"]) / 3
                    direction = 1 if row["Ret"] > 0 else (-1 if row["Ret"] < 0 else 0)
                    signed_turnover_usd = row["Volume"] * typical_price * direction
                    
                    # Convert to Millions of USD
                    signed_turnover_m_usd = signed_turnover_usd / 1_000_000
                    
                    rows.append({
                        "indicator": indicator,
                        "date": dt.date(),
                        "value": signed_turnover_m_usd,
                        "source": f"yfinance:{ticker}",
                        "unit": "M USD",
                    })
                    
            except Exception as exc:
                errors.append(f"Failed to fetch {ticker}: {exc}")
                logger.warning("ETF flows fetch failed for %s: %s", ticker, exc)

        df = make_records(rows)
        return FetchResult(plugin_name=self.name, records=df, errors=errors, warnings=warnings_list)
