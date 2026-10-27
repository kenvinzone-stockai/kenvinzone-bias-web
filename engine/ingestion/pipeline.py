"""
Market Bias Platform — Ingestion Pipeline
Orchestrates: Fetch → Validate → Normalize → Store → Compute Metrics → Run Bias Engine

Triggered on:
  1. App startup (if data older than DATA_FRESHNESS_HOURS)
  2. Manual refresh via dashboard button
"""
from __future__ import annotations

import logging
import queue
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Collection, Optional

import pandas as pd
from sqlalchemy import desc, select, func

from core.config import settings
from core.database import get_session
from core.models import RawDataPoint, ProcessedMetric, IngestionLog
from ingestion.raw_storage import store_raw_record
from plugins.data.fred import FREDPlugin
from plugins.data.yfinance_plugin import YFinancePlugin, YFinanceOptionsPlugin
from plugins.data.flashalpha import FlashAlphaPlugin
from plugins.data.cftc import CFTCPlugin
from plugins.data.cboe import CBOEPlugin
from plugins.data.base import FetchResult

from plugins.data.breadth import BreadthPlugin
from plugins.data.global_liquidity import GlobalLiquidityPlugin
from plugins.data.gld_official_flows import GLDOfficialFlowsPlugin
from plugins.data.fed_rate_expectations import FedRateExpectationsPlugin
try:
    from plugins.data.etf_flows import ETFFlowsPlugin
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Network-library timeouts do not reliably bound DNS resolution on every
# platform.  Keep a hard wall-clock deadline around sources that have shown
# this behaviour so one unavailable provider cannot hold the whole refresh.
PLUGIN_DEADLINES_SECONDS = {
    "cboe": 45,
    "gld_official_flows": 60,
    "fed_rate_expectations": 75,
}

# Freshness is source-specific: daily market data should not be masked by a
# recent monthly/weekly ingestion, while slow official series get wider TTLs.
PLUGIN_FRESHNESS_HOURS = {
    "yfinance": 36,
    "yfinance_options": 36,
    "flashalpha_options": 36,
    "breadth": 36,
    "etf_flows": 36,
    "gld_official_flows": 36,
    "fed_rate_expectations": 36,
    "cboe": 36,
    "fred": 72,
    "cftc": 24 * 8,
    "global_liquidity": 24 * 35,
    "flashalpha_options": 36,
}

# A normal manual refresh always checks these fast, market-sensitive sources.
# Slow sources still refresh as soon as their own TTL expires.
MANUAL_MARKET_PRIORITY_PLUGINS = frozenset({"yfinance", "etf_flows"})

OPTION_SNAPSHOT_INDICATORS = {
    f"{prefix}_{suffix}"
    for prefix in ("spy", "qqq", "gld")
    for suffix in (
        "pc_ratio_oi", "call_oi_total", "put_oi_total", "gex",
        "gamma_flip", "call_wall", "put_wall",
    )
}


def _success_is_stale(
    success_at: Optional[datetime], ttl_hours: int, now: datetime
) -> tuple[bool, Optional[float]]:
    if success_at is None:
        return True, None
    age_hours = (now - success_at).total_seconds() / 3600
    return age_hours > ttl_hours, age_hours


def _coverage_requires_backfill(
    coverage: dict[str, tuple[Optional[datetime], Optional[datetime], int]],
    indicators: list[str],
    full_start: date,
) -> bool:
    if any(indicator not in coverage for indicator in indicators):
        return True
    tolerance = full_start + timedelta(days=30)
    return any(
        min_date is None or min_date.date() > tolerance
        for min_date, _max_date, _count in coverage.values()
    )


def _normalize_market_snapshot_index(
    indicator: str, series: pd.Series
) -> pd.Series:
    """Map legacy weekend option snapshots to the preceding market Friday."""
    if indicator not in OPTION_SNAPSHOT_INDICATORS or series.empty:
        return series
    adjusted_dates = []
    for timestamp in pd.DatetimeIndex(series.index):
        days_back = 1 if timestamp.weekday() == 5 else 2 if timestamp.weekday() == 6 else 0
        adjusted_dates.append(timestamp - pd.Timedelta(days=days_back))
    normalized = series.copy()
    normalized.index = pd.DatetimeIndex(adjusted_dates)
    return normalized.groupby(level=0).last().sort_index()

