"""Auditable estimator boundary for the frozen 4W research tournament.

Estimators know how to fit, predict, explain, and serialize. They do not know about
walk-forward folds, benchmarks, promotion, persistence, or UI status.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import math
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PredictionDistribution:
    point: float
    probability_up: float
    lower_80: float
    upper_80: float


@dataclass(frozen=True)
class FittedLinearArtifact:
    estimator_name: str
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    medians: tuple[float, ...]
    scales: tuple[float, ...]
    residual_scale: float
    residual_q10: float
    residual_q90: float
    effective_n: float
    config: dict[str, Any]

    @property
    def intercept(self) -> float:
        return self.coefficients[0]

    def _standardize(self, frame: pd.DataFrame) -> np.ndarray:
        values = frame.reindex(columns=self.feature_names).astype(float)
        medians = pd.Series(self.medians, index=self.feature_names)
        scales = pd.Series(self.scales, index=self.feature_names)
        return ((values.fillna(medians) - medians) / scales).clip(-5.0, 5.0).to_numpy()

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        z = self._standardize(frame)
        return self.intercept + z @ np.asarray(self.coefficients[1:])

    def predict_distribution(self, frame: pd.DataFrame) -> list[PredictionDistribution]:
        points = self.predict(frame)
        scale = max(self.residual_scale, 1e-8)
        return [
            PredictionDistribution(
                point=float(point),
                probability_up=float(0.5 * (1.0 + math.erf(point / (scale * math.sqrt(2.0))))),
                lower_80=float(point + self.residual_q10),
                upper_80=float(point + self.residual_q90),
            )
            for point in points
        ]

    def explain(self, row: pd.Series) -> list[dict[str, float | str | bool | None]]:
        raw = row.reindex(self.feature_names).astype(float)
        medians = pd.Series(self.medians, index=self.feature_names)
        scales = pd.Series(self.scales, index=self.feature_names)
        imputed = raw.isna()
        z = ((raw.fillna(medians) - medians) / scales).clip(-5.0, 5.0)
        output = [
            {
                "feature_name": name,
                "value": None if pd.isna(raw[name]) else float(raw[name]),
                "coefficient": float(self.coefficients[index + 1]),
                "contribution": float(self.coefficients[index + 1] * z[name]),
                "imputed": bool(imputed[name]),
            }
            for index, name in enumerate(self.feature_names)
        ]
        output.sort(key=lambda item: abs(float(item["contribution"])), reverse=True)
        return output

    def serialize(self) -> bytes:
        payload = {
            "schema_version": 1,
            "estimator_name": self.estimator_name,
            "feature_names": list(self.feature_names),
            "coefficients": list(self.coefficients),
            "medians": list(self.medians),
            "scales": list(self.scales),
            "residual_scale": self.residual_scale,
            "residual_q10": self.residual_q10,
            "residual_q90": self.residual_q90,
            "effective_n": self.effective_n,
            "config": self.config,
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")

    @classmethod
    def load(cls, encoded: bytes) -> "FittedLinearArtifact":
        payload = json.loads(encoded.decode("utf-8"))
        if payload.pop("schema_version", None) != 1:
            raise ValueError("unsupported artifact schema")
        for key in ("feature_names", "coefficients", "medians", "scales"):
            payload[key] = tuple(payload[key])
        return cls(**payload)


class Estimator(ABC):
    name: str

    @abstractmethod
    def fit(self, features: pd.DataFrame, target: pd.Series) -> FittedLinearArtifact:
        raise NotImplementedError


def _prepare(features: pd.DataFrame, target: pd.Series):
    if len(features) != len(target) or len(features) < 12:
        raise ValueError("features and target need at least 12 aligned rows")
    if features.columns.duplicated().any():
        raise ValueError("duplicate feature names")
    y = target.astype(float).to_numpy()
    if not np.isfinite(y).all():
        raise ValueError("target must be finite")
    x = features.astype(float).replace([np.inf, -np.inf], np.nan)
    usable = [
        name for name in x.columns
        if x[name].notna().mean() >= 0.80 and x[name].nunique(dropna=True) >= 4
    ]
    if not usable:
        raise ValueError("no sufficiently complete non-constant features")
    x = x[usable]
    medians = x.median()
    filled = x.fillna(medians)
    mad = (filled - medians).abs().median() * 1.4826
    scales = mad.where(mad > 1e-8, filled.std(ddof=1)).fillna(1.0)
    scales = scales.where(scales > 1e-8, 1.0)
    z = ((filled - medians) / scales).clip(-5.0, 5.0).to_numpy()
    return usable, medians, scales, z, y


def _robust_scale(residual: np.ndarray) -> float:
    median = np.median(residual)
    scale = 1.4826 * np.median(np.abs(residual - median))
    return max(float(scale), float(np.std(residual, ddof=1)) * 0.25, 1e-8)


def _ridge_irls(
    design: np.ndarray,
    y: np.ndarray,
    base_weights: np.ndarray,
    prior_precision: float,
    prior_center: Optional[np.ndarray] = None,
) -> tuple[np.ndarray, np.ndarray]:
    penalty = np.eye(design.shape[1]) * prior_precision
    penalty[0, 0] = 1e-8
    center = np.zeros(design.shape[1]) if prior_center is None else prior_center.copy()
    beta = np.linalg.solve(
        (design.T * base_weights) @ design + penalty,
        (design.T * base_weights) @ y + penalty @ center,
    )
    weights = base_weights.copy()
    for _ in range(30):
        residual = y - design @ beta
        scale = _robust_scale(residual)
        student_weights = 6.0 / (5.0 + (residual / scale) ** 2)
        weights = base_weights * student_weights
        updated = np.linalg.solve(
            (design.T * weights) @ design + penalty,
            (design.T * weights) @ y + penalty @ center,
        )
        if np.max(np.abs(updated - beta)) < 1e-9:
            beta = updated
            break
        beta = updated
    return beta, weights


def _artifact(
    *,
    name: str,
    names: list[str],
    medians: pd.Series,
    scales: pd.Series,
    beta: np.ndarray,
    y: np.ndarray,
    design: np.ndarray,
    weights: np.ndarray,
    config: dict,
) -> FittedLinearArtifact:
    residual = y - design @ beta
    residual_scale = _robust_scale(residual)
    return FittedLinearArtifact(
        estimator_name=name,
        feature_names=tuple(names),
        coefficients=tuple(float(value) for value in beta),
        medians=tuple(float(medians[name]) for name in names),
        scales=tuple(float(scales[name]) for name in names),
        residual_scale=residual_scale,
        residual_q10=float(np.quantile(residual, 0.10)),
        residual_q90=float(np.quantile(residual, 0.90)),
        effective_n=float((weights.sum() ** 2) / max(np.square(weights).sum(), 1e-12)),
        config=config,
    )


class RobustRidgeEstimator(Estimator):
    def __init__(self, prior_precision: float = 8.0):
        self.prior_precision = float(prior_precision)
        self.name = "static_robust_ridge"

    def fit(self, features: pd.DataFrame, target: pd.Series) -> FittedLinearArtifact:
        names, medians, scales, z, y = _prepare(features, target)
        design = np.column_stack([np.ones(len(z)), z])
        weights = np.ones(len(y))
        beta, final_weights = _ridge_irls(
            design, y, weights, self.prior_precision,
        )
        return _artifact(
            name=self.name, names=names, medians=medians, scales=scales,
            beta=beta, y=y, design=design, weights=final_weights,
            config={"prior_precision": self.prior_precision},
        )


class EWRobustRidgeEstimator(Estimator):
    """Fixed half-life challenger shrunk toward the full-history robust fit."""

    def __init__(self, half_life_weeks: int, prior_precision: float = 12.0, movement_cap: float = 1.5):
        if half_life_weeks not in {26, 52}:
            raise ValueError("V1 half-life must be pre-registered as 26 or 52 weeks")
        self.half_life_weeks = half_life_weeks
        self.prior_precision = float(prior_precision)
        self.movement_cap = float(movement_cap)
        self.name = f"ew_{half_life_weeks}w_robust_ridge"

    def fit(self, features: pd.DataFrame, target: pd.Series) -> FittedLinearArtifact:
        names, medians, scales, z, y = _prepare(features, target)
        design = np.column_stack([np.ones(len(z)), z])
        baseline, _ = _ridge_irls(design, y, np.ones(len(y)), 8.0)
        age = np.arange(len(y) - 1, -1, -1, dtype=float)
        ew = np.power(0.5, age / self.half_life_weeks)
        beta, final_weights = _ridge_irls(
            design, y, ew, self.prior_precision, prior_center=baseline,
        )
        # Cap standardized coefficient movement relative to the stable baseline.
        beta[1:] = baseline[1:] + np.clip(
            beta[1:] - baseline[1:], -self.movement_cap, self.movement_cap,
        )
        return _artifact(
            name=self.name, names=names, medians=medians, scales=scales,
            beta=beta, y=y, design=design, weights=final_weights,
            config={
                "half_life_weeks": self.half_life_weeks,
                "prior_precision": self.prior_precision,
                "movement_cap": self.movement_cap,
                "baseline": "static_robust_ridge",
            },
        )


def _soft_threshold(value: float, threshold: float) -> float:
    return math.copysign(max(abs(value) - threshold, 0.0), value)


class ElasticNetAuditEstimator(Estimator):
    """One frozen Elastic Net challenger; no OOS hyperparameter search."""

    def __init__(self, l1_ratio: float = 0.35, penalty_scale: float = 0.05):
        if l1_ratio != 0.35 or penalty_scale != 0.05:
            raise ValueError("V1 Elastic Net configuration is frozen")
        self.l1_ratio = l1_ratio
        self.penalty_scale = penalty_scale
        self.name = "elastic_net_audit_l1_0.35"

    def fit(self, features: pd.DataFrame, target: pd.Series) -> FittedLinearArtifact:
        names, medians, scales, z, y = _prepare(features, target)
        intercept = float(np.mean(y))
        centered = y - intercept
        beta_features = np.zeros(z.shape[1])
        fitted = np.zeros(len(y))
        lam = len(y) * max(float(np.std(centered, ddof=1)), 1e-6) * self.penalty_scale
        for _ in range(500):
            previous = beta_features.copy()
            for column in range(z.shape[1]):
                without = fitted - z[:, column] * beta_features[column]
                numerator = float(z[:, column] @ (centered - without))
                denominator = float(
                    z[:, column] @ z[:, column] + lam * (1.0 - self.l1_ratio)
                )
                beta_features[column] = _soft_threshold(
                    numerator, lam * self.l1_ratio,
                ) / max(denominator, 1e-12)
                fitted = without + z[:, column] * beta_features[column]
            if np.max(np.abs(beta_features - previous)) < 1e-9:
                break
        beta = np.r_[intercept, beta_features]
        design = np.column_stack([np.ones(len(z)), z])
        return _artifact(
            name=self.name, names=names, medians=medians, scales=scales,
            beta=beta, y=y, design=design, weights=np.ones(len(y)),
            config={"l1_ratio": self.l1_ratio, "penalty_scale": self.penalty_scale},
        )
