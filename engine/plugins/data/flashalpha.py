"""FlashAlpha options exposure levels.

FlashAlpha is the preferred provider for aggregate GEX, gamma flip, and
call/put walls. Yahoo remains the raw-chain and model-estimate fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Optional

import pandas as pd
import requests

from core.config import settings
from plugins.data.base import (
    DataFrequency,
    DataPlugin,
    FetchResult,
    HealthStatus,
    make_records,
)


FLASHALPHA_BASE_URL = "https://lab.flashalpha.com"
SUPPORTED_SYMBOLS = {"SPY": "spy", "QQQ": "qqq", "GLD": "gld"}


class FlashAlphaAPIError(RuntimeError):
    """A sanitized FlashAlpha error safe to show in the dashboard."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        reason: Optional[str] = None,
        current_plan: Optional[str] = None,
        required_plan: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.current_plan = current_plan
        self.required_plan = required_plan

    @property
    def user_message(self) -> str:
        if self.reason == "tier_restricted":
            plans = ""
            if self.current_plan or self.required_plan:
                plans = (
                    f" (current: {self.current_plan or 'unknown'}; "
                    f"required: {self.required_plan or 'higher tier'})"
                )
            return f"FlashAlpha plan does not allow this ETF endpoint{plans}."
        if self.status_code in {401, 403}:
            return "FlashAlpha rejected the configured API key or its permissions."
        return str(self)


def _number(value: Any) -> Optional[float]:
    """Extract a finite numeric value from scalar or {strike/value: ...}."""
    if isinstance(value, dict):
        for key in ("strike", "value", "level"):
            if key in value:
                value = value[key]
                break
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if pd.notna(result) else None


def _observation_date(as_of: Any) -> date:
    if not as_of:
        return datetime.now(UTC).date()
    try:
        timestamp = pd.Timestamp(as_of)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("America/New_York")
        return timestamp.date()
    except (TypeError, ValueError):
        return datetime.now(UTC).date()


@dataclass(frozen=True)
class FlashAlphaLevels:
    symbol: str
    observation_date: date
    fetched_at: datetime
    as_of: Optional[str]
    spot_price: Optional[float]
    net_gex: Optional[float]
    gamma_flip: Optional[float]
    call_wall: Optional[float]
    put_wall: Optional[float]

    @property
    def source(self) -> str:
        return f"flashalpha:exposure_levels:{self.symbol}"

    def records(self) -> list[dict[str, Any]]:
        prefix = SUPPORTED_SYMBOLS[self.symbol]
        values = (
            (f"{prefix}_gex", self.net_gex, "USD per 1% move"),
            (f"{prefix}_gamma_flip", self.gamma_flip, "price"),
            (f"{prefix}_call_wall", self.call_wall, "price"),
            (f"{prefix}_put_wall", self.put_wall, "price"),
        )
        return [
            {
                "indicator": indicator,
                "date": self.observation_date,
                "value": value,
                "source": self.source,
                "unit": unit,
            }
            for indicator, value, unit in values
            if value is not None
        ]


def parse_levels_response(symbol: str, payload: dict[str, Any]) -> FlashAlphaLevels:
    """Parse both documented FlashAlpha levels response variants."""
    levels = payload.get("levels")
    if not isinstance(levels, dict):
        levels = payload

    net_gex = _number(payload.get("net_gex"))
    if net_gex is None:
        net_gex = _number(levels.get("net_gex"))

    result = FlashAlphaLevels(
        symbol=symbol.upper(),
        observation_date=_observation_date(payload.get("as_of")),
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
        as_of=str(payload["as_of"]) if payload.get("as_of") else None,
        spot_price=_number(payload.get("underlying_price")),
        net_gex=net_gex,
        gamma_flip=_number(levels.get("gamma_flip")),
        call_wall=_number(levels.get("call_wall")),
        put_wall=_number(levels.get("put_wall")),
    )
    if not any(
        value is not None
        for value in (result.net_gex, result.gamma_flip, result.call_wall, result.put_wall)
    ):
        raise FlashAlphaAPIError("FlashAlpha returned no usable exposure levels.")
    return result


class FlashAlphaPlugin(DataPlugin):
    """Fetch aggregate exposure analytics, one request per supported ETF."""

    @property
    def name(self) -> str:
        return "flashalpha_options"

    @property
    def description(self) -> str:
        return "FlashAlpha aggregate GEX, gamma flip, and option walls"

    @property
    def supported_frequencies(self) -> list[DataFrequency]:
        return [DataFrequency.DAILY]

    @property
    def supported_instruments(self) -> list[str]:
        return list(SUPPORTED_SYMBOLS)

    @property
    def requires_api_key(self) -> bool:
        return True

    @property
    def rate_limit_calls_per_day(self) -> int:
        return 5

    @property
    def is_available(self) -> bool:
        return self.enabled and bool(settings.flashalpha_api_key.strip())

    def health_check(self) -> HealthStatus:
        # Avoid consuming the small daily quota merely to render Settings.
        message = "Configured; verified on the next options refresh"
        self._last_health = HealthStatus(healthy=self.is_available, message=message)
        return self._last_health

    def fetch_symbol(self, symbol: str) -> FlashAlphaLevels:
        symbol = symbol.upper()
        if symbol not in SUPPORTED_SYMBOLS:
            raise ValueError(f"Unsupported FlashAlpha symbol: {symbol}")
        if not self.is_available:
            raise FlashAlphaAPIError("FlashAlpha API key is not configured.")

        url = f"{FLASHALPHA_BASE_URL}/v1/exposure/levels/{symbol}"
        try:
            response = requests.get(
                url,
                headers={
                    "X-Api-Key": settings.flashalpha_api_key,
                    "Accept": "application/json",
                    "User-Agent": "market-bias-platform/1.0",
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            raise FlashAlphaAPIError(f"FlashAlpha connection failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code != 200:
            payload = payload if isinstance(payload, dict) else {}
            reason = payload.get("error") or payload.get("status")
            raise FlashAlphaAPIError(
                f"FlashAlpha request failed with HTTP {response.status_code}.",
                status_code=response.status_code,
                reason=str(reason) if reason else None,
                current_plan=payload.get("current_plan"),
                required_plan=payload.get("required_plan"),
            )
        if not isinstance(payload, dict):
            raise FlashAlphaAPIError("FlashAlpha returned an invalid JSON response.")
        return parse_levels_response(symbol, payload)

    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        warnings: list[str] = []

        for symbol in SUPPORTED_SYMBOLS:
            try:
                levels = self.fetch_symbol(symbol)
                records.extend(levels.records())
            except FlashAlphaAPIError as exc:
                errors.append(f"{symbol}: {exc.user_message}")
                # The same ETF tier restriction applies to SPY, QQQ, and GLD;
                # stop after one request so the remaining quota is preserved.
                if exc.reason == "tier_restricted":
                    warnings.append("Yahoo options model remains the active fallback.")
                    break
                # A 429 means the daily quota is already exhausted — retrying the
                # other symbols cannot succeed and may deepen the rate limit.
                if exc.status_code == 429:
                    warnings.append(
                        "FlashAlpha daily quota exhausted; Yahoo options model "
                        "remains the active fallback for the remaining symbols."
                    )
                    break

        return FetchResult(
            plugin_name=self.name,
            records=make_records(records),
            errors=errors,
            warnings=warnings,
        )
