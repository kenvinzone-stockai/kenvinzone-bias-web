"""Idempotent metadata corrections introduced by the 2026-08 model audit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from core.database import engine, get_session
from core.models import RawDataPoint, RawDataRevision
from plugins.data.cftc import cot_available_date


def _normalize_option_dates() -> tuple[int, int]:
    """Move legacy weekend option snapshots to their market observation date."""
    moved = 0
    merged = 0
    with get_session() as session:
        weekend_rows = session.execute(
            select(RawDataPoint)
            .where(RawDataPoint.plugin == "yfinance_options")
            .order_by(RawDataPoint.date, RawDataPoint.id)
        ).scalars().all()
        for row in weekend_rows:
            weekday = row.date.weekday()
            if weekday not in {5, 6}:
                continue
            target_date = row.date - timedelta(days=1 if weekday == 5 else 2)
            target = session.execute(
                select(RawDataPoint).where(
                    RawDataPoint.indicator == row.indicator,
                    RawDataPoint.date == target_date,
                    RawDataPoint.source == row.source,
                    RawDataPoint.id != row.id,
                )
            ).scalar_one_or_none()
            if target is None:
                row.date = target_date
                moved += 1
                continue

            latest_revision = session.execute(
                select(func.max(RawDataRevision.data_version)).where(
                    RawDataRevision.raw_data_id == target.id
                )
            ).scalar() or 0
            revision_version = latest_revision + 1
            session.add(RawDataRevision(
                raw_data_id=target.id,
                indicator=row.indicator,
                date=target_date,
                value=row.value,
                source=row.source,
                plugin=row.plugin,
                original_unit=row.original_unit,
                original_frequency=row.original_frequency,
                api_response_ts=row.api_response_ts,
                data_version=revision_version,
                archived_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ))
            target.data_version = max(target.data_version or 1, revision_version + 1)
            session.delete(row)
            merged += 1
    return moved, merged


def _normalize_cftc_release_dates() -> int:
    """Upgrade legacy +3-calendar-day COT timestamps to federal business days."""
    corrected = 0
    with get_session() as session:
        rows = session.execute(
            select(RawDataPoint).where(
                RawDataPoint.plugin == "cftc",
                RawDataPoint.source.like("CFTC:%:available"),
            )
        ).scalars().all()
        for row in rows:
            inferred_report_date = row.date - timedelta(days=3)
            corrected_date = cot_available_date(inferred_report_date).to_pydatetime()
            revisions = session.execute(
                select(RawDataRevision).where(
                    RawDataRevision.raw_data_id == row.id
                )
            ).scalars().all()
            row.date = corrected_date
            row.source = f"{row.source}_usfedcal"
            for revision in revisions:
                revision.date = corrected_date
                if revision.source.endswith(":available"):
                    revision.source = f"{revision.source}_usfedcal"
            corrected += 1
    return corrected


def main() -> None:
    with engine.begin() as connection:
        framework_rows = connection.execute(text("""
            UPDATE framework_versions
            SET status = CASE WHEN is_active = 1 THEN 'active' ELSE 'archived' END
            WHERE status != CASE WHEN is_active = 1 THEN 'active' ELSE 'archived' END
        """)).rowcount
        oas_rows = connection.execute(text("""
            UPDATE raw_data
            SET original_unit = '%'
            WHERE indicator IN ('hy_oas', 'ig_oas', 'hy_bb_oas')
              AND COALESCE(original_unit, '') != '%'
        """)).rowcount
        gex_rows = connection.execute(text("""
            UPDATE raw_data
            SET original_unit = 'M USD'
            WHERE indicator LIKE '%_net_gex_fa'
              AND COALESCE(original_unit, '') != 'M USD'
        """)).rowcount
        invalid_cftc_rows = connection.execute(text("""
            DELETE FROM raw_data
            WHERE plugin = 'cftc'
              AND source IN ('CFTC:13874+', 'CFTC:209742', 'CFTC:043801')
        """)).rowcount
        cftc_release_rows = connection.execute(text("""
            UPDATE raw_data
            SET date = datetime(date, '+3 days'),
                source = source || :release_suffix
            WHERE plugin = 'cftc'
              AND source IN (
                  'CFTC:13874A', 'CFTC:20974+', 'CFTC:088691', 'CFTC:043602'
              )
        """), {"release_suffix": ":available"}).rowcount
        mislabeled_flow_rows = connection.execute(text("""
            DELETE FROM raw_data
            WHERE plugin = 'etf_flows'
              AND indicator IN (
                  'spy_flow', 'qqq_flow', 'gld_flow', 'iau_flow',
                  'tlt_flow', 'hyg_flow', 'lqd_flow'
              )
        """)).rowcount

    option_dates_moved, option_dates_merged = _normalize_option_dates()
    cftc_release_dates = _normalize_cftc_release_dates()

    print(
        f"metadata migration: frameworks={framework_rows}, "
        f"oas_units={oas_rows}, gex_units={gex_rows}, "
        f"invalid_cftc_rows={invalid_cftc_rows}, "
        f"cftc_release_rows={cftc_release_rows}, "
        f"mislabeled_flow_rows={mislabeled_flow_rows}, "
        f"option_dates_moved={option_dates_moved}, "
        f"option_dates_merged={option_dates_merged}, "
        f"cftc_release_dates={cftc_release_dates}"
    )


if __name__ == "__main__":
    main()
