"""Normalized option-chain providers used by the dashboard refresh path."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Optional

import pandas as pd
import requests

from core.config import settings


class OptionProviderError(RuntimeError):
    """A provider could not return a usable, normalized option chain."""


@dataclass(frozen=True)
class ProviderChainSnapshot:
    provider: str
    spot: float
    snapshot_date: date
    chains: dict[str, tuple[pd.DataFrame, pd.DataFrame]]


def _number(value) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) else None


def _batched(values: list[str], size: int = 100):
    for index in range(0, len(values), size):
        yield values[index:index + size]


class AlpacaOptionsProvider:
    """Fetch Alpaca contract OI plus free indicative quote/IV snapshots."""

    name = "Alpaca indicative"

    def __init__(self, http_get: Callable = requests.get):
        self._get = http_get
        self._headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key_id,
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret_key,
        }

    @property
    def is_available(self) -> bool:
        return settings.has_alpaca

    def _json(self, url: str, params: Optional[dict] = None) -> dict:
        try:
            response = self._get(
                url,
                headers=self._headers,
                params=params or {},
                timeout=25,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise OptionProviderError(f"Alpaca request failed{suffix}.") from exc
        except ValueError as exc:
            raise OptionProviderError("Alpaca returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise OptionProviderError("Alpaca returned an unexpected response shape.")
        return payload

    def _spot(self, symbol: str) -> tuple[float, date]:
        url = f"{settings.alpaca_data_base_url.rstrip('/')}/v2/stocks/{symbol}/snapshot"
        payload = self._json(url, {"feed": "iex"})
        trade = payload.get("latestTrade") or payload.get("latest_trade") or {}
        daily = payload.get("dailyBar") or payload.get("daily_bar") or {}
        spot = _number(trade.get("p")) or _number(daily.get("c"))
        if not spot or spot <= 0:
            raise OptionProviderError(f"{symbol}: Alpaca returned no usable spot price.")
        timestamp = trade.get("t") or daily.get("t")
        observed = pd.Timestamp(timestamp).date() if timestamp else date.today()
        return spot, observed

    def _contracts(self, symbol: str, spot: float, observed: date) -> list[dict]:
        url = f"{settings.alpaca_trading_base_url.rstrip('/')}/v2/options/contracts"
        params = {
            "underlying_symbols": symbol,
            "status": "active",
            "expiration_date_gte": observed.isoformat(),
            "expiration_date_lte": (observed + timedelta(days=180)).isoformat(),
            "strike_price_gte": round(spot * 0.5, 2),
            "strike_price_lte": round(spot * 1.5, 2),
            "limit": 10000,
        }
        rows: list[dict] = []
        for _ in range(20):
            payload = self._json(url, params)
            page = payload.get("option_contracts") or []
            if not isinstance(page, list):
                raise OptionProviderError("Alpaca contract response is malformed.")
            rows.extend(item for item in page if isinstance(item, dict))
            token = payload.get("next_page_token") or payload.get("page_token")
            if not token:
                break
            params["page_token"] = token
        if not rows:
            raise OptionProviderError(f"{symbol}: Alpaca returned no active option contracts.")
        return rows

    def _snapshots(self, symbols: list[str]) -> dict[str, dict]:
        url = f"{settings.alpaca_data_base_url.rstrip('/')}/v1beta1/options/snapshots"
        collected: dict[str, dict] = {}
        for batch in _batched(symbols):
            payload = self._json(url, {"symbols": ",".join(batch), "feed": "indicative"})
            snapshots = payload.get("snapshots") or {}
            if isinstance(snapshots, dict):
                collected.update(
                    (symbol, value) for symbol, value in snapshots.items()
                    if isinstance(value, dict)
                )
        return collected

    def fetch(self, symbol: str, expiration_selector: Callable, count: int) -> ProviderChainSnapshot:
        if not self.is_available:
            raise OptionProviderError("Alpaca API credentials are not configured.")
        spot, market_date = self._spot(symbol)
        contracts = self._contracts(symbol, spot, market_date)

        oi_dates = [
            pd.Timestamp(item["open_interest_date"]).date()
            for item in contracts if item.get("open_interest_date")
        ]
        snapshot_date = max(oi_dates, default=market_date)
        expiration_values = expiration_selector(
            sorted({str(item.get("expiration_date")) for item in contracts if item.get("expiration_date")}),
            snapshot_date,
            count,
        )
        selected = [
            item for item in contracts
            if str(item.get("expiration_date")) in expiration_values and item.get("symbol")
        ]
        snapshots = self._snapshots([str(item["symbol"]) for item in selected])

        rows: dict[str, dict[str, list[dict]]] = {
            expiration: {"call": [], "put": []} for expiration in expiration_values
        }
        for contract in selected:
            expiration = str(contract.get("expiration_date"))
            option_type = str(contract.get("type") or "").lower()
            if expiration not in rows or option_type not in ("call", "put"):
                continue
            symbol_value = str(contract.get("symbol"))
            snapshot = snapshots.get(symbol_value, {})
            quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or {}
            trade = snapshot.get("latestTrade") or snapshot.get("latest_trade") or {}
            bar = snapshot.get("dailyBar") or snapshot.get("daily_bar") or {}
            strike = _number(contract.get("strike_price"))
            if not strike or strike <= 0:
                continue
            rows[expiration][option_type].append({
                "contractSymbol": symbol_value,
                "lastTradeDate": trade.get("t"),
                "strike": strike,
                "lastPrice": _number(trade.get("p")) or _number(contract.get("close_price")),
                "bid": _number(quote.get("bp")),
                "ask": _number(quote.get("ap")),
                "volume": _number(bar.get("v")),
                "openInterest": _number(contract.get("open_interest")),
                "impliedVolatility": _number(
                    snapshot.get("impliedVolatility") or snapshot.get("implied_volatility")
                ),
                "inTheMoney": strike < spot if option_type == "call" else strike > spot,
            })

        chains = {
            expiration: (pd.DataFrame(parts["call"]), pd.DataFrame(parts["put"]))
            for expiration, parts in rows.items()
            if parts["call"] or parts["put"]
        }
        if not chains:
            raise OptionProviderError(f"{symbol}: Alpaca returned no normalized option chains.")
        return ProviderChainSnapshot(self.name, spot, snapshot_date, chains)
