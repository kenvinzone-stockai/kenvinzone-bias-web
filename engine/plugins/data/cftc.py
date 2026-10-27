"""
Market Bias Platform — CFTC COT Data Plugin
Fetches Commitment of Traders (COT) data.

PRIMARY: CFTC public CSV downloads (stable, no auth)
FALLBACK: CFTC Socrata API (often gives 403)
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import UTC, date, datetime, time as datetime_time
from typing import Optional
import time
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from plugins.data.base import DataPlugin, FetchResult, make_records, PluginType, DataFrequency, HealthStatus

logger = logging.getLogger(__name__)

_CFTC_PROCESSING_DAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def cot_available_date(report_date: str | date | datetime | pd.Timestamp) -> pd.Timestamp:
    """Earliest modeled public date after CFTC's three processing days."""
    return pd.Timestamp(report_date) + 3 * _CFTC_PROCESSING_DAY

# Source: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm

# ── Contract specs ────────────────────────────────────────────────────────────
CONTRACTS: dict[str, dict] = {
    "cot_spx": {
        "code": "13874A",
        "name": "E-Mini S&P 500",
        "report": "tff",
        "csv_name_substr": "E-MINI S&P 500 - CHICAGO",
    },
    "cot_nasdaq": {
        "code": "20974+",
        "name": "E-Mini Nasdaq 100",
        "report": "tff",
        "csv_name_substr": "NASDAQ-100 Consolidated",
    },
    "cot_gold": {
        "code": "088691",
        "name": "Gold COMEX",
        "report": "legacy",
        "csv_name_substr": "GOLD - COMMODITY EXCHANGE INC.",
    },
    "cot_10y": {
        "code": "043602",
        "name": "10-Year Treasury Notes",
        "report": "tff",
        "csv_name_substr": "UST 10Y NOTE",
    },
}

