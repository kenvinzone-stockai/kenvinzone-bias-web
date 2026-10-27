"""
Market Bias Platform — FRED Data Plugin
Fetches Fed liquidity, interest rates, and credit spread data from the
Federal Reserve Economic Data (FRED) API.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional
import urllib.request
import json

import pandas as pd

from core.config import settings
from plugins.data.base import DataPlugin, FetchResult, make_records, PluginType, DataFrequency, HealthStatus

logger = logging.getLogger(__name__)

# ── FRED Series Catalogue ─────────────────────────────────────────────────────
# Format: indicator_name -> (series_id, unit, frequency, description)
FRED_SERIES: dict[str, tuple[str, str, DataFrequency, str]] = {
    # ── Liquidity ──────────────────────────────────────────────────────────
    "fed_balance_sheet":    ("WALCL",       "M USD",  DataFrequency.WEEKLY, "Fed Total Assets"),
    "fed_reserves":         ("WRESBAL",     "M USD",  DataFrequency.WEEKLY, "Reserve Balances"),
    "on_rrp":               ("RRPONTSYD",   "B USD",  DataFrequency.DAILY,  "Overnight Reverse Repo"),
    "tga":                  ("WTREGEN",     "M USD",  DataFrequency.WEEKLY, "Treasury General Account"),

    # ── Rates ──────────────────────────────────────────────────────────────
    "fed_funds_rate":       ("DFF",         "%",      DataFrequency.DAILY,  "Effective Federal Funds Rate"),
    "sofr":                 ("SOFR",        "%",      DataFrequency.DAILY,  "SOFR"),
    "us_2y_yield":          ("DGS2",        "%",      DataFrequency.DAILY,  "2-Year Treasury"),
    "us_5y_yield":          ("DGS5",        "%",      DataFrequency.DAILY,  "5-Year Treasury"),
    "us_10y_yield":         ("DGS10",       "%",      DataFrequency.DAILY,  "10-Year Treasury"),
    "us_30y_yield":         ("DGS30",       "%",      DataFrequency.DAILY,  "30-Year Treasury"),
    "us_10y_real_yield":    ("DFII10",      "%",      DataFrequency.DAILY,  "10-Year TIPS Real Yield"),
    "us_5y_real_yield":     ("DFII5",       "%",      DataFrequency.DAILY,  "5-Year TIPS Real Yield"),

    # ── Credit Spreads ─────────────────────────────────────────────────────
    "hy_oas":               ("BAMLH0A0HYM2",   "%", DataFrequency.DAILY,  "US HY OAS"),
    "ig_oas":               ("BAMLC0A0CM",     "%", DataFrequency.DAILY,  "US IG OAS"),
    "hy_bb_oas":            ("BAMLH0A1HYBB",   "%", DataFrequency.DAILY,  "US BB OAS"),
    "nfci":                 ("NFCI",           "idx", DataFrequency.WEEKLY, "Chicago Fed National Financial Conditions"),

    # ── VIX ──────────────────────────────────────────────────────────────
    "vix_fred":             ("VIXCLS",      "index",  DataFrequency.DAILY,  "CBOE Volatility Index (VIX)"),

    # ── Monetary ───────────────────────────────────────────────────────────
    "us_m2":                ("WM2NS",       "B USD",  DataFrequency.WEEKLY, "M2 Money Supply"),
}


class FREDPlugin(DataPlugin):
    """Fetches macro data series from FRED."""

    @property
    def name(self) -> str:
        return "fred"

    @property
    def description(self) -> str:
        return "FRED — Liquidity, Rates, Spreads"

    @property
    def plugin_type(self) -> PluginType:
        return PluginType.MACRO

    @property
    def supported_frequencies(self) -> list[DataFrequency]:
        return [DataFrequency.DAILY, DataFrequency.WEEKLY, DataFrequency.MONTHLY]

    @property
    def requires_api_key(self) -> bool:
        return True

    @property
    def is_available(self) -> bool:
        return super().is_available and bool(settings.fred_api_key)

    @property
    def rate_limit_calls_per_minute(self) -> int:
        return 120  # FRED default rate limit

    def health_check(self) -> HealthStatus:
        if not self.is_available:
            return HealthStatus(healthy=False, message="Disabled or API key missing")
        try:
            url = f"https://api.stlouisfed.org/fred/category?category_id=125&api_key={settings.fred_api_key}&file_type=json"
            import time
            t0 = time.time()
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    lat = (time.time() - t0) * 1000
                    return HealthStatus(healthy=True, latency_ms=lat, message="OK")
                return HealthStatus(healthy=False, message=f"HTTP {response.status}")
        except Exception as exc:
            return HealthStatus(healthy=False, message=str(exc))

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        try:
            from fredapi import Fred
        except ImportError:
            raise RuntimeError("fredapi not installed")

        fred = Fred(api_key=settings.fred_api_key)
        rows = []
        errors = []
        warnings_list = []

        for indicator, (series_id, unit, freq, _desc) in FRED_SERIES.items():
            try:
                series = fred.get_series(
                    series_id,
                    observation_start=start_date.isoformat(),
                    observation_end=end_date.isoformat(),
                )
                if series is None or series.empty:
                    warnings_list.append(f"FRED: {series_id} returned no data")
                    continue

                for dt, val in series.items():
                    rows.append({
                        "indicator": indicator,
                        "date": dt,
                        "value": val,
                        "source": f"FRED:{series_id}",
                        "unit": unit,
                        "frequency": freq.value,
                    })
            except Exception as exc:
                errors.append(f"FRED {series_id}: {exc}")
                logger.warning("FRED fetch failed for %s: %s", series_id, exc)

        df = make_records(rows)
        return FetchResult(plugin_name=self.name, records=df, errors=errors, warnings=warnings_list)
