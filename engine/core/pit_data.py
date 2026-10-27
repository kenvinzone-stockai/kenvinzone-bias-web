"""Point-in-time series catalog and immutable observation repository.

The operational ``raw_data`` table remains the latest-value cache.  This module is the
research truth path: a value can be reconstructed only from a vintage whose
``available_at`` is no later than the decision timestamp.  Existing history is never
assigned a synthetic past availability time during ingestion; a normal live fetch is
usable only from the time this installation actually recorded it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
import hashlib
import json
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.models import ObservationVintage, SeriesDefinition


class VintageSource(str, Enum):
    """Controlled evidence taxonomy for historical availability."""

    VERIFIED_PROVIDER_VINTAGE = "verified_provider_vintage"
    VERIFIED_RELEASE_TIMESTAMP = "verified_release_timestamp"
    RECORDED_LIVE = "recorded_live"
    DECLARED_RULE = "declared_rule"
    CURRENT_VINTAGE_BACKFILL = "current_vintage_backfill"
    UNKNOWN = "unknown"


PROMOTION_SAFE_VINTAGE_SOURCES = frozenset({
    VintageSource.VERIFIED_PROVIDER_VINTAGE.value,
    VintageSource.VERIFIED_RELEASE_TIMESTAMP.value,
    VintageSource.RECORDED_LIVE.value,
})

_POLICY_METHODS = {"recorded_at", "provider_timestamp", "declared_schedule"}
_STALE_ACTIONS = {"block", "flag"}
_POLICY_KEYS = {
    "method", "timezone", "release_time", "calendar", "stale_action",
    "official_url", "notes",
}
_FREQUENCIES = {"tick", "intraday", "daily", "weekly", "monthly", "quarterly"}
_REVISION_CLASSES = {
    "non_revising", "market_history", "continuous_contract", "revisable",
    "derived_universe",
}
_SERIES_STATUSES = {"active", "research", "blocked", "retired"}


class InvalidSeriesPolicy(ValueError):
    """Raised when publication metadata does not match the controlled schema."""


class SeriesDefinitionConflict(ValueError):
    """Raised when an immutable catalog version already has different contents."""


class InvalidObservationVintage(ValueError):
    """Raised when observation timestamps or vintage evidence are inconsistent."""


def _naive_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be a datetime")
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def validate_publication_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the JSON persisted by ``SeriesDefinition``."""
    if not isinstance(policy, Mapping):
        raise InvalidSeriesPolicy("publication_policy must be an object")
    unknown = set(policy) - _POLICY_KEYS
    if unknown:
        raise InvalidSeriesPolicy(f"unknown publication policy keys: {sorted(unknown)}")
    method = policy.get("method")
    if method not in _POLICY_METHODS:
        raise InvalidSeriesPolicy(f"method must be one of {sorted(_POLICY_METHODS)}")
    stale_action = policy.get("stale_action", "block")
    if stale_action not in _STALE_ACTIONS:
        raise InvalidSeriesPolicy(f"stale_action must be one of {sorted(_STALE_ACTIONS)}")
    timezone = policy.get("timezone", "UTC")
    if not isinstance(timezone, str) or not timezone.strip():
        raise InvalidSeriesPolicy("timezone must be a non-empty string")
    release_time = policy.get("release_time")
    if release_time is not None:
        try:
            hour, minute = (int(part) for part in release_time.split(":"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise InvalidSeriesPolicy("release_time must use HH:MM") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise InvalidSeriesPolicy("release_time must use a valid HH:MM")
    normalized = dict(policy)
    normalized["method"] = method
    normalized["timezone"] = timezone
    normalized["stale_action"] = stale_action
    return normalized


@dataclass(frozen=True)
class CatalogEntry:
    series_key: str
    provider: str
    unit: Optional[str]
    frequency: str
    publication_policy: Mapping[str, Any]
    revision_class: str
    ttl_seconds: Optional[int]
    oos_eligible: bool
    status: str = "active"
    plugin: Optional[str] = None
    definition_version: int = 1

    def normalized_policy(self) -> dict[str, Any]:
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise InvalidSeriesPolicy("ttl_seconds must be positive or null")
        return validate_publication_policy(self.publication_policy)


_FRED_DOC = "https://fred.stlouisfed.org/docs/api/fred/alfred.html"
_CFTC_DOC = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm"


def _recorded_policy(*, notes: str, official_url: Optional[str] = None) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "method": "recorded_at",
        "timezone": "UTC",
        "stale_action": "block",
        "notes": notes,
    }
    if official_url:
        policy["official_url"] = official_url
    return policy


def _entry(
    key: str,
    provider: str,
    unit: Optional[str],
    frequency: str,
    ttl_seconds: Optional[int],
    *,
    plugin: str,
    revision_class: str = "revisable",
    oos_eligible: bool = True,
    status: str = "active",
    notes: str,
    official_url: Optional[str] = None,
) -> CatalogEntry:
    return CatalogEntry(
        series_key=key,
        provider=provider,
        plugin=plugin,
        unit=unit,
        frequency=frequency,
        publication_policy=_recorded_policy(notes=notes, official_url=official_url),
        revision_class=revision_class,
        ttl_seconds=ttl_seconds,
        oos_eligible=oos_eligible,
        status=status,
    )


# V1 catalog covers the inputs proposed for the frozen 4W research feature set.
# ``recorded_at`` is deliberate: current plugins do not fetch ALFRED vintages or a
# complete historical CFTC release calendar, so old raw rows are not backdated.
DEFAULT_SERIES_CATALOG: tuple[CatalogEntry, ...] = (
    _entry("spx_close", "Yahoo Finance", "index", "daily", 4 * 86400,
           plugin="yfinance", revision_class="market_history", notes="Usable from local capture time."),
    _entry("spy_close", "Yahoo Finance", "USD", "daily", 4 * 86400,
           plugin="yfinance", revision_class="market_history", notes="Usable from local capture time."),
    _entry("ndx_close", "Yahoo Finance", "index", "daily", 4 * 86400,
           plugin="yfinance", revision_class="market_history", notes="Usable from local capture time."),
    _entry("nasdaq_close", "Yahoo Finance", "index", "daily", 4 * 86400,
           plugin="yfinance", revision_class="market_history", notes="Usable from local capture time."),
    _entry("qqq_close", "Yahoo Finance", "USD", "daily", 4 * 86400,
           plugin="yfinance", revision_class="market_history", notes="Usable from local capture time."),
    _entry("gold_futures", "Yahoo Finance", "USD", "daily", 4 * 86400,
           plugin="yfinance", revision_class="continuous_contract", notes="Contract/adjustment provenance required later."),
    _entry("gld_close", "Yahoo Finance", "USD", "daily", 4 * 86400,
           plugin="yfinance", revision_class="market_history", notes="Usable from local capture time."),
    _entry("dxy", "Yahoo Finance", "index", "daily", 4 * 86400,
           plugin="yfinance", revision_class="market_history", notes="Usable from local capture time."),
    _entry("vix", "Yahoo Finance", "index", "daily", 4 * 86400,
           plugin="yfinance", revision_class="market_history", notes="Usable from local capture time."),
    _entry("vix3m", "Yahoo Finance", "index", "daily", 4 * 86400,
           plugin="yfinance", revision_class="market_history", notes="Usable from local capture time."),
    _entry("us_10y_real_yield", "FRED", "%", "daily", 7 * 86400,
           plugin="fred", notes="Plain FRED history is today's vintage; live captures are safe prospectively.", official_url=_FRED_DOC),
    _entry("us_10y_yield", "FRED", "%", "daily", 7 * 86400,
           plugin="fred", notes="Plain FRED history is today's vintage; live captures are safe prospectively.", official_url=_FRED_DOC),
    _entry("us_2y_yield", "FRED", "%", "daily", 7 * 86400,
           plugin="fred", notes="Plain FRED history is today's vintage; live captures are safe prospectively.", official_url=_FRED_DOC),
    _entry("hy_oas", "FRED", "%", "daily", 7 * 86400,
           plugin="fred", notes="Plain FRED history is today's vintage; live captures are safe prospectively.", official_url=_FRED_DOC),
    _entry("vix_fred", "FRED", "index", "daily", 7 * 86400,
           plugin="fred", notes="Plain FRED history is today's vintage; live captures are safe prospectively.", official_url=_FRED_DOC),
    _entry("fed_balance_sheet", "FRED", "M USD", "weekly", 14 * 86400,
           plugin="fred", oos_eligible=False, status="research", notes="Blocked until ALFRED vintages are ingested.", official_url=_FRED_DOC),
    _entry("tga", "FRED", "M USD", "weekly", 14 * 86400,
           plugin="fred", oos_eligible=False, status="research", notes="Blocked until verified historical availability is ingested.", official_url=_FRED_DOC),
    _entry("on_rrp", "FRED", "B USD", "daily", 7 * 86400,
           plugin="fred", oos_eligible=False, status="research", notes="Blocked from the initial feature set pending vintage audit.", official_url=_FRED_DOC),
    _entry("us_m2", "FRED", "B USD", "weekly", 45 * 86400,
           plugin="fred", oos_eligible=False, status="research", notes="Revision-prone macro history requires ALFRED vintages.", official_url=_FRED_DOC),
    *tuple(
        _entry(key, "CFTC", "contracts" if not key.endswith("open_interest") else "contracts",
               "weekly", 10 * 86400, plugin="cftc", notes="Tuesday positions; current ingestion is safe only from capture time. Official releases are normally Friday 15:30 ET but holidays vary.", official_url=_CFTC_DOC)
        for key in (
            "cot_spx_net_leveraged", "cot_spx_open_interest",
            "cot_nasdaq_net_leveraged", "cot_nasdaq_open_interest",
            "cot_gold_net_noncommercial", "cot_gold_open_interest",
        )
    ),
    _entry("mcclellan_oscillator", "Yahoo-derived breadth", "index", "daily", 4 * 86400,
           plugin="breadth", revision_class="derived_universe", oos_eligible=False, status="blocked", notes="Constituent-universe lineage and survivorship are not verified."),
    _entry("pct_above_200ma", "Yahoo-derived breadth", "%", "daily", 4 * 86400,
           plugin="breadth", revision_class="derived_universe", oos_eligible=False, status="blocked", notes="Constituent-universe lineage and survivorship are not verified."),
)


def _definition_signature(entry: CatalogEntry) -> dict[str, Any]:
    if entry.frequency not in _FREQUENCIES:
        raise InvalidSeriesPolicy(f"unsupported frequency: {entry.frequency}")
    if entry.revision_class not in _REVISION_CLASSES:
        raise InvalidSeriesPolicy(f"unsupported revision_class: {entry.revision_class}")
    if entry.status not in _SERIES_STATUSES:
        raise InvalidSeriesPolicy(f"unsupported series status: {entry.status}")
    return {
        "provider": entry.provider,
        "plugin": entry.plugin,
        "unit": entry.unit,
        "frequency": entry.frequency,
        "publication_policy": entry.normalized_policy(),
        "revision_class": entry.revision_class,
        "ttl_seconds": entry.ttl_seconds,
        "oos_eligible": entry.oos_eligible,
        "status": entry.status,
    }


def sync_series_catalog(
    session: Session,
    entries: Iterable[CatalogEntry] = DEFAULT_SERIES_CATALOG,
) -> list[SeriesDefinition]:
    """Insert immutable catalog versions idempotently; never update a definition."""
    rows: list[SeriesDefinition] = []
    for entry in entries:
        signature = _definition_signature(entry)
        existing = session.scalar(select(SeriesDefinition).where(
            SeriesDefinition.series_key == entry.series_key,
            SeriesDefinition.definition_version == entry.definition_version,
        ))
        if existing is not None:
            actual = {key: getattr(existing, key) for key in signature}
            if actual != signature:
                raise SeriesDefinitionConflict(
                    f"{entry.series_key} v{entry.definition_version} already exists with different policy"
                )
            rows.append(existing)
            continue
        row = SeriesDefinition(
            series_key=entry.series_key,
            definition_version=entry.definition_version,
            **signature,
        )
        session.add(row)
        session.flush()
        rows.append(row)
    return rows


def _payload_hash(
    *,
    value: Optional[float],
    vintage_id: Optional[str],
    vintage_source: str,
    quality_flags: Mapping[str, Any],
) -> str:
    encoded = json.dumps({
        "value": value,
        "vintage_id": vintage_id,
        "vintage_source": vintage_source,
        "quality_flags": dict(quality_flags),
    }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def append_observation_vintage(
    session: Session,
    *,
    series_definition: SeriesDefinition,
    observed_at: datetime,
    available_at: datetime,
    recorded_at: datetime,
    value: Optional[float],
    vintage_source: str | VintageSource,
    vintage_id: Optional[str] = None,
    ingest_run_id: Optional[str] = None,
    quality_flags: Optional[Mapping[str, Any]] = None,
) -> ObservationVintage:
    """Append one verified/declared vintage, idempotently by immutable payload."""
    observed = _naive_utc(observed_at)
    available = _naive_utc(available_at)
    recorded = _naive_utc(recorded_at)
    source = vintage_source.value if isinstance(vintage_source, VintageSource) else str(vintage_source)
    if source not in {item.value for item in VintageSource}:
        raise InvalidObservationVintage(f"uncontrolled vintage_source: {source}")
    if available < observed:
        raise InvalidObservationVintage("available_at cannot precede observed_at")
    if source == VintageSource.RECORDED_LIVE.value and available != recorded:
        raise InvalidObservationVintage(
            "recorded_live availability must equal the local capture timestamp"
        )
    flags = dict(quality_flags or {})
    payload_hash = _payload_hash(
        value=value, vintage_id=vintage_id, vintage_source=source, quality_flags=flags,
    )
    existing = session.scalar(select(ObservationVintage).where(
        ObservationVintage.series_definition_id == series_definition.id,
        ObservationVintage.observed_at == observed,
        ObservationVintage.payload_hash == payload_hash,
    ).order_by(ObservationVintage.available_at))
    if existing is not None:
        return existing
    row = ObservationVintage(
        series_definition_id=series_definition.id,
        observed_at=observed,
        available_at=available,
        recorded_at=recorded,
        value=value,
        vintage_id=vintage_id,
        vintage_source=source,
        payload_hash=payload_hash,
        ingest_run_id=ingest_run_id,
        quality_flags=flags,
    )
    session.add(row)
    session.flush()
    return row


def latest_series_definition(session: Session, series_key: str) -> Optional[SeriesDefinition]:
    return session.scalar(select(SeriesDefinition).where(
        SeriesDefinition.series_key == series_key,
    ).order_by(desc(SeriesDefinition.definition_version)).limit(1))


def mirror_ingested_observation(
    session: Session,
    *,
    indicator: str,
    observed_at: datetime,
    value: Optional[float],
    recorded_at: datetime,
    provider_source: str,
    ingest_run_id: Optional[str],
) -> Optional[ObservationVintage]:
    """Prospectively mirror a catalogued raw record without backdating availability."""
    definition = latest_series_definition(session, indicator)
    if definition is None:
        return None
    captured = _naive_utc(recorded_at)
    return append_observation_vintage(
        session,
        series_definition=definition,
        observed_at=observed_at,
        available_at=captured,
        recorded_at=captured,
        value=value,
        vintage_source=VintageSource.RECORDED_LIVE,
        ingest_run_id=ingest_run_id,
        quality_flags={"provider_source": provider_source, "prospective_capture": True},
    )


@dataclass(frozen=True)
class PITValue:
    series_key: str
    definition_version: int
    value: Optional[float]
    observed_at: datetime
    available_at: datetime
    recorded_at: datetime
    vintage_source: str
    age_seconds: float
    stale: bool
    promotion_eligible: bool
    eligibility_reasons: tuple[str, ...]
    observation_vintage_id: int


def point_in_time_value(
    session: Session,
    series_key: str,
    decision_at: datetime,
    *,
    definition_version: Optional[int] = None,
    observed_at_or_before: Optional[datetime] = None,
    promotion_safe_only: bool = False,
) -> Optional[PITValue]:
    """Return the newest observation genuinely available at ``decision_at``."""
    decision = _naive_utc(decision_at)
    observed_cutoff = (
        _naive_utc(observed_at_or_before)
        if observed_at_or_before is not None else decision
    )
    if observed_cutoff > decision:
        raise ValueError("observed_at_or_before cannot be after decision_at")
    definition_query = select(SeriesDefinition).where(SeriesDefinition.series_key == series_key)
    if definition_version is not None:
        definition_query = definition_query.where(
            SeriesDefinition.definition_version == definition_version
        )
    else:
        definition_query = definition_query.order_by(
            desc(SeriesDefinition.definition_version)
        ).limit(1)
    definition = session.scalar(definition_query)
    if definition is None:
        return None
    validate_publication_policy(definition.publication_policy)
    vintage = session.scalar(select(ObservationVintage).where(
        ObservationVintage.series_definition_id == definition.id,
        ObservationVintage.observed_at <= observed_cutoff,
        ObservationVintage.available_at <= decision,
    ).order_by(
        desc(ObservationVintage.observed_at),
        desc(ObservationVintage.available_at),
        desc(ObservationVintage.recorded_at),
        desc(ObservationVintage.id),
    ).limit(1))
    if vintage is None:
        return None
    # For a historical lookback requested at a later decision time, freshness is
    # measured around that lookback cutoff, not against the final decision date.
    age_seconds = max(0.0, (observed_cutoff - vintage.observed_at).total_seconds())
    stale = definition.ttl_seconds is not None and age_seconds > definition.ttl_seconds
    reasons: list[str] = []
    if definition.status != "active":
        reasons.append(f"series_status:{definition.status}")
    if not definition.oos_eligible:
        reasons.append("series_not_oos_eligible")
    if vintage.vintage_source not in PROMOTION_SAFE_VINTAGE_SOURCES:
        reasons.append(f"unsafe_vintage_source:{vintage.vintage_source}")
    if stale and definition.publication_policy.get("stale_action", "block") == "block":
        reasons.append("ttl_exceeded")
    result = PITValue(
        series_key=series_key,
        definition_version=definition.definition_version,
        value=vintage.value,
        observed_at=vintage.observed_at,
        available_at=vintage.available_at,
        recorded_at=vintage.recorded_at,
        vintage_source=vintage.vintage_source,
        age_seconds=age_seconds,
        stale=stale,
        promotion_eligible=not reasons,
        eligibility_reasons=tuple(reasons),
        observation_vintage_id=vintage.id,
    )
    if promotion_safe_only and not result.promotion_eligible:
        return None
    return result


@dataclass
class PITPanel:
    values: dict[str, PITValue] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def point_in_time_panel(
    session: Session,
    series_keys: Iterable[str],
    decision_at: datetime,
    *,
    promotion_safe_only: bool = False,
) -> PITPanel:
    """Query series independently so one unavailable source cannot block the panel."""
    panel = PITPanel()
    for key in series_keys:
        try:
            result = point_in_time_value(
                session, key, decision_at, promotion_safe_only=promotion_safe_only,
            )
            if result is None:
                panel.missing.append(key)
            else:
                panel.values[key] = result
        except Exception as exc:  # isolate malformed policy/data to its series
            panel.errors[key] = f"{type(exc).__name__}: {exc}"
    return panel
