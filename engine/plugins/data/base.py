"""
Market Bias Platform — Enhanced Data Plugin Base Class

All data source plugins implement this interface.
Architecture: DATA → MEASUREMENT → USER FRAMEWORK → BIAS → AI EXPLANATION
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────

class PluginType(str, Enum):
    MACRO     = "macro"       # Fed, FRED, ECB, BOJ, PBOC, Treasury
    MARKET    = "market"      # Prices, options, ETF flows
    AI        = "ai"          # OpenAI, Gemini, Claude, Ollama
    UTILITY   = "utility"     # CSV, Excel, Sheets, Telegram, Discord, Email

class DataFrequency(str, Enum):
    TICK      = "tick"
    INTRADAY  = "intraday"
    DAILY     = "daily"
    WEEKLY    = "weekly"
    MONTHLY   = "monthly"


# ── Result Types ──────────────────────────────────────────────────────────────

@dataclass
class HealthStatus:
    """Result of a plugin health check."""
    healthy: bool
    latency_ms: Optional[float] = None
    message: str = "OK"
    checked_at: datetime = field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    def __str__(self) -> str:
        status = "HEALTHY" if self.healthy else "UNHEALTHY"
        lat = f" ({self.latency_ms:.0f}ms)" if self.latency_ms else ""
        return f"{status}{lat}: {self.message}"


@dataclass
class ValidationResult:
    """Result of plugin data validation."""
    passed: bool
    null_pct: float = 0.0
    duplicate_count: int = 0
    out_of_range_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class FetchResult:
    """Holds the result of a plugin fetch operation."""
    plugin_name: str
    records: pd.DataFrame        # columns: indicator, date, value, source, unit
    errors: list[str]    = field(default_factory=list)
    warnings: list[str]  = field(default_factory=list)
    fetch_start: Optional[datetime] = None
    fetch_end: Optional[datetime]   = None
    api_response_time_ms: Optional[float] = None

    @property
    def success(self) -> bool:
        return len(self.records) > 0

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.fetch_start and self.fetch_end:
            return (self.fetch_end - self.fetch_start).total_seconds()
        return None


# ── Abstract Base ─────────────────────────────────────────────────────────────

class DataPlugin(ABC):
    """
    Abstract base class for all market data plugins.

    Required properties:
        name, description

    Required methods:
        fetch(start_date, end_date) -> FetchResult

    Optional overrides:
        validate(), normalize(), health_check()

    Plugin lifecycle:
        enabled → health_check() → fetch() → validate() → normalize() → store
    """

    # Auto-registry for plugin discovery
    _registry: dict[str, type[DataPlugin]] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "_abstract", False):
            DataPlugin._registry[cls.__name__] = cls

    # ── Required identity properties ──────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier (used in logs and DB)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description shown in Settings page."""
        ...

    # ── Optional identity properties ──────────────────────────────────────────

    @property
    def plugin_type(self) -> PluginType:
        return PluginType.MARKET

    @property
    def supported_frequencies(self) -> list[DataFrequency]:
        """Which data frequencies this plugin provides."""
        return [DataFrequency.DAILY]

    @property
    def supported_instruments(self) -> list[str]:
        """List of instrument names/tickers this plugin covers."""
        return []

    @property
    def requires_api_key(self) -> bool:
        """True if plugin needs an authenticated API key."""
        return False

    @property
    def is_available(self) -> bool:
        """False if plugin cannot run (e.g., missing API key, disabled)."""
        return self._enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    # Rate limiting info (for Settings display)
    @property
    def rate_limit_calls_per_minute(self) -> Optional[int]:
        return None

    @property
    def rate_limit_calls_per_day(self) -> Optional[int]:
        return None

    def __init__(self):
        self._enabled: bool = True
        self._last_health: Optional[HealthStatus] = None

    # ── Core methods ─────────────────────────────────────────────────────────

    @abstractmethod
    def fetch(self, start_date: date, end_date: date) -> FetchResult:
        """
        Fetch raw data for the given date range.

        Must return FetchResult with DataFrame columns:
            indicator | date | value | source | unit
        """
        ...

    def validate(self, result: FetchResult) -> FetchResult:
        """
        Validate fetched data for quality.
        Default: checks null values and duplicate (indicator, date) pairs.
        Subclasses can override for domain-specific validation.
        """
        if result.records.empty:
            return result

        df = result.records
        null_mask  = df["value"].isna()
        null_count = null_mask.sum()
        null_pct   = 100 * null_count / len(df)

        if null_count > 0:
            msg = f"{self.name}: {null_count} null values ({null_pct:.1f}%)"
            if null_pct > 50:
                result.errors.append(msg + " — HIGH null rate, check source")
            else:
                result.warnings.append(msg)

        dups = df.duplicated(subset=["indicator", "date"])
        if dups.any():
            result.warnings.append(
                f"{self.name}: {dups.sum()} duplicate (indicator, date) pairs — keeping last"
            )
            result.records = df.loc[~dups]

        return result

    def normalize(self, result: FetchResult) -> FetchResult:
        """
        Normalize data to standard format:
        - UTC-normalized dates
        - Numeric values
        - Standard column order
        Subclasses can override for unit conversions (e.g., M→B).
        """
        if result.records.empty:
            return result

        df = result.records.copy()
        df["date"]   = pd.to_datetime(df["date"]).dt.normalize()
        df["value"]  = pd.to_numeric(df["value"], errors="coerce")
        df["source"] = df["source"].fillna(self.name)
        df["unit"]   = df.get("unit", pd.Series(dtype=str)).fillna("")
        if "frequency" not in df.columns:
            df["frequency"] = None
        # Standard column order, retaining optional point-in-time provenance.
        standard = ["indicator", "date", "value", "source", "unit", "frequency"]
        optional = [
            col for col in ("observed_at", "available_at", "vintage_source", "vintage_id")
            if col in df.columns
        ]
        result.records = df[standard + optional]
        return result

    def health_check(self) -> HealthStatus:
        """
        Check if the plugin is reachable and functional.
        Default: return healthy if plugin is available.
        Subclasses should override to make an actual lightweight API call.
        """
        if not self.is_available:
            return HealthStatus(
                healthy=False,
                message=f"Plugin '{self.name}' is disabled or missing API key"
            )
        self._last_health = HealthStatus(healthy=True, message="Available (no active health check)")
        return self._last_health

    def run(self, start_date: date, end_date: date) -> FetchResult:
        """
        Full pipeline: validate availability → fetch → validate → normalize.
        Records timing metadata on the result.
        """
        if not self.is_available:
            logger.warning("[%s] Plugin not available, skipping", self.name)
            result = FetchResult(plugin_name=self.name, records=pd.DataFrame())
            result.errors.append(f"{self.name}: not available (check API key / enabled flag)")
            return result

        logger.info("[%s] Fetching %s → %s", self.name, start_date, end_date)
        t0 = datetime.now(UTC).replace(tzinfo=None)
        try:
            result = self.fetch(start_date, end_date)
            result.fetch_start = t0
            result.fetch_end   = datetime.now(UTC).replace(tzinfo=None)
        except Exception as exc:
            logger.exception("[%s] Fetch failed: %s", self.name, exc)
            result = FetchResult(plugin_name=self.name, records=pd.DataFrame(),
                                  fetch_start=t0,
                                  fetch_end=datetime.now(UTC).replace(tzinfo=None))
            result.errors.append(f"{self.name} fetch exception: {exc}")
            return result

        result = self.validate(result)
        result = self.normalize(result)

        logger.info(
            "[%s] Done — %d records, %d errors, %d warnings (%.1fs)",
            self.name, result.record_count,
            len(result.errors), len(result.warnings),
            result.duration_seconds or 0,
        )
        return result

    @property
    def last_health(self) -> Optional[HealthStatus]:
        return self._last_health

    def __repr__(self) -> str:
        avail = "✓" if self.is_available else "✗"
        return f"<{self.__class__.__name__} name={self.name!r} {avail}>"


# ── Helper ────────────────────────────────────────────────────────────────────

def make_records(rows: list[dict]) -> pd.DataFrame:
    """Helper: create a standard records DataFrame from a list of dicts."""
    standard = ["indicator", "date", "value", "source", "unit", "frequency"]
    if not rows:
        return pd.DataFrame(columns=standard)
    df = pd.DataFrame(rows)
    for col in standard:
        if col not in df.columns:
            df[col] = None
    # Preserve explicitly supplied PIT provenance while keeping the legacy columns first.
    optional = [
        col for col in ("observed_at", "available_at", "vintage_source", "vintage_id")
        if col in df.columns
    ]
    return df[standard + optional]
