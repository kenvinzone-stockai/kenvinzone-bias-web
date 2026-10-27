"""Persistence invariants for adaptive research artifacts.

The repository deliberately exposes append operations only. SQLite triggers installed by
``install_append_only_guards`` provide a second storage-layer boundary so an ORM caller or
manual SQL statement cannot rewrite historical feature or promotion evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from core.models import FeatureSnapshot


class ImmutableSnapshotConflict(ValueError):
    """Raised when a natural snapshot key already exists with different contents."""


@dataclass(frozen=True)
class FeatureSnapshotPayload:
    feature_set_version: str
    asset: str
    horizon: str
    as_of: datetime
    values: dict[str, Any]
    availability: dict[str, Any]
    quality: dict[str, Any]
    lineage: dict[str, Any]
    vintage_source: str

    def canonical_hash(self) -> str:
        payload = {
            "feature_set_version": self.feature_set_version,
            "asset": self.asset,
            "horizon": self.horizon,
            "as_of": self.as_of.isoformat(),
            "values": self.values,
            "availability": self.availability,
            "quality": self.quality,
            "lineage": self.lineage,
            "vintage_source": self.vintage_source,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False, default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def install_append_only_guards(db_engine: Engine) -> None:
    """Install idempotent SQLite triggers protecting immutable audit tables."""
    if db_engine.dialect.name != "sqlite":
        raise RuntimeError("Append-only guards currently require the deployed SQLite database")
    # Every correction to these audit artifacts appends a new version/row.
    # Existing evidence must never be edited or removed in place.
    protected = (
        "series_definitions",
        "observation_vintages",
        "feature_definitions",
        "feature_snapshots",
        "research_model_specs",
        "research_model_versions",
        "research_predictions",
        "research_prediction_factors",
        "research_outcomes",
        "research_evaluation_runs",
        "research_calibration_runs",
        "research_promotion_events",
        "ai_tool_audits",
        "assistant_preference_events",
        "ai_research_telemetry",
    )
    with db_engine.begin() as connection:
        for table_name in protected:
            connection.execute(text(f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
            """))
            connection.execute(text(f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
            """))
        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_observation_vintages_validate_source
            BEFORE INSERT ON observation_vintages
            WHEN NEW.vintage_source NOT IN (
                'verified_provider_vintage',
                'verified_release_timestamp',
                'recorded_live',
                'declared_rule',
                'current_vintage_backfill',
                'unknown'
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid observation_vintages.vintage_source');
            END
        """))


def append_feature_snapshot(
    session: Session,
    payload: FeatureSnapshotPayload,
) -> FeatureSnapshot:
    """Append an immutable snapshot, returning an identical existing row idempotently."""
    existing = session.execute(
        select(FeatureSnapshot).where(
            FeatureSnapshot.feature_set_version == payload.feature_set_version,
            FeatureSnapshot.asset == payload.asset,
            FeatureSnapshot.horizon == payload.horizon,
            FeatureSnapshot.as_of == payload.as_of,
        )
    ).scalar_one_or_none()
    snapshot_hash = payload.canonical_hash()
    if existing is not None:
        if existing.snapshot_hash != snapshot_hash:
            raise ImmutableSnapshotConflict(
                "Snapshot natural key already exists with different content; "
                "create a new feature_set_version"
            )
        return existing

    row = FeatureSnapshot(
        feature_set_version=payload.feature_set_version,
        asset=payload.asset,
        horizon=payload.horizon,
        as_of=payload.as_of,
        values_json=payload.values,
        availability_json=payload.availability,
        quality_json=payload.quality,
        lineage_json=payload.lineage,
        vintage_source=payload.vintage_source,
        snapshot_hash=snapshot_hash,
    )
    session.add(row)
    session.flush()
    return row
