"""
Market Bias Platform — CBOE Data Plugin
Fetches free delayed/EOD volatility data from CBOE:
  - VIX spot
  - VIX3M
  - VIX6M

Note: the public put/call ratio chart files (_EPC/_IPC/_PC under
cdn.cboe.com/api/global/delayed_quotes/charts/historical/) were retired by
CBOE in 2026 and now return S3 AccessDenied. Market-wide P/C ratios are no
longer available from a free CBOE endpoint; per-ETF P/C proxies from option
chains (spy_pc_ratio_oi, qqq_pc_ratio_oi, gld_pc_ratio_oi) remain available
via the yfinance options plugin.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import requests

from plugins.data.base import DataPlugin, FetchResult, make_records

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

# CBOE still serves these historical chart files (200 OK); the JSON points are
# dicts like {"date": "2026-09-28", "open": ..., "close": "16.07", ...}.
VIX_ENDPOINTS = {
    "vix_spot":   "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_VIX.json",
    "vix3m_cboe": "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_VIX3M.json",
    "vix6m_cboe": "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_VIX6M.json",
}


class CBOEPlugin(DataPlugin):
    """Fetches CBOE VIX term structure (spot, 3M, 6M)."""

    @property
    def name(self) -> str:
        return "cboe"

    @property
    def description(self) -> str:
        return "CBOE — VIX Term Structure (spot, 3M, 6M)"

    @staticmethod
    def _parse_point(point) -> tuple[date, float] | None:
        """Return (date, close) for one chart point, or None.

        Current CBOE format is a dict with string fields; older snapshots of
        the API returned [timestamp, value] pairs, which are still accepted.
        """
        if isinstance(point, dict):
            raw_date = point.get("date") or point.get("datetime")
            raw_value = point.get("close")
            if raw_date is None or raw_value is None:
                return None
            try:
                dt = pd.Timestamp(raw_date).date()
                return dt, float(raw_value)
            except (TypeError, ValueError):
                return None
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                dt = pd.Timestamp(point[0]).date()
                return dt, float(point[1])
            except (TypeError, ValueError):
                return None
        return None

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        rows = []
        errors = []
        warnings_list = [
            "CBOE retired the public put/call ratio chart files (_EPC/_IPC/_PC); "
            "market-wide P/C ratios are no longer fetched. Use the per-ETF "
            "option-chain P/C proxies from yfinance instead."
        ]

        for indicator, url in VIX_ENDPOINTS.items():
            try:
                resp = requests.get(url, headers=BROWSER_HEADERS, timeout=20)
                resp.raise_for_status()
                chart_data = resp.json().get("data", [])
                for point in chart_data:
                    parsed = self._parse_point(point)
                    if parsed is None:
                        continue
                    dt, value = parsed
                    if start_date <= dt <= end_date:
                        rows.append({
                            "indicator": indicator,
                            "date": dt,
                            "value": value,
                            "source": f"CBOE:{url}",
                            "unit": "index",
                        })
            except Exception as exc:
                errors.append(f"CBOE VIX term {indicator}: {exc}")
                logger.debug("CBOE %s failed: %s", indicator, exc)

        df = make_records(rows) if rows else pd.DataFrame(
            columns=["indicator", "date", "value", "source", "unit"]
        )
        return FetchResult(plugin_name=self.name, records=df, errors=errors, warnings=warnings_list)
