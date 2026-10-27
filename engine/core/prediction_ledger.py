"""Immutable prediction/explanation ledger and deterministic outcome maturation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import math
from typing import Callable, Iterable, Optional, Sequence

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.models import (
    FeatureSnapshot,
    ResearchModelSpec,
    ResearchModelVersion,
    ResearchOutcome,
    ResearchPrediction,
    ResearchPredictionFactor,
)


CALENDAR_RULE_VERSION = "us_market_close_v1"


class PredictionConflict(ValueError):
    pass


class InvalidPrediction(ValueError):
    pass


class MaturityUnavailable(ValueError):
    pass


class OutcomeConflict(ValueError):
    pass


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class FactorPayload:
    feature_name: str
    value: Optional[float]
    coefficient: Optional[float]
    contribution: Optional[float]
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PredictionPayload:
    asset: str
    horizon: str
    decision_at: datetime
    eligible_entry_at: datetime
    model_version_id: int
    feature_snapshot_id: int
    feature_snapshot_hash: str
    config_version: str
    evidence_score: Optional[float] = None
    point_forecast: Optional[float] = None
    raw_probability: Optional[float] = None
    calibrated_probability: Optional[float] = None
    confidence_grade: str = "research_only"
    status: str = "provisional"
    factors: tuple[FactorPayload, ...] = ()


def _finite_optional(value: Optional[float], field_name: str) -> None:
    if value is not None and not math.isfinite(float(value)):
        raise InvalidPrediction(f"{field_name} must be finite or null")


def append_prediction(session: Session, payload: PredictionPayload) -> ResearchPrediction:
    """Persist prediction and explanation atomically, idempotently by natural key."""
    if payload.asset not in {"SPX", "NASDAQ", "GOLD"}:
        raise InvalidPrediction("unsupported asset")
    if payload.horizon not in {"1W", "4W"}:
        raise InvalidPrediction("only 1W and 4W ledgers are registered")
    decision = _naive_utc(payload.decision_at)
    eligible = _naive_utc(payload.eligible_entry_at)
    if eligible < decision:
        raise InvalidPrediction("eligible_entry_at cannot precede decision_at")
    for name in ("evidence_score", "point_forecast", "raw_probability", "calibrated_probability"):
        _finite_optional(getattr(payload, name), name)
    for probability_name in ("raw_probability", "calibrated_probability"):
        probability = getattr(payload, probability_name)
        if probability is not None and not 0 <= probability <= 1:
            raise InvalidPrediction(f"{probability_name} must be in [0, 1]")
    factor_names = [factor.feature_name for factor in payload.factors]
    if len(factor_names) != len(set(factor_names)):
        raise InvalidPrediction("factor names must be unique")

    snapshot = session.get(FeatureSnapshot, payload.feature_snapshot_id)
    model_version = session.get(ResearchModelVersion, payload.model_version_id)
    if snapshot is None or model_version is None:
        raise InvalidPrediction("model version and feature snapshot must exist")
    model_spec = session.get(ResearchModelSpec, model_version.model_spec_id)
    if model_spec is None:
        raise InvalidPrediction("model specification must exist")
    if snapshot.snapshot_hash != payload.feature_snapshot_hash:
        raise InvalidPrediction("feature snapshot hash mismatch")
    if snapshot.asset != payload.asset or snapshot.horizon != payload.horizon:
        raise InvalidPrediction("snapshot asset/horizon mismatch")
    if snapshot.as_of != decision:
        raise InvalidPrediction("snapshot as_of must equal decision_at")
    if model_spec.horizon != payload.horizon:
        raise InvalidPrediction("model specification horizon mismatch")
    if model_spec.feature_set_version != snapshot.feature_set_version:
        raise InvalidPrediction("model and snapshot feature-set versions differ")
    if model_version.training_cutoff >= decision:
        raise InvalidPrediction("training cutoff must precede decision_at")

    existing = session.scalar(select(ResearchPrediction).where(
        ResearchPrediction.asset == payload.asset,
        ResearchPrediction.horizon == payload.horizon,
        ResearchPrediction.decision_at == decision,
        ResearchPrediction.model_version_id == payload.model_version_id,
    ))
    scalar_signature = {
        "eligible_entry_at": eligible,
        "feature_snapshot_id": payload.feature_snapshot_id,
        "feature_snapshot_hash": payload.feature_snapshot_hash,
        "config_version": payload.config_version,
        "evidence_score": payload.evidence_score,
        "point_forecast": payload.point_forecast,
        "raw_probability": payload.raw_probability,
        "calibrated_probability": payload.calibrated_probability,
        "confidence_grade": payload.confidence_grade,
        "status": payload.status,
    }
    if existing is not None:
        if any(getattr(existing, key) != value for key, value in scalar_signature.items()):
            raise PredictionConflict("prediction natural key already has different content")
        existing_factors = session.scalars(select(ResearchPredictionFactor).where(
            ResearchPredictionFactor.prediction_id == existing.id
        ).order_by(ResearchPredictionFactor.feature_name)).all()
        requested = sorted(payload.factors, key=lambda item: item.feature_name)
        actual = [
            (item.feature_name, item.value, item.coefficient, item.contribution, item.detail)
            for item in existing_factors
        ]
        expected = [
            (item.feature_name, item.value, item.coefficient, item.contribution, item.detail)
            for item in requested
        ]
        if actual != expected:
            raise PredictionConflict("stored explanation differs from requested explanation")
        return existing

    row = ResearchPrediction(
        asset=payload.asset,
        horizon=payload.horizon,
        decision_at=decision,
        model_version_id=payload.model_version_id,
        **scalar_signature,
    )
    session.add(row)
    session.flush()
    for factor in payload.factors:
        for name in ("value", "coefficient", "contribution"):
            _finite_optional(getattr(factor, name), f"factor.{name}")
        session.add(ResearchPredictionFactor(
            prediction_id=row.id,
            feature_name=factor.feature_name,
            value=factor.value,
            coefficient=factor.coefficient,
            contribution=factor.contribution,
            detail=factor.detail,
        ))
    session.flush()
    return row


@dataclass(frozen=True)
class OutcomeConvention:
    asset: str
    price_series: str
    calendar_rule_version: str = CALENDAR_RULE_VERSION
    max_exit_delay_days: int = 4


OUTCOME_CONVENTIONS = {
    "SPX": OutcomeConvention("SPX", "spx_close"),
    "NASDAQ": OutcomeConvention("NASDAQ", "ndx_close"),
    "GOLD": OutcomeConvention("GOLD", "gld_close"),
}


@dataclass(frozen=True)
class PriceBar:
    series_key: str
    observed_at: datetime
    fetched_at: datetime
    close: float
    high: Optional[float] = None
    low: Optional[float] = None
    source: str = "unknown"
    revision_possible: bool = False
    contract_identity: Optional[str] = None
    roll_adjustment_rule: Optional[str] = None

    def validated(self) -> "PriceBar":
        if self.close <= 0 or not math.isfinite(self.close):
            raise ValueError("close must be finite and positive")
        high = self.close if self.high is None else self.high
        low = self.close if self.low is None else self.low
        if not (math.isfinite(high) and math.isfinite(low) and high >= low > 0):
            raise ValueError("invalid high/low")
        if not (high >= self.close >= low):
            raise ValueError("close must lie inside high/low")
        if _naive_utc(self.fetched_at) < _naive_utc(self.observed_at):
            raise ValueError("fetched_at cannot precede observed_at")
        return self


@dataclass(frozen=True)
class OutcomePayload:
    matured_at: datetime
    entry_price: float
    exit_price: float
    actual_return: float
    excess_return: Optional[float]
    mfe: Optional[float]
    mae: Optional[float]
    direction_correct: Optional[bool]
    price_source: str
    calendar_rule_version: str
    price_observed_at: datetime
    price_fetched_at: datetime
    price_revision_possible: bool
    contract_identity: Optional[str]
    roll_adjustment_rule: Optional[str]
    provenance: dict


def append_outcome(
    session: Session,
    *,
    prediction_id: int,
    payload: OutcomePayload,
    correction_of_id: Optional[int] = None,
) -> ResearchOutcome:
    """Append an outcome or an explicit correction; never overwrite evidence."""
    prediction = session.get(ResearchPrediction, prediction_id)
    if prediction is None:
        raise OutcomeConflict("prediction does not exist")
    existing = session.scalars(select(ResearchOutcome).where(
        ResearchOutcome.prediction_id == prediction_id,
    ).order_by(desc(ResearchOutcome.outcome_version))).all()
    latest = existing[0] if existing else None
    signature = {
        "matured_at": _naive_utc(payload.matured_at),
        "entry_price": payload.entry_price,
        "exit_price": payload.exit_price,
        "actual_return": payload.actual_return,
        "excess_return": payload.excess_return,
        "mfe": payload.mfe,
        "mae": payload.mae,
        "direction_correct": payload.direction_correct,
        "price_source": payload.price_source,
        "calendar_rule_version": payload.calendar_rule_version,
        "price_observed_at": _naive_utc(payload.price_observed_at),
        "price_fetched_at": _naive_utc(payload.price_fetched_at),
        "price_revision_possible": payload.price_revision_possible,
        "contract_identity": payload.contract_identity,
        "roll_adjustment_rule": payload.roll_adjustment_rule,
        "provenance": payload.provenance,
    }
    if latest is not None and correction_of_id is None:
        if all(getattr(latest, key) == value for key, value in signature.items()):
            return latest
        raise OutcomeConflict("outcome exists; changed data requires correction_of_id")
    if correction_of_id is not None:
        correction = session.get(ResearchOutcome, correction_of_id)
        if correction is None or correction.prediction_id != prediction_id:
            raise OutcomeConflict("correction_of_id must reference this prediction")
        if latest is None or latest.id != correction_of_id:
            raise OutcomeConflict("correction must reference the latest outcome version")
    row = ResearchOutcome(
        prediction_id=prediction_id,
        outcome_version=1 if latest is None else latest.outcome_version + 1,
        correction_of_id=correction_of_id,
        **signature,
    )
    session.add(row)
    session.flush()
    return row


def _horizon_weeks(horizon: str) -> int:
    if horizon == "1W":
        return 1
    if horizon == "4W":
        return 4
    raise MaturityUnavailable(f"unsupported horizon: {horizon}")


def calculate_outcome(
    prediction: ResearchPrediction,
    bars: Sequence[PriceBar],
    *,
    worker_as_of: datetime,
    convention: Optional[OutcomeConvention] = None,
    benchmark_return: Optional[float] = None,
) -> OutcomePayload:
    """Pure deterministic maturity calculation over supplied valid-session bars."""
    rule = convention or OUTCOME_CONVENTIONS[prediction.asset]
    worker_time = _naive_utc(worker_as_of)
    if rule.asset != prediction.asset:
        raise MaturityUnavailable("outcome convention asset mismatch")
    validated = [bar.validated() for bar in bars]
    if any(bar.series_key != rule.price_series for bar in validated):
        raise MaturityUnavailable("mixed or incorrect price series")
    usable = sorted(
        (
            bar for bar in validated
            if _naive_utc(bar.fetched_at) <= worker_time
            and _naive_utc(bar.observed_at) <= worker_time
        ),
        key=lambda bar: _naive_utc(bar.observed_at),
    )
    decision = _naive_utc(prediction.decision_at)
    eligible = _naive_utc(prediction.eligible_entry_at)
    entry = next((
        bar for bar in usable
        if _naive_utc(bar.observed_at) > decision
        and _naive_utc(bar.observed_at) >= eligible
    ), None)
    if entry is None:
        raise MaturityUnavailable("no eligible post-decision entry close")
    target_date = _naive_utc(entry.observed_at).date() + timedelta(
        weeks=_horizon_weeks(prediction.horizon)
    )
    if worker_time.date() < target_date:
        raise MaturityUnavailable("horizon has not matured")
    latest_date = target_date + timedelta(days=rule.max_exit_delay_days)
    exit_bar = next((
        bar for bar in usable
        if target_date <= _naive_utc(bar.observed_at).date() <= latest_date
    ), None)
    if exit_bar is None:
        raise MaturityUnavailable("no exit close inside maximum delay")
    path = [
        bar for bar in usable
        if _naive_utc(entry.observed_at) <= _naive_utc(bar.observed_at)
        <= _naive_utc(exit_bar.observed_at)
    ]
    entry_price = float(entry.close)
    exit_price = float(exit_bar.close)
    actual_return = exit_price / entry_price - 1.0
    highs = [bar.high if bar.high is not None else bar.close for bar in path]
    lows = [bar.low if bar.low is not None else bar.close for bar in path]
    mfe = max(highs) / entry_price - 1.0 if highs else None
    mae = min(lows) / entry_price - 1.0 if lows else None
    direction_correct = None
    if prediction.point_forecast is not None and prediction.point_forecast != 0:
        direction_correct = (prediction.point_forecast > 0) == (actual_return > 0)
    sources = sorted({bar.source for bar in path})
    if len(sources) != 1:
        raise MaturityUnavailable("price provider changed inside one outcome path")
    contracts = sorted({bar.contract_identity for bar in path if bar.contract_identity})
    roll_rules = sorted({bar.roll_adjustment_rule for bar in path if bar.roll_adjustment_rule})
    return OutcomePayload(
        matured_at=_naive_utc(exit_bar.observed_at),
        entry_price=entry_price,
        exit_price=exit_price,
        actual_return=actual_return,
        excess_return=(actual_return - benchmark_return if benchmark_return is not None else None),
        mfe=mfe,
        mae=mae,
        direction_correct=direction_correct,
        price_source="+".join(sources),
        calendar_rule_version=rule.calendar_rule_version,
        price_observed_at=_naive_utc(exit_bar.observed_at),
        price_fetched_at=_naive_utc(exit_bar.fetched_at),
        price_revision_possible=any(bar.revision_possible for bar in path),
        contract_identity="+".join(contracts) if contracts else None,
        roll_adjustment_rule="+".join(roll_rules) if roll_rules else None,
        provenance={
            "price_series": rule.price_series,
            "entry_observed_at": _naive_utc(entry.observed_at).isoformat(),
            "exit_observed_at": _naive_utc(exit_bar.observed_at).isoformat(),
            "target_date": target_date.isoformat(),
            "max_exit_delay_days": rule.max_exit_delay_days,
            "path": [
                {
                    "observed_at": _naive_utc(bar.observed_at).isoformat(),
                    "fetched_at": _naive_utc(bar.fetched_at).isoformat(),
                    "close": bar.close,
                    "high": bar.high,
                    "low": bar.low,
                    "source": bar.source,
                }
                for bar in path
            ],
        },
    )


def mature_prediction(
    session: Session,
    *,
    prediction_id: int,
    bars: Sequence[PriceBar],
    worker_as_of: datetime,
    benchmark_return: Optional[float] = None,
    correction_of_id: Optional[int] = None,
) -> ResearchOutcome:
    prediction = session.get(ResearchPrediction, prediction_id)
    if prediction is None:
        raise MaturityUnavailable("prediction does not exist")
    payload = calculate_outcome(
        prediction, bars, worker_as_of=worker_as_of,
        benchmark_return=benchmark_return,
    )
    return append_outcome(
        session, prediction_id=prediction_id, payload=payload,
        correction_of_id=correction_of_id,
    )


@dataclass
class MaturityBatch:
    matured_ids: list[int] = field(default_factory=list)
    pending_prediction_ids: list[int] = field(default_factory=list)
    errors: dict[int, str] = field(default_factory=dict)


def mature_due_predictions(
    session: Session,
    *,
    worker_as_of: datetime,
    price_loader: Callable[[ResearchPrediction, OutcomeConvention], Sequence[PriceBar]],
) -> MaturityBatch:
    """Mature outstanding predictions independently; one asset failure cannot abort all."""
    existing_prediction_ids = select(ResearchOutcome.prediction_id)
    predictions = session.scalars(select(ResearchPrediction).where(
        ~ResearchPrediction.id.in_(existing_prediction_ids)
    ).order_by(ResearchPrediction.decision_at, ResearchPrediction.id)).all()
    batch = MaturityBatch()
    for prediction in predictions:
        try:
            convention = OUTCOME_CONVENTIONS[prediction.asset]
            bars = price_loader(prediction, convention)
            with session.begin_nested():
                outcome = mature_prediction(
                    session,
                    prediction_id=prediction.id,
                    bars=bars,
                    worker_as_of=worker_as_of,
                )
            batch.matured_ids.append(outcome.id)
        except MaturityUnavailable:
            batch.pending_prediction_ids.append(prediction.id)
        except Exception as exc:
            batch.errors[prediction.id] = f"{type(exc).__name__}: {exc}"
    return batch
