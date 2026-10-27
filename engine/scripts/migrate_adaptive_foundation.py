"""Idempotent SQLite schema migration for the adaptive research foundation.

The migration creates new tables and append-only guards only. It does not rewrite or
delete any existing market, bias, forecast, option, or narrative row.

V1 is deliberately deployed on SQLite. A future PostgreSQL migration must install
database-level trigger/permission guards with equivalent semantics; ORM events alone are
not an adequate substitute because direct SQL can bypass them.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect

from core.database import Base, engine
from core import models  # noqa: F401 — register every ORM table
from core.research_store import install_append_only_guards
from core.pit_data import sync_series_catalog
from sqlalchemy.orm import Session


FOUNDATION_TABLES = {
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
}


def migrate(db_engine=engine) -> set[str]:
    """Create missing foundation objects and return the verified table names."""
    Base.metadata.create_all(bind=db_engine)
    install_append_only_guards(db_engine)
    with Session(db_engine) as session:
        sync_series_catalog(session)
        session.commit()
    present = set(inspect(db_engine).get_table_names())
    missing = FOUNDATION_TABLES - present
    if missing:
        raise RuntimeError(f"Adaptive foundation migration is incomplete: {sorted(missing)}")
    return FOUNDATION_TABLES & present


def main() -> None:
    created = migrate()
    print(f"Adaptive foundation ready; verified {len(created)} tables.")


if __name__ == "__main__":
    main()
