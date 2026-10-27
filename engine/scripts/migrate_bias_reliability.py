"""One-time, idempotent migration for the corrected market-state framework.

The previous active framework used unreachable regime thresholds and disabled
Gold-native inputs.  This migration preserves that row as archived and creates
one auditable corrected version.  Re-running it never creates duplicates or
re-activates an older corrected version after a later promotion.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import desc, func, select

from bias.regimes import DEFAULT_THRESHOLDS
from core.database import get_session
from core.models import FrameworkVersion


CORRECTED_FRAMEWORK_NAME = "Corrected market-state reliability"


def migrate() -> int:
    with get_session() as session:
        existing = session.execute(
            select(FrameworkVersion).where(
                FrameworkVersion.name == CORRECTED_FRAMEWORK_NAME
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing.version

        active = session.execute(
            select(FrameworkVersion)
            .where(FrameworkVersion.is_active == True)
            .order_by(desc(FrameworkVersion.version))
        ).scalar_one_or_none()
        if active is None:
            raise RuntimeError("No active framework exists to migrate")

        next_version = int(
            session.execute(select(func.max(FrameworkVersion.version))).scalar() or 0
        ) + 1
        gold_weights = dict(active.gold_weights or {})
        if float(gold_weights.get("gold_specific", 0.0)) <= 0.0:
            gold_weights["gold_specific"] = 1.5

        active.is_active = False
        active.status = "archived"
        corrected = FrameworkVersion(
            version=next_version,
            name=CORRECTED_FRAMEWORK_NAME,
            description=(
                "System reliability correction: transition-based rates, stable breadth, "
                "bounded estimated GEX, calibrated state thresholds, and restored "
                "Gold-native category."
            ),
            spx_weights=dict(active.spx_weights or {}),
            nasdaq_weights=dict(active.nasdaq_weights or {}),
            gold_weights=gold_weights,
            regime_thresholds=dict(DEFAULT_THRESHOLDS),
            status="active",
            is_active=True,
            created_by="system_bias_reliability_migration",
            activated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(corrected)
        return next_version


def main() -> None:
    version = migrate()
    print(f"Corrected market-state framework ready at v{version}.")


if __name__ == "__main__":
    main()
