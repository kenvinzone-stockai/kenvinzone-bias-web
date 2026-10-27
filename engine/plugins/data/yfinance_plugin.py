"""
Market Bias Platform — yfinance Data Plugin
Fetches price data, volatility indices, USD pairs, ETF data, and options chains
using the free yfinance library (Yahoo Finance).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from plugins.data.base import DataPlugin, FetchResult, make_records

logger = logging.getLogger(__name__)

# ── Ticker Map ────────────────────────────────────────────────────────────────
# indicator_name -> (ticker, unit, description)
YFINANCE_TICKERS: dict[str, tuple[str, str, str]] = {
    # ── Equity Indices ─────────────────────────────────────────────────────
    "spx_close":    ("^GSPC",     "index",    "S&P 500 Index"),
    "nasdaq_close": ("^IXIC",     "index",    "Nasdaq Composite"),
    "ndx_close":    ("^NDX",      "index",    "Nasdaq 100"),
    "djia_close":   ("^DJI",      "index",    "Dow Jones Industrial Average"),
    "rut_close":    ("^RUT",      "index",    "Russell 2000"),

    # ── Volatility ─────────────────────────────────────────────────────────
    "vix":          ("^VIX",      "index",    "CBOE VIX"),
    "vxn":          ("^VXN",      "index",    "CBOE VXN (Nasdaq Volatility)"),
    "vix3m":        ("^VIX3M",    "index",    "CBOE 3-Month VIX"),
    "move":         ("^MOVE",     "index",    "MOVE Treasury Volatility Index"),

    # ── USD / FX ───────────────────────────────────────────────────────────
    "dxy":          ("DX-Y.NYB",  "index",    "US Dollar Index (DXY)"),
    "usdjpy":       ("JPY=X",     "USD/JPY",  "USD/JPY"),
    "usdcnh":       ("USDCNH=X",  "USD/CNH",  "USD/CNH"),
    "eurusd":       ("EURUSD=X",  "EUR/USD",  "EUR/USD"),
    "gbpusd":       ("GBPUSD=X",  "GBP/USD",  "GBP/USD"),

    # ── Commodities ────────────────────────────────────────────────────────
    "gold_futures": ("GC=F",      "USD/oz",   "Gold Futures (front month)"),
    "silver":       ("SI=F",      "USD/oz",   "Silver Futures"),
    "crude_oil":    ("CL=F",      "USD/bbl",  "WTI Crude Oil Futures"),
    "copper":       ("HG=F",      "USD/lb",   "Copper Futures"),

    # ── ETFs (for flow/AUM proxy) ─────────────────────────────────────────
    "spy_close":    ("SPY",       "USD",      "SPDR S&P 500 ETF"),
    "qqq_close":    ("QQQ",       "USD",      "Invesco QQQ (Nasdaq 100 ETF)"),
    "gld_close":    ("GLD",       "USD",      "SPDR Gold Shares ETF"),
    "iau_close":    ("IAU",       "USD",      "iShares Gold Trust ETF"),
    "tlt_close":    ("TLT",       "USD",      "iShares 20+ Year Treasury Bond ETF"),
    "hyg_close":    ("HYG",       "USD",      "iShares HY Corporate Bond ETF"),
    "lqd_close":    ("LQD",       "USD",      "iShares IG Corporate Bond ETF"),

    # ── Rates (yfinance proxies) ───────────────────────────────────────────
    "us_10y_yf":    ("^TNX",      "%",        "10-Year Treasury Yield (yfinance)"),
    "us_3m_yf":     ("^IRX",      "%",        "13-Week T-Bill Yield (Yahoo Finance)"),
    "us_30y_yf":    ("^TYX",      "%",        "30-Year Treasury Yield (yfinance)"),
}


class YFinancePlugin(DataPlugin):
    """Fetches price-based data from Yahoo Finance via yfinance."""

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def description(self) -> str:
        return "Yahoo Finance — Prices, Volatility, FX, ETFs, Commodities"

    @property
    def is_available(self) -> bool:
        return True  # No API key required

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        rows = []
        errors = []
        warnings_list = []

        # Batch download all tickers at once for efficiency
        tickers = [v[0] for v in YFINANCE_TICKERS.values()]
        indicator_by_ticker = {v[0]: k for k, v in YFINANCE_TICKERS.items()}

        try:
            # Batch download all tickers at once for efficiency, disabling threads to avoid random drops
            data = yf.download(
                tickers=tickers,
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                auto_adjust=True,
                progress=False,
                threads=False, # Disable threads to prevent Yahoo Finance from randomly blocking tickers
            )
        except Exception as exc:
            return FetchResult(
                plugin_name=self.name,
                records=pd.DataFrame(columns=["indicator", "date", "value", "source", "unit"]),
                errors=[f"yfinance batch download failed: {exc}"],
            )

        # Parse multi-index DataFrame (Close prices)
        close_data = data.get("Close", data if data.columns.nlevels == 1 else pd.DataFrame())

        for ticker, indicator in indicator_by_ticker.items():
            unit = YFINANCE_TICKERS[indicator][1]
            try:
                if ticker in close_data.columns:
                    series = close_data[ticker].dropna()
                elif len(close_data.columns) == 1:
                    # Single ticker download
                    series = close_data.iloc[:, 0].dropna()
                else:
                    warnings_list.append(f"yfinance: {ticker} not in response")
                    continue

                for dt, val in series.items():
                    if pd.notna(val):
                        rows.append({
                            "indicator": indicator,
                            "date": dt,
                            "value": float(val),
                            "source": f"yfinance:{ticker}",
                            "unit": unit,
                        })
            except Exception as exc:
                errors.append(f"yfinance parse {ticker}: {exc}")

        # ── ETF Share counts (for flow proxy) ─────────────────────────────
        etf_tickers = {"spy_shares": "SPY", "qqq_shares": "QQQ",
                       "gld_shares": "GLD", "iau_shares": "IAU"}
        for indicator, ticker in etf_tickers.items():
            try:
                info = yf.Ticker(ticker).fast_info
                shares = getattr(info, "shares", None)
                if shares:
                    rows.append({
                        "indicator": indicator,
                        "date": end_date,
                        "value": float(shares),
                        "source": f"yfinance:{ticker}",
                        "unit": "shares",
                    })
            except Exception as exc:
                warnings_list.append(f"yfinance shares {ticker}: {exc}")

        df = make_records(rows) if rows else pd.DataFrame(
            columns=["indicator", "date", "value", "source", "unit"]
        )
        return FetchResult(
            plugin_name=self.name,
            records=df,
            errors=errors,
            warnings=warnings_list,
        )


class YFinanceOptionsPlugin(DataPlugin):
    """
    Fetches options chain data for SPY/QQQ/GLD from Yahoo Finance.
    Used to compute approximate GEX, Put/Call OI, and key option walls.
    """

    _abstract = False

    # Tickers to fetch options for
    OPTION_TICKERS = {
        "spy": ("SPY", "S&P 500 ETF"),
        "qqq": ("QQQ", "Nasdaq 100 ETF"),
        "gld": ("GLD", "Gold ETF"),
    }

    @property
    def is_available(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "yfinance_options"

    @property
    def description(self) -> str:
        return "Yahoo options observations — OI plus model-estimated GEX/levels"

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        from metrics.options import compute_gex_from_chain, compute_oi_walls

        rows = []
        errors = []
        warnings_list = []

        # Dynamic risk-free rate from DB (SOFR or Fed Funds), fallback to 4.5%
        rfr = 0.045
        try:
            from core.database import get_session
            from core.models import RawDataPoint
            from sqlalchemy import select
            with get_session() as session:
                for indicator in ['sofr', 'fed_funds_rate']:
                    rec = session.execute(
                        select(RawDataPoint)
                        .where(RawDataPoint.indicator == indicator)
                        .order_by(RawDataPoint.date.desc())
                        .limit(1)
                    ).scalar_one_or_none()
                    if rec and rec.value is not None:
                        rfr = rec.value / 100.0  # Convert from % to decimal
                        break
        except Exception:
            pass  # Use default 4.5%

        for indicator_prefix, (ticker, _desc) in self.OPTION_TICKERS.items():
            try:
                t = yf.Ticker(ticker)
                price_history = t.history(period="5d", auto_adjust=False)
                if price_history.empty or price_history["Close"].dropna().empty:
                    warnings_list.append(f"Options {ticker}: no recent market price")
                    continue
                spot = float(price_history["Close"].dropna().iloc[-1])
                observation_date = pd.Timestamp(price_history.index[-1]).date()
                expirations = t.options[:2]  # Next 2 expiration dates (minimize yfinance rate limits)

                total_call_oi = 0
                total_put_oi = 0
                all_calls = []
                all_puts = []

                for exp_date in expirations:
                    try:
                        chain = t.option_chain(exp_date)
                        calls = chain.calls.copy()
                        puts = chain.puts.copy()

                        # Add DTE
                        days_to_exp = (pd.Timestamp(exp_date).date() - observation_date).days
                        if days_to_exp < 0:
                            continue
                        calls["daysToExpiration"] = days_to_exp
                        puts["daysToExpiration"] = days_to_exp

                        total_call_oi += calls["openInterest"].sum()
                        total_put_oi += puts["openInterest"].sum()
                        all_calls.append(calls)
                        all_puts.append(puts)
                    except Exception as exc:
                        warnings_list.append(f"Options {ticker} {exp_date}: {exc}")

                # Put/Call OI ratio
                if total_call_oi > 0:
                    pc_ratio = total_put_oi / total_call_oi
                    rows.append({
                        "indicator": f"{indicator_prefix}_pc_ratio_oi",
                        "date": observation_date,
                        "value": pc_ratio,
                        "source": f"yfinance:{ticker}_options",
                        "unit": "ratio",
                    })

                rows.append({"indicator": f"{indicator_prefix}_call_oi_total", "date": observation_date,
                             "value": float(total_call_oi), "source": f"yfinance:{ticker}_options", "unit": "contracts"})
                rows.append({"indicator": f"{indicator_prefix}_put_oi_total", "date": observation_date,
                             "value": float(total_put_oi), "source": f"yfinance:{ticker}_options", "unit": "contracts"})

                # Compute GEX
                if all_calls and spot:
                    calls_df = pd.concat(all_calls, ignore_index=True)
                    puts_df = pd.concat(all_puts, ignore_index=True)
                    gex, gamma_flip = compute_gex_from_chain(spot, calls_df, puts_df, risk_free_rate=rfr)
                    rows.append({"indicator": f"{indicator_prefix}_gex", "date": observation_date,
                                 "value": gex, "source": f"yfinance:{ticker}_options", "unit": "USD"})
                    if gamma_flip:
                        rows.append({"indicator": f"{indicator_prefix}_gamma_flip", "date": observation_date,
                                     "value": gamma_flip, "source": f"yfinance:{ticker}_options", "unit": "price"})
                                     
                    # Compute OI Walls
                    walls = compute_oi_walls(calls_df, puts_df, top_n=1)
                    if walls["call_walls"]:
                        rows.append({"indicator": f"{indicator_prefix}_call_wall", "date": observation_date,
                                     "value": walls["call_walls"][0][0], "source": f"yfinance:{ticker}_options", "unit": "strike"})
                    if walls["put_walls"]:
                        rows.append({"indicator": f"{indicator_prefix}_put_wall", "date": observation_date,
                                     "value": walls["put_walls"][0][0], "source": f"yfinance:{ticker}_options", "unit": "strike"})


            except Exception as exc:
                errors.append(f"Options {ticker}: {exc}")
                logger.warning("Options fetch failed for %s: %s", ticker, exc)

        df = make_records(rows) if rows else pd.DataFrame(
            columns=["indicator", "date", "value", "source", "unit"]
        )
        return FetchResult(plugin_name=self.name, records=df, errors=errors, warnings=warnings_list)
