"""Frozen 4W walk-forward tournament, diagnostics, and evaluation persistence."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import math
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import (
    FeatureSnapshot,
    ResearchEvaluationRun,
    ResearchOutcome,
    ResearchPrediction,
)
from core.research_models import (
    EWRobustRidgeEstimator,
    ElasticNetAuditEstimator,
    Estimator,
    RobustRidgeEstimator,
)


TOURNAMENT_PROTOCOL_VERSION = "4w_tournament_v1"
BOOTSTRAP_SEED = 42
MINIMUM_OOS_BLOCKS = 40
COMPLEXITY_ORDER = (
    "static_robust",
    "ew_52w_robust",
    "ew_26w_robust",
    "elastic_net_audit",
)


@dataclass(frozen=True)
class Candidate:
    name: str
    complexity_rank: int
    factory: callable


CANDIDATES = (
    Candidate("static_robust", 1, lambda: RobustRidgeEstimator(8.0)),
    Candidate("ew_52w_robust", 2, lambda: EWRobustRidgeEstimator(52)),
    Candidate("ew_26w_robust", 3, lambda: EWRobustRidgeEstimator(26)),
    Candidate("elastic_net_audit", 4, ElasticNetAuditEstimator),
)


class LeakageDetected(ValueError):
    pass


@dataclass(frozen=True)
class ResearchDataset:
    features: pd.DataFrame
    target: pd.Series
    vintage_safe: pd.Series
    feature_available_at: Optional[pd.DataFrame] = None
    heuristic_benchmark: Optional[pd.Series] = None

    def validated(self, cutoff: Optional[pd.Timestamp] = None) -> "ResearchDataset":
        features = self.features.copy().sort_index()
        if not isinstance(features.index, pd.DatetimeIndex):
            raise ValueError("features must use a DatetimeIndex")
        if features.index.has_duplicates or not features.index.is_monotonic_increasing:
            raise ValueError("feature dates must be unique and sorted")
        if cutoff is not None:
            features = features.loc[:cutoff]
        target = self.target.reindex(features.index)
        safe = self.vintage_safe.reindex(features.index).fillna(False).astype(bool)
        if target.isna().any() or not np.isfinite(target.astype(float)).all():
            raise ValueError("target must be finite for every evaluation row")
        availability = None
        if self.feature_available_at is not None:
            availability = self.feature_available_at.reindex(
                index=features.index, columns=features.columns,
            )
            for column in features.columns:
                present = features[column].notna()
                if availability.loc[present, column].isna().any():
                    raise LeakageDetected(f"missing availability timestamp for {column}")
                available = pd.to_datetime(availability.loc[present, column])
                decisions = pd.Series(
                    features.index[present], index=available.index,
                )
                if (available.to_numpy() > decisions.to_numpy()).any():
                    raise LeakageDetected(f"future availability detected for {column}")
        heuristic = (
            self.heuristic_benchmark.reindex(features.index)
            if self.heuristic_benchmark is not None else None
        )
        return ResearchDataset(features, target, safe, availability, heuristic)


def load_immutable_research_dataset(
    session: Session,
    *,
    asset: str,
    horizon: str = "4W",
    feature_set_version: str = "pit_4w_v1",
    target_field: str = "excess_return",
) -> ResearchDataset:
    """Build one deduplicated frame only from immutable snapshot/outcome artifacts."""
    if target_field not in {"actual_return", "excess_return"}:
        raise ValueError("target_field must be actual_return or excess_return")
    latest_versions = select(
        ResearchOutcome.prediction_id,
        func.max(ResearchOutcome.outcome_version).label("latest_version"),
    ).group_by(ResearchOutcome.prediction_id).subquery()
    rows = session.execute(
        select(FeatureSnapshot, ResearchOutcome)
        .join(ResearchPrediction, ResearchPrediction.feature_snapshot_id == FeatureSnapshot.id)
        .join(ResearchOutcome, ResearchOutcome.prediction_id == ResearchPrediction.id)
        .join(
            latest_versions,
            (latest_versions.c.prediction_id == ResearchOutcome.prediction_id)
            & (latest_versions.c.latest_version == ResearchOutcome.outcome_version),
        )
        .where(
            FeatureSnapshot.asset == asset,
            FeatureSnapshot.horizon == horizon,
            FeatureSnapshot.feature_set_version == feature_set_version,
        )
        .order_by(FeatureSnapshot.as_of, FeatureSnapshot.id)
    ).all()
    by_decision: dict[datetime, tuple[FeatureSnapshot, ResearchOutcome]] = {}
    for snapshot, outcome in rows:
        target_value = getattr(outcome, target_field)
        if target_value is None:
            continue
        existing = by_decision.get(snapshot.as_of)
        if existing is not None:
            old_snapshot, old_outcome = existing
            if (
                old_snapshot.snapshot_hash != snapshot.snapshot_hash
                or getattr(old_outcome, target_field) != target_value
            ):
                raise ValueError("conflicting immutable artifacts for one decision date")
            continue
        by_decision[snapshot.as_of] = (snapshot, outcome)
    if not by_decision:
        empty_index = pd.DatetimeIndex([])
        return ResearchDataset(
            pd.DataFrame(index=empty_index), pd.Series(dtype=float, index=empty_index),
            pd.Series(dtype=bool, index=empty_index), pd.DataFrame(index=empty_index),
        )
    decisions = sorted(by_decision)
    feature_names = sorted({
        name for decision in decisions for name in by_decision[decision][0].values_json
    })
    features = pd.DataFrame([
        {name: by_decision[decision][0].values_json.get(name) for name in feature_names}
        for decision in decisions
    ], index=pd.DatetimeIndex(decisions))
    target = pd.Series([
        float(getattr(by_decision[decision][1], target_field)) for decision in decisions
    ], index=features.index)
    safe = pd.Series([
        bool(by_decision[decision][0].quality_json.get("_snapshot", {}).get(
            "promotion_eligible", False
        )) for decision in decisions
    ], index=features.index)
    availability_rows = []
    for decision in decisions:
        snapshot = by_decision[decision][0]
        row = {}
        for name in feature_names:
            timestamps = snapshot.availability_json.get(name, [])
            row[name] = max(pd.to_datetime(timestamps)) if timestamps else pd.NaT
        availability_rows.append(row)
    availability = pd.DataFrame(availability_rows, index=features.index)
    return ResearchDataset(features, target, safe, availability).validated()


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: int
    train_positions: tuple[int, ...]
    test_position: int
    train_start: str
    train_end: str
    test_date: str


def make_purged_folds(
    index: pd.DatetimeIndex,
    *,
    horizon_rows: int = 4,
    min_train_rows: int = 52,
    embargo_rows: int = 0,
) -> tuple[WalkForwardFold, ...]:
    """Create strict-purge, non-overlapping headline OOS folds."""
    if horizon_rows <= 0 or min_train_rows < 12 or embargo_rows < 0:
        raise ValueError("invalid fold configuration")
    folds: list[WalkForwardFold] = []
    first_test = min_train_rows + horizon_rows + embargo_rows
    for fold_id, test_pos in enumerate(range(first_test, len(index), horizon_rows), 1):
        # Strict inequality: a label ending at the test decision close is not yet known.
        train_end = test_pos - horizon_rows - embargo_rows - 1
        if train_end + 1 < min_train_rows:
            continue
        positions = tuple(range(train_end + 1))
        folds.append(WalkForwardFold(
            fold_id=fold_id,
            train_positions=positions,
            test_position=test_pos,
            train_start=index[0].isoformat(),
            train_end=index[train_end].isoformat(),
            test_date=index[test_pos].isoformat(),
        ))
    return tuple(folds)


def _manifest_hash(folds: tuple[WalkForwardFold, ...]) -> str:
    encoded = json.dumps(
        [asdict(fold) for fold in folds], sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _interval_score(actual: np.ndarray, lower: np.ndarray, upper: np.ndarray, alpha=0.20):
    return (upper - lower) + (2.0 / alpha) * (
        (lower - actual) * (actual < lower) + (actual - upper) * (actual > upper)
    )


def block_bootstrap_skill(
    loss_difference: np.ndarray,
    *,
    block_length: int = 4,
    draws: int = 2000,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Moving-date-block bootstrap of benchmark loss minus candidate loss."""
    values = np.asarray(loss_difference, dtype=float)
    if len(values) < 8:
        return {"mean": None, "lower_90": None, "upper_90": None, "draws": draws}
    block_length = min(block_length, len(values))
    starts = np.arange(len(values) - block_length + 1)
    blocks_needed = math.ceil(len(values) / block_length)
    rng = np.random.default_rng(seed)
    means = np.empty(draws)
    for draw in range(draws):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate([
            values[start:start + block_length] for start in chosen
        ])[:len(values)]
        means[draw] = sample.mean()
    low, high = np.quantile(means, [0.05, 0.95])
    # Four frozen candidates share the same OOS history. A Bonferroni one-sided
    # family bound controls the chance of selecting one lucky candidate.
    family_low = float(np.quantile(means, 0.10 / len(CANDIDATES)))
    return {
        "mean": float(values.mean()),
        "lower_90": float(low),
        "upper_90": float(high),
        "lower_familywise_90": family_low,
        "draws": draws,
        "block_length": block_length,
        "seed": seed,
    }


