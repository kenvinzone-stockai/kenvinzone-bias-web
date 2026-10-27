"""Official GLD holdings and primary-market flow estimates.

The SPDR archive publishes holdings, ounces per share and NAV.  Share creation
or redemption value is derived as the daily change in shares outstanding times
that day's NAV.  It is materially closer to primary-market flow than signed
exchange turnover, but remains an estimate rather than a fund-reported cashflow.
"""
from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import pandas as pd
import requests

from plugins.data.base import DataFrequency, DataPlugin, FetchResult, PluginType, make_records


GLD_ARCHIVE_URL = (
    "https://api.spdrgoldshares.com/api/v1/historical-archive"
    "?exchange=NYSE&lang=en&product=gld"
)
GLD_INDICATORS = [
    "gld_shares_outstanding_official",
    "gld_gold_tonnes_official",
    "gld_primary_market_flow",
    "gld_gold_tonnes_change",
]


class GLDOfficialFlowsPlugin(DataPlugin):
    @property
    def name(self) -> str:
        return "gld_official_flows"

    @property
    def description(self) -> str:
        return "Official SPDR GLD holdings and estimated creations/redemptions"

    @property
    def plugin_type(self) -> PluginType:
        return PluginType.MARKET

    @property
    def supported_frequencies(self) -> list[DataFrequency]:
        return [DataFrequency.DAILY]

    @property
    def supported_instruments(self) -> list[str]:
        return ["GLD"]

    @staticmethod
    def _parse_workbook(content: bytes, start_date: date, end_date: date) -> pd.DataFrame:
        frame = pd.read_excel(BytesIO(content), sheet_name="US GLD Historical Archive")
        required = {
            "Date", "Ounces of Gold per Share", "NAV/Share at 10:30am NYT",
            "Total Ounces of Gold in the Trust", "Tonnes of Gold",
        }
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"GLD archive missing columns: {', '.join(sorted(missing))}")

        frame = frame[list(required)].copy()
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        numeric = required.difference({"Date"})
        for column in numeric:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["Date"]).sort_values("Date")
        frame = frame[frame["Ounces of Gold per Share"] > 0]
        frame["shares"] = (
            frame["Total Ounces of Gold in the Trust"]
            / frame["Ounces of Gold per Share"]
        )
        frame["flow_m_usd"] = (
            frame["shares"].diff() * frame["NAV/Share at 10:30am NYT"] / 1_000_000
        )
        frame["tonnes_change"] = frame["Tonnes of Gold"].diff()

        rows: list[dict] = []
        source = "SPDRGoldShares:GLD_historical_archive"
        for _, item in frame.iterrows():
            observation_date = item["Date"].date()
            if not start_date <= observation_date <= end_date:
                continue
            observed_at = observation_date + timedelta(days=1)
            values = [
                (GLD_INDICATORS[0], item["shares"], "shares"),
                (GLD_INDICATORS[1], item["Tonnes of Gold"], "tonnes"),
                (GLD_INDICATORS[2], item["flow_m_usd"], "M USD"),
                (GLD_INDICATORS[3], item["tonnes_change"], "tonnes"),
            ]
            for indicator, value, unit in values:
                if pd.notna(value):
                    rows.append({
                        "indicator": indicator,
                        "date": observation_date,
                        "value": float(value),
                        "source": source,
                        "unit": unit,
                        # The archive notes that each trading day's holdings
                        # become available on the following business update.
                        "observed_at": observed_at,
                        "vintage_source": source,
                    })
        return make_records(rows)

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        response = requests.get(
            GLD_ARCHIVE_URL,
            headers={"User-Agent": "MarketBiasPlatform/1.0"},
            timeout=(10, 35),
        )
        response.raise_for_status()
        records = self._parse_workbook(response.content, start_date, end_date)
        warnings = [] if not records.empty else ["GLD archive returned no observations in range"]
        return FetchResult(plugin_name=self.name, records=records, warnings=warnings)
