"""Versioned 4W feature construction from point-in-time observation vintages."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import FeatureDefinition, FeatureSnapshot
from core.pit_data import PROMOTION_SAFE_VINTAGE_SOURCES, PITValue, point_in_time_value
from core.research_store import FeatureSnapshotPayload, append_feature_snapshot


FEATURE_SET_VERSION_4W = "pit_4w_v1"

PRICE_SERIES = {
    "SPX": "spx_close",
    "NASDAQ": "ndx_close",
    # GLD avoids silent front-month futures roll effects in the first outcome/model spec.
    "GOLD": "gld_close",
}
COT_SERIES = {
    "SPX": ("cot_spx_net_leveraged", "cot_spx_open_interest"),
    "NASDAQ": ("cot_nasdaq_net_leveraged", "cot_nasdaq_open_interest"),
    "GOLD": ("cot_gold_net_noncommercial", "cot_gold_open_interest"),
}


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    formula_ref: str
    lookback_weeks: int
    eligibility_policy: dict


FEATURE_SPECS_4W: tuple[FeatureSpec, ...] = (
    FeatureSpec("real_yield_4w_bp", "delta(us_10y_real_yield,4w)*100", 4, {"missing": "block"}),
    FeatureSpec("breakeven_4w_bp", "delta(us_10y_yield-us_10y_real_yield,4w)*100", 4, {"missing": "block"}),
    FeatureSpec("dxy_4w_log", "log(dxy/dxy_lag_4w)", 4, {"positive_only": True, "missing": "block"}),
    FeatureSpec("hy_oas_4w_bp", "delta(hy_oas,4w)*100", 4, {"missing": "block"}),
    FeatureSpec("vix_curve_log", "log(vix3m/vix)", 0, {"positive_only": True, "missing": "block"}),
    FeatureSpec("cot_net_oi_4w", "delta(cot_net/cot_open_interest,4w)", 4, {"nonzero_denominator": True, "missing": "block"}),
    FeatureSpec("momentum_4w", "log(asset_price/asset_price_lag_4w)", 4, {"positive_only": True, "missing": "block"}),
    FeatureSpec("momentum_13w", "log(asset_price/asset_price_lag_13w)", 13, {"positive_only": True, "missing": "block"}),
)


class FeatureDefinitionConflict(ValueError):
    pass


def sync_feature_definitions(
    session: Session,
    specs: tuple[FeatureSpec, ...] = FEATURE_SPECS_4W,
    feature_set_version: str = FEATURE_SET_VERSION_4W,
) -> list[FeatureDefinition]:
    """Insert immutable formula contracts idempotently."""
    rows: list[FeatureDefinition] = []
    for spec in specs:
        existing = session.scalar(select(FeatureDefinition).where(
            FeatureDefinition.feature_set_version == feature_set_version,
            FeatureDefinition.name == spec.name,
        ))
        signature = {
            "formula_ref": spec.formula_ref,
            "lookback_periods": spec.lookback_weeks,
            "eligibility_policy": spec.eligibility_policy,
        }
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in signature.items()):
                raise FeatureDefinitionConflict(
                    f"{feature_set_version}/{spec.name} already has another formula"
                )
            rows.append(existing)
            continue
        row = FeatureDefinition(
            feature_set_version=feature_set_version,
            name=spec.name,
            **signature,
        )
        session.add(row)
        session.flush()
        rows.append(row)
    return rows


class _Resolver:
    def __init__(self, session: Session, as_of: datetime):
        self.session = session
        self.as_of = as_of
        self.cache: dict[tuple[str, int], Optional[PITValue]] = {}

    def get(self, series_key: str, lag_weeks: int = 0) -> Optional[PITValue]:
        key = (series_key, lag_weeks)
        if key not in self.cache:
            cutoff = self.as_of - timedelta(weeks=lag_weeks)
            self.cache[key] = point_in_time_value(
                self.session,
                series_key,
                self.as_of,
                observed_at_or_before=cutoff,
            )
        return self.cache[key]


def _number(value: Optional[PITValue]) -> Optional[float]:
    if value is None or value.value is None:
        return None
    number = float(value.value)
    return number if math.isfinite(number) else None


def _delta(resolver: _Resolver, key: str, weeks: int, scale: float = 1.0) -> tuple[Optional[float], list[PITValue]]:
    current, lagged = resolver.get(key), resolver.get(key, weeks)
    a, b = _number(current), _number(lagged)
    used = [item for item in (current, lagged) if item is not None]
    return ((a - b) * scale if a is not None and b is not None else None), used


def _log_change(resolver: _Resolver, key: str, weeks: int) -> tuple[Optional[float], list[PITValue]]:
    current, lagged = resolver.get(key), resolver.get(key, weeks)
    a, b = _number(current), _number(lagged)
    used = [item for item in (current, lagged) if item is not None]
    value = math.log(a / b) if a is not None and b is not None and a > 0 and b > 0 else None
    return value, used


def _quality(used: list[PITValue], value: Optional[float]) -> dict:
    reasons = sorted({reason for item in used for reason in item.eligibility_reasons})
    if value is None:
        reasons.append("missing_or_invalid_input")
    return {
        "missing": value is None,
        "stale_inputs": sorted({item.series_key for item in used if item.stale}),
        "promotion_eligible": value is not None and not reasons,
        "reasons": sorted(set(reasons)),
    }


def _lineage(used: list[PITValue]) -> dict:
    return {
        "series_keys": [item.series_key for item in used],
        "observation_vintage_ids": [item.observation_vintage_id for item in used],
        "definition_versions": {
            item.series_key: item.definition_version for item in used
        },
        "available_at": [item.available_at.isoformat() for item in used],
        "vintage_sources": [item.vintage_source for item in used],
    }


def build_4w_feature_snapshot(
    session: Session,
    *,
    asset: str,
    as_of: datetime,
    feature_set_version: str = FEATURE_SET_VERSION_4W,
) -> FeatureSnapshot:
    """Build and append one reproducible 4W feature vector for an asset/as-of."""
    if asset not in PRICE_SERIES:
        raise ValueError(f"unsupported asset: {asset}")
    if feature_set_version != FEATURE_SET_VERSION_4W:
        raise ValueError("unknown feature_set_version; register formulas before use")
    sync_feature_definitions(session, feature_set_version=feature_set_version)
    resolver = _Resolver(session, as_of)
    computed: dict[str, tuple[Optional[float], list[PITValue]]] = {}

    computed["real_yield_4w_bp"] = _delta(resolver, "us_10y_real_yield", 4, 100.0)
    real_now, real_lag = resolver.get("us_10y_real_yield"), resolver.get("us_10y_real_yield", 4)
    nominal_now, nominal_lag = resolver.get("us_10y_yield"), resolver.get("us_10y_yield", 4)
    rn, rl, nn, nl = map(_number, (real_now, real_lag, nominal_now, nominal_lag))
    breakeven = ((nn - rn) - (nl - rl)) * 100.0 if None not in (rn, rl, nn, nl) else None
    computed["breakeven_4w_bp"] = (
        breakeven, [item for item in (real_now, real_lag, nominal_now, nominal_lag) if item]
    )
    computed["dxy_4w_log"] = _log_change(resolver, "dxy", 4)
    computed["hy_oas_4w_bp"] = _delta(resolver, "hy_oas", 4, 100.0)

    vix, vix3m = resolver.get("vix"), resolver.get("vix3m")
    vix_n, vix3m_n = _number(vix), _number(vix3m)
    curve = (
        math.log(vix3m_n / vix_n)
        if vix_n is not None and vix3m_n is not None and vix_n > 0 and vix3m_n > 0
        else None
    )
    computed["vix_curve_log"] = (curve, [item for item in (vix, vix3m) if item])

    cot_net, cot_oi = COT_SERIES[asset]
    net_now, net_lag = resolver.get(cot_net), resolver.get(cot_net, 4)
    oi_now, oi_lag = resolver.get(cot_oi), resolver.get(cot_oi, 4)
    n0, n4, o0, o4 = map(_number, (net_now, net_lag, oi_now, oi_lag))
    cot_change = (
        n0 / o0 - n4 / o4
        if None not in (n0, n4, o0, o4) and o0 != 0 and o4 != 0 else None
    )
    computed["cot_net_oi_4w"] = (
        cot_change, [item for item in (net_now, net_lag, oi_now, oi_lag) if item]
    )

    price_key = PRICE_SERIES[asset]
    computed["momentum_4w"] = _log_change(resolver, price_key, 4)
    computed["momentum_13w"] = _log_change(resolver, price_key, 13)

    values = {name: value for name, (value, _used) in computed.items()}
    quality = {name: _quality(used, value) for name, (value, used) in computed.items()}
    lineage = {name: _lineage(used) for name, (_value, used) in computed.items()}
    availability = {
        name: lineage[name]["available_at"] for name in computed
    }
    all_sources = sorted({
        source
        for feature_lineage in lineage.values()
        for source in feature_lineage["vintage_sources"]
    })
    if not all_sources:
        snapshot_source = "unknown"
    elif len(all_sources) == 1:
        snapshot_source = all_sources[0]
    elif all(source in PROMOTION_SAFE_VINTAGE_SOURCES for source in all_sources):
        snapshot_source = "mixed_safe"
    else:
        snapshot_source = "mixed_unsafe"
    quality["_snapshot"] = {
        "promotion_eligible": all(
            item["promotion_eligible"] for name, item in quality.items() if name != "_snapshot"
        ),
        "missing_features": sorted(
            name for name, item in quality.items()
            if name != "_snapshot" and item["missing"]
        ),
    }
    return append_feature_snapshot(session, FeatureSnapshotPayload(
        feature_set_version=feature_set_version,
        asset=asset,
        horizon="4W",
        as_of=as_of,
        values=values,
        availability=availability,
        quality=quality,
        lineage=lineage,
        vintage_source=snapshot_source,
    ))
