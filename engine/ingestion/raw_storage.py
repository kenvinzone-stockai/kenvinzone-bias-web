"""Centralized storage rules for auditable provider observations."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import RawDataPoint, RawDataRevision

logger = logging.getLogger(__name__)


def _values_differ(old_value: Optional[float], new_value: Optional[float]) -> bool:
    if old_value is None or new_value is None:
        return old_value is not new_value
    return float(old_value) != float(new_value)


def store_raw_record(
    session: Session,
    *,
    indicator: str,
    observation_date: datetime,
    value: Optional[float],
    source: str,
    plugin: Optional[str],
    unit: Optional[str],
    frequency: Optional[str],
    api_response_ts: datetime,
    ingest_run_id: Optional[str] = None,
    pit_observed_at: Optional[datetime] = None,
) -> RawDataPoint:
    """Insert an observation or archive its old value before a revision.

    Re-fetching an unchanged value refreshes provenance metadata without
    creating a fake data revision.
    """
    existing = session.execute(
        select(RawDataPoint).where(
            RawDataPoint.indicator == indicator,
            RawDataPoint.date == observation_date,
            RawDataPoint.source == source,
        )
    ).scalar_one_or_none()

    if existing is None:
        record = RawDataPoint(
            indicator=indicator,
            date=observation_date,
            value=value,
            source=source,
            plugin=plugin,
            original_unit=unit,
            original_frequency=frequency,
            api_response_ts=api_response_ts,
            data_version=1,
        )
        session.add(record)
        _mirror_to_pit(
            session, indicator, pit_observed_at or observation_date, value, api_response_ts,
            source, ingest_run_id,
        )
        return record

    if _values_differ(existing.value, value):
        session.add(RawDataRevision(
            raw_data_id=existing.id,
            indicator=existing.indicator,
            date=existing.date,
            value=existing.value,
            source=existing.source,
            plugin=existing.plugin,
            original_unit=existing.original_unit,
            original_frequency=existing.original_frequency,
            api_response_ts=existing.api_response_ts,
            data_version=existing.data_version or 1,
        ))
        existing.data_version = (existing.data_version or 1) + 1

    existing.value = value
    existing.plugin = plugin or existing.plugin
    existing.original_unit = unit or existing.original_unit
    existing.original_frequency = frequency or existing.original_frequency
    existing.api_response_ts = api_response_ts
    _mirror_to_pit(
        session, indicator, pit_observed_at or observation_date, value, api_response_ts,
        source, ingest_run_id,
    )
    return existing


def _mirror_to_pit(
    session: Session,
    indicator: str,
    observation_date: datetime,
    value: Optional[float],
    api_response_ts: datetime,
    source: str,
    ingest_run_id: Optional[str],
) -> None:
    """Best-effort PIT mirror isolated by a savepoint from the operational cache."""
    try:
        from core.pit_data import mirror_ingested_observation

        with session.begin_nested():
            mirror_ingested_observation(
                session,
                indicator=indicator,
                observed_at=observation_date,
                value=value,
                recorded_at=api_response_ts,
                provider_source=source,
                ingest_run_id=ingest_run_id,
            )
    except Exception as exc:
        # The latest-value pipeline must remain available during incremental PIT rollout.
        # A catalog/policy failure is visible in logs and cannot create a partial vintage.
        logger.warning("PIT mirror skipped for %s: %s", indicator, exc)