# All data plugins in priority order
ALL_PLUGINS = [
    YFinancePlugin,
    CBOEPlugin,
    CFTCPlugin,
    FREDPlugin,
    BreadthPlugin,
    GlobalLiquidityPlugin,
    GLDOfficialFlowsPlugin,
    FedRateExpectationsPlugin,
]

if 'ETFFlowsPlugin' in locals():
    ALL_PLUGINS.append(ETFFlowsPlugin)


def get_last_ingest_time() -> Optional[datetime]:
    """Return the most recent completed ingestion timestamp, or None."""
    with get_session() as session:
        result = session.execute(
            select(func.max(IngestionLog.completed_at))
            .where(IngestionLog.status == "success")
        ).scalar()
        return result


def get_plugin_freshness(now: Optional[datetime] = None) -> dict[str, dict]:
    """Return latest attempt/success and source-specific stale state."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    with get_session() as session:
        logs = session.execute(
            select(
                IngestionLog.plugin,
                IngestionLog.status,
                IngestionLog.completed_at,
                IngestionLog.id,
            ).order_by(desc(IngestionLog.id))
        ).all()

    latest_attempt: dict[str, tuple[str, Optional[datetime]]] = {}
    latest_success: dict[str, datetime] = {}
    for plugin, status, completed_at, _log_id in logs:
        latest_attempt.setdefault(plugin, (status, completed_at))
        if status in {"success", "partial"} and completed_at is not None:
            latest_success.setdefault(plugin, completed_at)

    report: dict[str, dict] = {}
    for plugin, ttl_hours in PLUGIN_FRESHNESS_HOURS.items():
        success_at = latest_success.get(plugin)
        stale, age_hours = _success_is_stale(success_at, ttl_hours, now)
        status, attempted_at = latest_attempt.get(plugin, ("missing", None))
        report[plugin] = {
            "status": status,
            "last_attempt": attempted_at,
            "last_success": success_at,
            "age_hours": age_hours,
            "ttl_hours": ttl_hours,
            "stale": stale,
        }
    return report


def is_data_stale() -> bool:
    """Return True when any required configured source is stale or missing."""
    required = {
        "yfinance", "yfinance_options", "breadth", "etf_flows", "cftc",
        "gld_official_flows", "fed_rate_expectations",
    }
    if settings.has_fred:
        required.update({"fred", "global_liquidity"})
    report = get_plugin_freshness()
    return any(report[name]["stale"] for name in required)


def _plugin_should_refresh(
    plugin_name: str,
    freshness: dict[str, dict],
    *,
    force: bool,
    priority_plugins: Collection[str],
) -> bool:
    """Return whether a source is due without discarding its stored history."""
    if force or plugin_name in priority_plugins:
        return True
    state = freshness.get(plugin_name)
    return state is None or bool(state.get("stale", True))


def _fresh_age_label(age_hours: Optional[float]) -> str:
    return f" ({age_hours:.1f}h old)" if age_hours is not None else ""


def _run_plugin_with_deadline(plugin, start_date: date, end_date: date) -> FetchResult:
    """Run a plugin with an optional hard wall-clock deadline.

    A daemon worker is intentional here: ``requests`` cannot cancel a DNS call
    that is already inside the Windows resolver.  If the deadline expires, the
    refresh continues, stored observations remain untouched, and the stale
    source is retried on the next scheduled or manual refresh.
    """
    deadline = PLUGIN_DEADLINES_SECONDS.get(plugin.name)
    if deadline is None:
        return plugin.run(start_date, end_date)

    completed: queue.Queue[FetchResult | Exception] = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            completed.put(plugin.run(start_date, end_date), block=False)
        except Exception as exc:  # defensive: DataPlugin.run normally captures this
            completed.put(exc, block=False)

    worker = threading.Thread(
        target=_worker,
        name=f"ingestion-{plugin.name}",
        daemon=True,
    )
    worker.start()
    try:
        outcome = completed.get(timeout=deadline)
    except queue.Empty:
        logger.error("[%s] Hard deadline exceeded after %ss", plugin.name, deadline)
        return FetchResult(
            plugin_name=plugin.name,
            records=pd.DataFrame(),
            errors=[
                f"{plugin.name}: timed out after {deadline}s; retained stored data "
                "and will retry on the next refresh"
            ],
        )

    if isinstance(outcome, Exception):
        return FetchResult(
            plugin_name=plugin.name,
            records=pd.DataFrame(),
            errors=[f"{plugin.name} fetch exception: {outcome}"],
        )
    return outcome


def run_ingestion(
    timeframe: str = "weekly",
    lookback_days: int = 365 * 3,  # 3 years default
    force: bool = False,
    status_callback=None,
    priority_plugins: Optional[Collection[str]] = None,
) -> dict:
    """
    Run the full ingestion pipeline for all plugins.

    Args:
        timeframe: "weekly" or "monthly"
        lookback_days: How many days of history to fetch
        force: Force every source to refresh even if its data is fresh
        status_callback: Optional callable(msg: str) for progress updates
        priority_plugins: Sources that must refresh now; all other sources run
            only when their source-specific TTL has expired.

    Returns:
        Summary dict with counts and any errors
    """
    priority_plugins = frozenset(priority_plugins or ())
    freshness = get_plugin_freshness()
    if not force and not priority_plugins and not is_data_stale():
        logger.info("Data is fresh — skipping ingestion (use force=True to override)")
        return {"skipped": True, "reason": "data_fresh"}

    end_date = date.today()
    full_start_date = end_date - timedelta(days=lookback_days)

    run_id = str(uuid.uuid4())[:8]

    summary = {
        "run_id": run_id,
        "timeframe": timeframe,
        "start_date": str(full_start_date),
        "end_date": str(end_date),
        "plugins": {},
        "total_records": 0,
        "errors": [],
    }

    def _status(msg: str):
        logger.info("[%s] %s", run_id, msg)
        if status_callback:
            try:
                status_callback(msg)
            except UnicodeEncodeError:
                # Some Windows maintenance terminals still use cp1252. Keep
                # ingestion running even when their callback cannot print emoji.
                status_callback(msg.encode("ascii", "replace").decode("ascii"))

    _status(f"Starting ingestion {run_id} ({timeframe})")

    for PluginClass in ALL_PLUGINS:
        plugin = PluginClass()

        if not plugin.is_available:
            _status(f"⚠️  {plugin.name}: not available (check API key)")
            summary["plugins"][plugin.name] = {"status": "skipped", "reason": "unavailable"}
            continue

        if not _plugin_should_refresh(
            plugin.name,
            freshness,
            force=force,
            priority_plugins=priority_plugins,
        ):
            age = freshness[plugin.name].get("age_hours")
            _status(f"⏭️  {plugin.name}: fresh{_fresh_age_label(age)}")
            summary["plugins"][plugin.name] = {
                "status": "skipped",
                "reason": "fresh",
                "age_hours": age,
            }
            continue

        plugin_start = datetime.now(UTC).replace(tzinfo=None)
        start_date = _plugin_start_date(plugin.name, full_start_date, end_date)
        _status(f"📡 Fetching {plugin.description}...")

        result = _run_plugin_with_deadline(plugin, start_date, end_date)
        plugin_end = datetime.now(UTC).replace(tzinfo=None)
        duration = (plugin_end - plugin_start).total_seconds()

        records_stored = 0
        if result.success:
            default_frequency = (
                plugin.supported_frequencies[0].value
                if len(plugin.supported_frequencies) == 1 else None
            )
            records_stored = _store_raw_data(
                result.records, run_id, plugin.name, default_frequency
            )

        # Log to DB
        log_status = (
            "partial" if result.success and result.errors else
            "success" if result.success else
            "error" if result.errors else
            "partial"
        )
        _log_ingest(
            run_id=run_id,
            plugin=plugin.name,
            timeframe=timeframe,
            status=log_status,
            records_fetched=result.record_count,
            records_stored=records_stored,
            error_message="; ".join(result.errors) if result.errors else None,
            duration=duration,
            started_at=plugin_start,
            completed_at=plugin_end,
        )

        summary["plugins"][plugin.name] = {
            "status": log_status,
            "records_fetched": result.record_count,
            "records_stored": records_stored,
            "errors": result.errors,
            "warnings": result.warnings,
            "duration_s": round(duration, 2),
        }
        summary["total_records"] += records_stored

        if result.errors:
            _status(f"⚠️  {plugin.name} errors: {'; '.join(result.errors[:3])}")
        if result.success:
            _status(f"✅ {plugin.name}: stored {records_stored} records")

    # Also run options plugin (depends on yfinance)
    options_plugin = YFinanceOptionsPlugin()
    if options_plugin.is_available and _plugin_should_refresh(
        options_plugin.name,
        freshness,
        force=force,
        priority_plugins=priority_plugins,
    ):
        _status("📡 Fetching options chains (GEX, P/C)...")
        opt_start = datetime.now(UTC).replace(tzinfo=None)
        opt_result = options_plugin.run(end_date - timedelta(days=7), end_date)
        opt_end = datetime.now(UTC).replace(tzinfo=None)
        stored = 0
        if opt_result.success:
            stored = _store_raw_data(
                opt_result.records, run_id, options_plugin.name,
                options_plugin.supported_frequencies[0].value,
            )
            _status(f"✅ Options: stored {stored} records")

        opt_status = (
            "partial" if opt_result.success and opt_result.errors else
            "success" if opt_result.success else
            "error" if opt_result.errors else
            "partial"
        )
        _log_ingest(
            run_id=run_id,
            plugin=options_plugin.name,
            timeframe=timeframe,
            status=opt_status,
            records_fetched=opt_result.record_count,
            records_stored=stored,
            error_message="; ".join(opt_result.errors) if opt_result.errors else None,
            duration=(opt_end - opt_start).total_seconds(),
            started_at=opt_start,
            completed_at=opt_end,
        )
        summary["plugins"][options_plugin.name] = {
            "status": opt_status,
            "records_fetched": opt_result.record_count,
            "records_stored": stored,
            "errors": opt_result.errors,
            "warnings": opt_result.warnings,
        }
        summary["total_records"] += stored
    elif options_plugin.is_available:
        age = freshness[options_plugin.name].get("age_hours")
        _status(f"⏭️  {options_plugin.name}: fresh{_fresh_age_label(age)}")
        summary["plugins"][options_plugin.name] = {
            "status": "skipped", "reason": "fresh", "age_hours": age,
        }

    # FlashAlpha runs after Yahoo so its same-day aggregate analytics become
    # the preferred GEX/levels. If unavailable or tier-restricted, the Yahoo
    # records above remain the deterministic fallback.
    flashalpha_plugin = FlashAlphaPlugin()
    if not flashalpha_plugin.is_available:
        summary["plugins"][flashalpha_plugin.name] = {
            "status": "skipped",
            "reason": "API key not configured",
        }
    elif not _plugin_should_refresh(
        flashalpha_plugin.name,
        freshness,
        force=force,
        priority_plugins=priority_plugins,
    ):
        age = freshness[flashalpha_plugin.name].get("age_hours")
        _status(f"⏭️  {flashalpha_plugin.name}: fresh{_fresh_age_label(age)}")
        summary["plugins"][flashalpha_plugin.name] = {
            "status": "skipped", "reason": "fresh", "age_hours": age,
        }
    else:
        _status("📡 Fetching FlashAlpha aggregate exposure levels...")
        fa_start = datetime.now(UTC).replace(tzinfo=None)
        fa_result = flashalpha_plugin.run(end_date, end_date)
        fa_end = datetime.now(UTC).replace(tzinfo=None)
        fa_stored = 0
        if fa_result.success:
            fa_stored = _store_raw_data(
                fa_result.records,
                run_id,
                flashalpha_plugin.name,
                flashalpha_plugin.supported_frequencies[0].value,
            )

        fa_status = (
            "partial" if fa_result.success and fa_result.errors else
            "success" if fa_result.success else
            "error" if fa_result.errors else
            "partial"
        )
        _log_ingest(
            run_id=run_id,
            plugin=flashalpha_plugin.name,
            timeframe=timeframe,
            status=fa_status,
            records_fetched=fa_result.record_count,
            records_stored=fa_stored,
            error_message="; ".join(fa_result.errors) if fa_result.errors else None,
            duration=(fa_end - fa_start).total_seconds(),
            started_at=fa_start,
            completed_at=fa_end,
        )
        summary["plugins"][flashalpha_plugin.name] = {
            "status": fa_status,
            "records_fetched": fa_result.record_count,
            "records_stored": fa_stored,
            "errors": fa_result.errors,
            "warnings": fa_result.warnings,
        }
        summary["total_records"] += fa_stored
        if fa_result.success:
            _status(f"✅ FlashAlpha: stored {fa_stored} preferred analytics records")
        elif fa_result.errors:
            _status(
                f"⚠️  FlashAlpha unavailable; Yahoo fallback active: "
                f"{' '.join(fa_result.errors[:1])}"
            )

    _status(f"🏁 Ingestion complete. Total records: {summary['total_records']}")
    return summary


def _plugin_indicator_names(plugin_name: str) -> list[str]:
    """Indicators used to decide whether a plugin needs a historical backfill."""
    if plugin_name == "fred":
        from plugins.data.fred import FRED_SERIES
        return list(FRED_SERIES)
    if plugin_name == "yfinance":
        from plugins.data.yfinance_plugin import YFINANCE_TICKERS
        # Yahoo currently exposes only the latest few USD/CNH observations via
        # this endpoint. Keep collecting it, but do not let that provider-side
        # limitation trigger a full 28-ticker backfill on every refresh.
        return [name for name in YFINANCE_TICKERS if name != "usdcnh"]
    if plugin_name == "cftc":
        from plugins.data.cftc import CONTRACTS
        suffixes = {
            "tff": ["net_leveraged", "net_asset_mgr", "open_interest"],
            "legacy": ["net_noncommercial", "open_interest", "net_commercial"],
        }
        return [
            f"{base}_{suffix}"
            for base, cfg in CONTRACTS.items()
            for suffix in suffixes[cfg["report"]]
        ]
    if plugin_name == "breadth":
        return [
            "mcclellan_oscillator", "spx_mcclellan_sum", "advance_decline_line",
            "pct_above_20ma", "pct_above_50ma", "pct_above_200ma",
            "spx_net_new_highs",
        ]
    if plugin_name == "global_liquidity":
        return ["ecb_assets", "boj_assets"]
    if plugin_name == "etf_flows":
        from plugins.data.etf_flows import ETFS
        return list(ETFS.values())
    if plugin_name == "gld_official_flows":
        from plugins.data.gld_official_flows import GLD_INDICATORS
        return GLD_INDICATORS
    if plugin_name == "fed_rate_expectations":
        from plugins.data.fed_rate_expectations import FED_RATE_EXPECTATION_INDICATORS
        return FED_RATE_EXPECTATION_INDICATORS
    if plugin_name == "cboe":
        return [
            "cboe_equity_pc", "cboe_index_pc", "cboe_total_pc",
            "vix_spot", "vix3m_cboe", "vix6m_cboe",
        ]
    return []


def _plugin_start_date(plugin_name: str, full_start: date, end_date: date) -> date:
    """Backfill when any expected series is missing/short; otherwise overlap."""
    indicators = _plugin_indicator_names(plugin_name)
    if not indicators or plugin_name == "cboe":
        return end_date - timedelta(days=7)

    with get_session() as session:
        rows = session.execute(
            select(
                RawDataPoint.indicator,
                func.min(RawDataPoint.date),
                func.max(RawDataPoint.date),
                func.count(RawDataPoint.id),
            )
            .where(RawDataPoint.indicator.in_(indicators))
            .group_by(RawDataPoint.indicator)
        ).all()

    coverage = {
        indicator: (min_date, max_date, count)
        for indicator, min_date, max_date, count in rows
    }
    if _coverage_requires_backfill(coverage, indicators, full_start):
        return full_start

    latest = min(max_date for _min_date, max_date, _count in coverage.values())
    return max(full_start, latest.date() - timedelta(days=7))


def _store_raw_data(
    df: pd.DataFrame,
    run_id: str,
    plugin_name: str | None = None,
    default_frequency: str | None = None,
) -> int:
    """Store provider observations while preserving revised values."""
    if df.empty:
        return 0

    stored = 0
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    with get_session() as session:
        for _, row in df.iterrows():
            try:
                row_frequency = row.get("frequency")
                if pd.isna(row_frequency):
                    row_frequency = default_frequency
                store_raw_record(
                    session,
                    indicator=str(row["indicator"]),
                    observation_date=pd.Timestamp(row["date"]).to_pydatetime(),
                    value=float(row["value"]) if pd.notna(row["value"]) else None,
                    source=str(row.get("source", "")),
                    plugin=plugin_name,
                    unit=str(row.get("unit", "")),
                    frequency=str(row_frequency or ""),
                    api_response_ts=fetched_at,
                    ingest_run_id=run_id,
                    pit_observed_at=(
                        pd.Timestamp(row.get("observed_at")).to_pydatetime()
                        if pd.notna(row.get("observed_at")) else None
                    ),
                )
                stored += 1
            except Exception as exc:
                logger.debug("Store error for %s: %s", row.get("indicator"), exc)

    return stored


def _log_ingest(
    run_id: str,
    plugin: str,
    timeframe: str,
    status: str,
    records_fetched: int,
    records_stored: int,
    error_message: Optional[str],
    duration: float,
    started_at: datetime,
    completed_at: datetime,
):
    """Write an ingestion log entry."""
    with get_session() as session:
        log = IngestionLog(
            run_id=run_id,
            plugin=plugin,
            timeframe=timeframe,
            status=status,
            records_fetched=records_fetched,
            records_stored=records_stored,
            error_message=error_message,
            duration_seconds=duration,
            started_at=started_at,
            completed_at=completed_at,
        )
        session.add(log)


def load_raw_series(
    indicator: str,
    days: int = 252 * 3,
    end_date: date | datetime | None = None,
) -> pd.Series:
    """
    Load a single indicator's time series from the raw data table.
    Returns a pandas Series indexed by date.
    """
    end = (
        datetime.combine(end_date, datetime.max.time())
        if isinstance(end_date, date) and not isinstance(end_date, datetime)
        else end_date or datetime.now(UTC).replace(tzinfo=None)
    )
    start = end - timedelta(days=days)
    with get_session() as session:
        rows = session.execute(
            select(
                RawDataPoint.date,
                RawDataPoint.value,
                RawDataPoint.source,
                RawDataPoint.api_response_ts,
                RawDataPoint.id,
            )
            .where(
                RawDataPoint.indicator == indicator,
                RawDataPoint.date >= start,
                RawDataPoint.date <= end,
            )
            .order_by(RawDataPoint.date, RawDataPoint.id)
        ).all()

    if not rows:
        return pd.Series(dtype=float)

    frame = pd.DataFrame(
        rows,
        columns=["date", "value", "source", "api_response_ts", "id"],
    )
    option_analytics = indicator.endswith(
        ("_gex", "_gamma_flip", "_call_wall", "_put_wall")
    )
    if option_analytics:
        # Same-day provider priority is explicit: FlashAlpha analytics first,
        # Yahoo model second. This prevents SQLite insertion order from
        # silently changing the bias input.
        frame["provider_priority"] = frame["source"].fillna("").map(
            lambda source: 20 if str(source).startswith("flashalpha:") else 10
        )
    else:
        frame["provider_priority"] = 0
    frame = frame.sort_values(
        ["date", "provider_priority", "api_response_ts", "id"],
        na_position="first",
    ).drop_duplicates("date", keep="last")
    series = pd.Series(
        frame["value"].to_numpy(),
        index=pd.DatetimeIndex(frame["date"]),
        name=indicator,
    )
    return _normalize_market_snapshot_index(indicator, series.sort_index())


def load_all_series(
    indicators: list[str],
    days: int = 252 * 3,
    end_date: date | datetime | None = None,
) -> dict[str, pd.Series]:
    """Load multiple indicators at once."""
    return {ind: load_raw_series(ind, days, end_date=end_date) for ind in indicators}