def _coefficient_turnover(
    coefficient_paths: list[dict[str, float]], residual_scales: list[float],
) -> float:
    if len(coefficient_paths) < 2:
        return 0.0
    changes = []
    for previous, current in zip(coefficient_paths, coefficient_paths[1:]):
        names = set(previous) | set(current)
        changes.append(float(np.mean([
            abs(current.get(name, 0.0) - previous.get(name, 0.0)) for name in names
        ])))
    normalizer = max(float(np.median(residual_scales)), 1e-8)
    return float(np.mean(changes) / normalizer)


def _evaluate_candidate(
    candidate: Candidate,
    dataset: ResearchDataset,
    folds: tuple[WalkForwardFold, ...],
    manifest_hash: str,
) -> dict:
    records: list[dict] = []
    coefficient_paths: list[dict[str, float]] = []
    residual_scales: list[float] = []
    for fold in folds:
        train_index = list(fold.train_positions)
        x_train = dataset.features.iloc[train_index]
        y_train = dataset.target.iloc[train_index]
        x_test = dataset.features.iloc[[fold.test_position]]
        estimator: Estimator = candidate.factory()
        artifact = estimator.fit(x_train, y_train)
        distribution = artifact.predict_distribution(x_test)[0]
        actual = float(dataset.target.iloc[fold.test_position])
        benchmark_point = float(y_train.mean())
        benchmark_probability = float(np.mean(y_train > 0))
        benchmark_low = float(benchmark_point + np.quantile(y_train - benchmark_point, 0.10))
        benchmark_high = float(benchmark_point + np.quantile(y_train - benchmark_point, 0.90))
        momentum_columns = [
            name for name in ("momentum_4w", "momentum_13w") if name in x_train
        ]
        momentum_point = benchmark_point
        if momentum_columns:
            momentum_artifact = RobustRidgeEstimator(6.0).fit(
                x_train[momentum_columns], y_train,
            )
            momentum_point = float(momentum_artifact.predict(x_test[momentum_columns])[0])
        heuristic_point = None
        if dataset.heuristic_benchmark is not None:
            value = dataset.heuristic_benchmark.iloc[fold.test_position]
            heuristic_point = float(value) if pd.notna(value) else None
        records.append({
            "fold_id": fold.fold_id,
            "date": fold.test_date,
            "actual": actual,
            "predicted": distribution.point,
            "lower_80": distribution.lower_80,
            "upper_80": distribution.upper_80,
            "raw_probability_up": distribution.probability_up,
            "benchmark_predicted": benchmark_point,
            "benchmark_probability_up": benchmark_probability,
            "benchmark_lower_80": benchmark_low,
            "benchmark_upper_80": benchmark_high,
            "zero_benchmark_predicted": 0.0,
            "momentum_benchmark_predicted": momentum_point,
            "heuristic_benchmark_predicted": heuristic_point,
            "effective_train_n": artifact.effective_n,
            "vintage_safe": bool(dataset.vintage_safe.iloc[fold.test_position]),
        })
        coefficient_paths.append({
            name: artifact.coefficients[position + 1]
            for position, name in enumerate(artifact.feature_names)
        })
        residual_scales.append(artifact.residual_scale)

    if not records:
        return {
            "candidate": candidate.name,
            "complexity_rank": candidate.complexity_rank,
            "fold_manifest_hash": manifest_hash,
            "n_oos": 0,
            "records": [],
            "checks": {"minimum_oos": False},
            "statistically_eligible": False,
        }
    actual = np.asarray([row["actual"] for row in records])
    predicted = np.asarray([row["predicted"] for row in records])
    lower = np.asarray([row["lower_80"] for row in records])
    upper = np.asarray([row["upper_80"] for row in records])
    probability = np.clip(np.asarray([row["raw_probability_up"] for row in records]), 1e-6, 1 - 1e-6)
    benchmark = np.asarray([row["benchmark_predicted"] for row in records])
    benchmark_probability = np.clip(np.asarray([
        row["benchmark_probability_up"] for row in records
    ]), 1e-6, 1 - 1e-6)
    benchmark_lower = np.asarray([row["benchmark_lower_80"] for row in records])
    benchmark_upper = np.asarray([row["benchmark_upper_80"] for row in records])
    outcomes = (actual > 0).astype(float)
    model_loss = np.abs(actual - predicted)
    benchmark_loss = np.abs(actual - benchmark)
    bootstrap = block_bootstrap_skill(benchmark_loss - model_loss)
    brier = float(np.mean((probability - outcomes) ** 2))
    benchmark_brier = float(np.mean((benchmark_probability - outcomes) ** 2))
    interval = float(np.mean(_interval_score(actual, lower, upper)))
    benchmark_interval = float(np.mean(_interval_score(
        actual, benchmark_lower, benchmark_upper,
    )))
    turnover = _coefficient_turnover(coefficient_paths, residual_scales)
    zero_loss = np.abs(actual)
    momentum_loss = np.abs(actual - np.asarray([
        row["momentum_benchmark_predicted"] for row in records
    ]))
    heuristic_values = [row["heuristic_benchmark_predicted"] for row in records]
    heuristic_mae = (
        float(np.mean([
            abs(actual[index] - value)
            for index, value in enumerate(heuristic_values) if value is not None
        ])) if any(value is not None for value in heuristic_values) else None
    )
    minimum_effective_n = float(min(row["effective_train_n"] for row in records))
    safe_predictions = bool(
        np.isfinite(predicted).all()
        and np.max(np.abs(predicted)) <= max(8.0 * float(np.std(actual, ddof=1)), 0.25)
    )
    vintage_safe = all(row["vintage_safe"] for row in records)
    checks = {
        "minimum_oos": len(records) >= MINIMUM_OOS_BLOCKS,
        "primary_mae_improvement": float(model_loss.mean()) < float(benchmark_loss.mean()),
        "bootstrap_lower_above_zero": (
            bootstrap.get("lower_familywise_90") is not None
            and bootstrap["lower_familywise_90"] > 0
        ),
        "brier_noninferiority": brier <= benchmark_brier + 0.02,
        "interval_noninferiority": interval <= benchmark_interval * 1.10,
        "coefficient_turnover": turnover <= 0.75,
        "minimum_effective_train_n": minimum_effective_n >= 32,
        "prediction_safety": safe_predictions,
        "vintage_safe_oos": vintage_safe,
    }
    return {
        "candidate": candidate.name,
        "complexity_rank": candidate.complexity_rank,
        "fold_manifest_hash": manifest_hash,
        "n_oos": len(records),
        "mae": float(model_loss.mean()),
        "benchmark_mae": float(benchmark_loss.mean()),
        "brier": brier,
        "benchmark_brier": benchmark_brier,
        "interval_score_80": interval,
        "benchmark_interval_score_80": benchmark_interval,
        "directional_accuracy": float(np.mean(np.sign(predicted) == np.sign(actual))),
        "coverage_80": float(np.mean((actual >= lower) & (actual <= upper))),
        "coefficient_turnover": turnover,
        "minimum_effective_train_n": minimum_effective_n,
        "benchmark_comparison": {
            "primary": "expanding_mean",
            "expanding_mean_mae": float(benchmark_loss.mean()),
            "zero_mae": float(zero_loss.mean()),
            "momentum_only_mae": float(momentum_loss.mean()),
            "production_heuristic_mae": heuristic_mae,
        },
        "bootstrap": bootstrap,
        "checks": checks,
        "statistically_eligible": all(checks.values()),
        "records": records,
    }


