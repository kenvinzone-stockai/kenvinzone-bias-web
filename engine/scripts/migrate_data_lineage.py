"""Idempotent data-lineage migration for existing local databases."""
from __future__ import annotations

from sqlalchemy import update

from core.database import get_session, init_db
from core.models import RawDataPoint


def main() -> None:
    init_db()  # Creates raw_data_revisions without altering existing rows.
    with get_session() as session:
        result = session.execute(
            update(RawDataPoint)
            .where(RawDataPoint.indicator == "us_2y_yf")
            .values(indicator="us_3m_yf")
        )
        renamed = result.rowcount or 0
    print(f"Data-lineage migration complete; renamed {renamed} ^IRX observations.")


if __name__ == "__main__":
    main()
