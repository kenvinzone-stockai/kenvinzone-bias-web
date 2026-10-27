"""
Market Bias Platform — Global Liquidity Plugin
Fetches Central Bank balance sheets (ECB, BOJ, PBOC) to calculate Global M2/Liquidity.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional
import urllib.request
import json
import pandas as pd

from plugins.data.base import DataPlugin, FetchResult, make_records, PluginType, DataFrequency, HealthStatus
from core.config import settings

logger = logging.getLogger(__name__)

GLOBAL_LIQUIDITY_SERIES = {
    "ecb_assets": ("ECBASSETSW", "M EUR"),
    "boj_assets": ("JPNASSETS", "100M JPY"),
}

class GlobalLiquidityPlugin(DataPlugin):
    """Fetches international central bank data via FRED."""

    @property
    def name(self) -> str:
        return "global_liquidity"

    @property
    def description(self) -> str:
        return "ECB and BOJ Balance Sheets via FRED (PBoC not available)"

    @property
    def plugin_type(self) -> PluginType:
        return PluginType.MACRO

    @property
    def supported_frequencies(self) -> list[DataFrequency]:
        return [DataFrequency.MONTHLY]

    @property
    def requires_api_key(self) -> bool:
        return True

    @property
    def is_available(self) -> bool:
        return super().is_available and bool(settings.fred_api_key)

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
        
        for indicator, (series_id, unit) in GLOBAL_LIQUIDITY_SERIES.items():
            try:
                series = fred.get_series(
                    series_id,
                    observation_start=start_date.isoformat(),
                    observation_end=end_date.isoformat(),
                )
                if series is None or series.empty:
                    warnings_list.append(f"GlobalLiquidity: {series_id} returned no data")
                    continue

                for dt, val in series.items():
                    rows.append({
                        "indicator": indicator,
                        "date": dt,
                        "value": val,
                        "source": f"FRED:{series_id}",
                        "unit": unit,
                    })
            except Exception as exc:
                errors.append(f"FRED {series_id}: {exc}")
                logger.warning("GlobalLiquidity fetch failed for %s: %s", series_id, exc)

        df = make_records(rows)
        return FetchResult(plugin_name=self.name, records=df, errors=errors, warnings=warnings_list)