def _pareto_frontier(results: dict[str, dict]) -> list[str]:
    eligible = {
        name: result for name, result in results.items()
        if result.get("mae") is not None
    }
    frontier = []
    for name, result in eligible.items():
        vector = (
            result["mae"], result["brier"], result["interval_score_80"],
            result["coefficient_turnover"],
        )
        dominated = False
        for other_name, other in eligible.items():
            if other_name == name:
                continue
            other_vector = (
                other["mae"], other["brier"], other["interval_score_80"],
                other["coefficient_turnover"],
            )
            if all(a <= b for a, b in zip(other_vector, vector)) and any(
                a < b for a, b in zip(other_vector, vector)
            ):
                dominated = True
                break
        if not dominated:
            frontier.append(name)
    return sorted(frontier, key=lambda name: COMPLEXITY_ORDER.index(name))


def run_frozen_4w_tournament(
    dataset: ResearchDataset,
    *,
    cutoff: Optional[pd.Timestamp] = None,
    min_train_rows: int = 52,
    embargo_rows: int = 0,
) -> dict:
    """Run the pre-registered hierarchy; never create a promotion event."""
    validated = dataset.validated(cutoff)
    folds = make_purged_folds(
        validated.features.index,
        horizon_rows=4,
        min_train_rows=min_train_rows,
        embargo_rows=embargo_rows,
    )
    manifest_hash = _manifest_hash(folds)
    results = {
        candidate.name: _evaluate_candidate(candidate, validated, folds, manifest_hash)
        for candidate in CANDIDATES
    }
    passing = [name for name in COMPLEXITY_ORDER if results[name]["statistically_eligible"]]
    recommended = passing[0] if passing else None
    return {
        "protocol_version": TOURNAMENT_PROTOCOL_VERSION,
        "cutoff": validated.features.index[-1].isoformat() if len(validated.features) else None,
        "complexity_order": list(COMPLEXITY_ORDER),
        "fold_manifest": [asdict(fold) for fold in folds],
        "fold_manifest_hash": manifest_hash,
        "candidate_results": results,
        "pareto_frontier_diagnostic": _pareto_frontier(results),
        "statistically_recommended_candidate": recommended,
        "promotion_status": "human_approval_required" if recommended else "no_candidate_passed",
        "automatic_promotion": False,
    }