class CFTCPlugin(DataPlugin):
    """Fetches weekly COT positioning data from CFTC."""

    @property
    def name(self) -> str:
        return "cftc"

    @property
    def description(self) -> str:
        return "CFTC COT — Speculator Positioning"

    @property
    def plugin_type(self) -> PluginType:
        return PluginType.MACRO
        
    @property
    def supported_frequencies(self) -> list[DataFrequency]:
        return [DataFrequency.WEEKLY]

    def health_check(self) -> HealthStatus:
        if not self.is_available:
            return HealthStatus(healthy=False, message="Disabled")
        try:
            # Just do a HEAD request to the CFTC website to ensure we can reach it
            t0 = time.time()
            resp = requests.head("https://www.cftc.gov", timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            lat = (time.time() - t0) * 1000
            if resp.status_code < 400:
                return HealthStatus(healthy=True, latency_ms=lat, message="OK")
            return HealthStatus(healthy=False, message=f"HTTP {resp.status_code}")
        except Exception as exc:
            return HealthStatus(healthy=False, message=str(exc))

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        rows = []
        errors = []
        warnings_list = []

        # Download ZIP files (tff and legacy) for the required years
        cached_dfs = {"tff": pd.DataFrame(), "legacy": pd.DataFrame()}
        years = range(start_date.year, end_date.year + 1)
        for year in years:
            for report_type in ["tff", "legacy"]:
                try:
                    df_year = self._download_csv_zip(report_type, year)
                    if not df_year.empty:
                        if cached_dfs[report_type].empty:
                            cached_dfs[report_type] = df_year
                        else:
                            cached_dfs[report_type] = pd.concat([cached_dfs[report_type], df_year], ignore_index=True)
                except Exception as exc:
                    errors.append(f"Failed to download {report_type} CSV for {year}: {exc}")

        for indicator_base, cfg in CONTRACTS.items():
            report_type = cfg["report"]
            if report_type not in cached_dfs or cached_dfs[report_type].empty:
                warnings_list.append(f"CFTC {cfg['name']}: CSV data unavailable")
                continue
                
            try:
                data = self._filter_csv_data(cached_dfs[report_type], cfg, start_date, end_date)
                if data.empty:
                    warnings_list.append(f"CFTC {cfg['name']}: No data in date range")
                    continue
                rows.extend(self._parse_rows(indicator_base, cfg, data))
            except Exception as exc:
                logger.warning("CFTC processing failed for %s: %s", cfg["name"], exc)
                errors.append(f"CFTC {cfg['name']} error: {exc}")

        df = make_records(rows)
        return FetchResult(plugin_name=self.name, records=df, errors=errors, warnings=warnings_list)

    # ── CSV Downloading and Filtering ─────────────────────────────────────────
    def _download_csv_zip(self, report_type: str, year: int) -> pd.DataFrame:
        if report_type == "tff":
            url = f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
        else:
            url = f"https://www.cftc.gov/files/dea/history/deacot{year}.zip"
        
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_files = [f for f in zf.namelist() if f.lower().endswith(".csv") or f.lower().endswith(".txt")]
            if not csv_files:
                raise ValueError("No CSV/TXT in CFTC zip")
            with zf.open(csv_files[0]) as f:
                df = pd.read_csv(f, low_memory=False)
        return df
        
    def _filter_csv_data(self, df_full: pd.DataFrame, cfg: dict, start_date: date, end_date: date) -> pd.DataFrame:
        df = df_full.copy()
        
        # Contract names can overlap (for example GOLD also matches MICRO GOLD).
        # Prefer the official exact market code and only fall back to names when
        # an older export does not expose a code column.
        name_col = "Market_and_Exchange_Names" if "Market_and_Exchange_Names" in df.columns else df.columns[0]
        code_col = next(
            (
                column for column in (
                    "CFTC_Contract_Market_Code", "CFTC Contract Market Code"
                ) if column in df.columns
            ),
            None,
        )
        if code_col:
            df = df[df[code_col].astype(str).str.strip() == cfg["code"]]
        else:
            df = df[df[name_col].str.upper().str.contains(
                cfg["csv_name_substr"].upper(), na=False
            )]

        if df.empty:
            return df

        # Parse date
        # Both formats usually have a YYYY-MM-DD column, but with different names (underscores vs spaces)
        if "Report_Date_as_YYYY-MM-DD" in df.columns:
            date_col = "Report_Date_as_YYYY-MM-DD"
        elif "As of Date in Form YYYY-MM-DD" in df.columns:
            date_col = "As of Date in Form YYYY-MM-DD"
        else:
            # Fallback to the first column containing 'yyyy-mm-dd'
            date_cols = [c for c in df.columns if "yyyy-mm-dd" in c.lower()]
            if not date_cols:
                return pd.DataFrame()
            date_col = date_cols[0]

        df["_date"] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=["_date"])
        df = df[(df["_date"] >= pd.Timestamp(start_date)) & (df["_date"] <= pd.Timestamp(end_date))]

        # Map columns
        col_map = {
            # TFF Format
            "Lev_Money_Positions_Long_All": "lev_money_positions_long_all",
            "Lev_Money_Positions_Short_All": "lev_money_positions_short_all",
            "Asset_Mgr_Positions_Long_All": "asset_mgr_positions_long_all",
            "Asset_Mgr_Positions_Short_All": "asset_mgr_positions_short_all",
            "Open_Interest_All": "open_interest_all",
            # Legacy Format
            "Open Interest (All)": "open_interest_all",
            "Noncommercial Positions-Long (All)": "noncomm_positions_long_all",
            "Noncommercial Positions-Short (All)": "noncomm_positions_short_all",
            "Commercial Positions-Long (All)": "comm_positions_long_all",
            "Commercial Positions-Short (All)": "comm_positions_short_all",
            
            "_date": "report_date",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["report_date"] = df["report_date"].dt.strftime("%Y-%m-%d")
        return df

    # ── Unified row parser ────────────────────────────────────────────────────
    def _parse_rows(self, indicator_base: str, cfg: dict, data: pd.DataFrame) -> list[dict]:
        rows = []
        for _, row_data in data.iterrows():
            report_date = row_data.get("report_date")
            if report_date is None:
                continue

            # COT positions are measured on Tuesday and become public after
            # three US federal business days. This maps ordinary weeks to
            # Friday and holiday-delayed weeks to the following business day.
            available_date = cot_available_date(report_date).strftime("%Y-%m-%d")
            src = f"CFTC:{cfg['code']}:available_usfedcal"
            # Preserve both economic observation time (Tuesday) and the modeled
            # publication timestamp. The historical schedule is not complete enough to
            # call this verified; the PIT mirror therefore remains RECORDED_LIVE unless
            # an independently verified release timestamp is supplied later.
            observed_at = pd.Timestamp(report_date).to_pydatetime()
            release_local = datetime.combine(
                pd.Timestamp(available_date).date(), datetime_time(15, 30),
                tzinfo=ZoneInfo("America/New_York"),
            )
            declared_available_at = release_local.astimezone(UTC).replace(tzinfo=None)

            def record(indicator: str, value: float) -> dict:
                return {
                    "indicator": indicator,
                    "date": available_date,
                    "observed_at": observed_at,
                    "available_at": declared_available_at,
                    "vintage_source": "declared_rule",
                    "value": value,
                    "source": src,
                    "unit": "contracts",
                }

            if cfg["report"] == "tff":
                net_lev = self._sf(row_data, "lev_money_positions_long_all") - \
                          self._sf(row_data, "lev_money_positions_short_all")
                net_am  = self._sf(row_data, "asset_mgr_positions_long_all") - \
                          self._sf(row_data, "asset_mgr_positions_short_all")
                total_oi = self._sf(row_data, "open_interest_all")
                rows.extend([
                    record(f"{indicator_base}_net_leveraged", net_lev),
                    record(f"{indicator_base}_net_asset_mgr", net_am),
                    record(f"{indicator_base}_open_interest", total_oi),
                ])
            else:
                net_nc   = self._sf(row_data, "noncomm_positions_long_all") - \
                           self._sf(row_data, "noncomm_positions_short_all")
                total_oi = self._sf(row_data, "open_interest_all")
                net_comm = self._sf(row_data, "comm_positions_long_all") - \
                           self._sf(row_data, "comm_positions_short_all")
                rows.extend([
                    record(f"{indicator_base}_net_noncommercial", net_nc),
                    record(f"{indicator_base}_open_interest", total_oi),
                    record(f"{indicator_base}_net_commercial", net_comm),
                ])
        return rows

    @staticmethod
    def _sf(row, col: str) -> float:
        try:
            return float(row[col])
        except (KeyError, TypeError, ValueError):
            return 0.0
