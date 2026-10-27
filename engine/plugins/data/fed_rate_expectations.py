"""Free official market-implied policy distributions from the Atlanta Fed.

This is the Atlanta Fed Market Probability Tracker (MPT), derived from CME
three-month SOFR options.  It is not branded or represented as CME FedWatch.
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO

import pandas as pd
import requests

from plugins.data.base import DataFrequency, DataPlugin, FetchResult, PluginType, make_records


MPT_HISTORY_URL = (
    "https://www.frbatlanta.org/-/media/Project/Atlanta/FRBA/Documents/"
    "research-and-data/data/market-probability-tracker/mpt_histdata.xlsx"
)
FED_RATE_EXPECTATION_INDICATORS = [
    f"fed_policy_{metric}_{horizon}"
    for horizon in ("near", "next")
    for metric in (
        "hike_probability", "cut_probability", "hold_probability",
        "expected_rate", "expected_change_bps", "horizon_days",
    )
]


def _target_midpoint_bps(label: object) -> float | None:
    match = re.search(r"([\d.]+)bps\s*-\s*([\d.]+)bps", str(label))
    if not match:
        return None
    return (float(match.group(1)) + float(match.group(2))) / 2


class FedRateExpectationsPlugin(DataPlugin):
    @property
    def name(self) -> str:
        return "fed_rate_expectations"

    @property
    def description(self) -> str:
        return "Atlanta Fed MPT policy hike/cut probabilities from SOFR options"

    @property
    def plugin_type(self) -> PluginType:
        return PluginType.MACRO

    @property
    def supported_frequencies(self) -> list[DataFrequency]:
        return [DataFrequency.DAILY]

    @staticmethod
    def _parse_workbook(content: bytes, start_date: date, end_date: date) -> pd.DataFrame:
        raw = pd.read_excel(BytesIO(content), sheet_name="DATA")
        required = {"date", "reference_start", "target_range", "field", "value"}
        missing = required.difference(raw.columns)
        if missing:
            raise ValueError(f"Atlanta Fed MPT missing columns: {', '.join(sorted(missing))}")

        raw = raw[list(required)].copy()
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
        raw["reference_start"] = pd.to_datetime(raw["reference_start"], errors="coerce")
        raw["value"] = pd.to_numeric(raw["value"], errors="coerce")
        raw = raw.dropna(subset=["date", "reference_start", "field", "value"])
        raw = raw[raw["field"].isin(["Prob: hike", "Prob: cut", "Rate: mean"])]

        rows: list[dict] = []
        source = "AtlantaFed:Market_Probability_Tracker"
        for observed_ts, dated in raw.groupby("date"):
            observed_date = observed_ts.date()
            if not start_date <= observed_date <= end_date:
                continue
            future_refs = sorted(
                ref for ref in dated["reference_start"].dropna().unique()
                if pd.Timestamp(ref).date() >= observed_date
            )[:2]
            for horizon, reference in zip(("near", "next"), future_refs):
                block = dated[dated["reference_start"] == reference]
                values = block.groupby("field")["value"].last().to_dict()
                if not {"Prob: hike", "Prob: cut", "Rate: mean"}.issubset(values):
                    continue
                hike = float(values["Prob: hike"])
                cut = float(values["Prob: cut"])
                expected_rate_bps = float(values["Rate: mean"])
                hold = max(0.0, min(100.0, 100.0 - hike - cut))
                midpoint = _target_midpoint_bps(block["target_range"].dropna().iloc[-1])
                metrics = {
                    "hike_probability": (hike, "%"),
                    "cut_probability": (cut, "%"),
                    "hold_probability": (hold, "%"),
                    "expected_rate": (expected_rate_bps / 100.0, "%"),
                    "expected_change_bps": (
                        expected_rate_bps - midpoint if midpoint is not None else float("nan"),
                        "bps",
                    ),
                    "horizon_days": ((pd.Timestamp(reference).date() - observed_date).days, "days"),
                }
                for metric, (value, unit) in metrics.items():
                    if pd.notna(value):
                        rows.append({
                            "indicator": f"fed_policy_{metric}_{horizon}",
                            "date": observed_date,
                            "value": float(value),
                            "source": source,
                            "unit": unit,
                            "observed_at": observed_date,
                            "vintage_source": source,
                            "vintage_id": pd.Timestamp(reference).date().isoformat(),
                        })
        return make_records(rows)

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        response = requests.get(
            MPT_HISTORY_URL,
            headers={"User-Agent": "MarketBiasPlatform/1.0"},
            timeout=(10, 45),
        )
        response.raise_for_status()
        # The Atlanta Fed serves an HTML page (HTTP 200) at stale document URLs;
        # fail with a location-specific message instead of a cryptic Excel error.
        head = response.content[:512].lstrip().lower()
        if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
            raise ValueError(
                "Atlanta Fed MPT download returned an HTML page — the historical "
                "data file has likely moved. Update MPT_HISTORY_URL from "
                "https://www.atlantafed.org/research-and-data/data/market-probability-tracker"
            )
        records = self._parse_workbook(response.content, start_date, end_date)
        warnings = [] if not records.empty else ["Atlanta Fed MPT returned no observations in range"]
        return FetchResult(plugin_name=self.name, records=records, warnings=warnings)