def persist_evaluation_run(
    session: Session,
    *,
    tournament: dict,
    candidate_name: str,
    candidate_model_version_id: int,
    champion_model_version_id: Optional[int] = None,
) -> ResearchEvaluationRun:
    """Persist one candidate's frozen evaluation artifact idempotently by hash."""
    result = tournament["candidate_results"][candidate_name]
    payload = {
        "protocol_version": tournament["protocol_version"],
        "candidate": candidate_name,
        "candidate_model_version_id": candidate_model_version_id,
        "champion_model_version_id": champion_model_version_id,
        "cutoff": tournament["cutoff"],
        "fold_manifest_hash": tournament["fold_manifest_hash"],
        "result": result,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    artifact_hash = hashlib.sha256(encoded).hexdigest()
    existing = session.query(ResearchEvaluationRun).filter_by(
        artifact_hash=artifact_hash
    ).one_or_none()
    if existing is not None:
        return existing
    row = ResearchEvaluationRun(
        protocol_version=tournament["protocol_version"],
        candidate_model_version_id=candidate_model_version_id,
        champion_model_version_id=champion_model_version_id,
        cutoff=datetime.fromisoformat(tournament["cutoff"]),
        prediction_outcome_manifest=result["records"],
        metrics={key: value for key, value in result.items() if key not in {"records", "bootstrap"}},
        bootstrap_results=result.get("bootstrap", {}),
        status="statistically_eligible" if result["statistically_eligible"] else "research_only",
        artifact_hash=artifact_hash,
    )
    session.add(row)
    session.flush()
    return row
