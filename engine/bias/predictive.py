"""Unified, auditable probabilistic bias model.

The production heuristic remains untouched until this model passes its
expanding-window acceptance tests.  Inputs are changes or stationary ratios;
rate and USD moves are split into rising/falling branches so the data can learn
asymmetric effects rather than imposing a sign.

Model family: regularized robust regression with MAP estimation and
Laplace-approximate posterior (Student-t IRLS + L2 ridge prior).
This is NOT full Bayesian inference; it does not marginalise over σ² or
model structure. Uncertainty is a Laplace approximation at the MAP point.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
import logging
from typing import Optional
import uuid

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, t as student_t
from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from bias.engine import ALL_INDICATORS
from bias.regimes import classify_regime
from core.config import settings
from core.database import engine as db_engine, get_session
from core.models import BiasResult, PredictiveBiasResult, PredictiveModelRunLease
from ingestion.pipeline import load_all_series

logger = logging.getLogger(__name__)

MODEL_VERSION = "forecast_tournament_v2"
ASSETS = ("SPX", "NASDAQ", "GOLD")
# LOW-1: named constant so the seed is never silently changed
_BOOTSTRAP_SEED: int = 42

PRICE_KEYS = {
    "SPX": ("spx_close", "spy_close"),
    "NASDAQ": ("ndx_close", "nasdaq_close", "qqq_close"),
    "GOLD": ("gold_futures", "gld_close"),
}
COT_KEYS = {
    "SPX": ("cot_spx_net_leveraged", "cot_spx_open_interest"),
    "NASDAQ": ("cot_nasdaq_net_leveraged", "cot_nasdaq_open_interest"),
    "GOLD": ("cot_gold_net_noncommercial", "cot_gold_open_interest"),
}
ASYMMETRIC = {"real_yield_4w_bp", "dxy_4w_log", "hy_oas_4w_bp"}

# These sets are fixed ex ante.  They deliberately express economic channels
# instead of letting a 154-row sample search through arbitrary subsets.
REDUCED_FEATURES = (
    "real_yield_4w_bp",
    "breakeven_4w_bp",
    "dxy_4w_log",
    "hy_oas_4w_bp",
    "vix_curve_log",
    "breadth_200ma_4w",
    "cot_net_oi_4w",
    "momentum_4w",
    "momentum_13w",
)
MOMENTUM_FEATURES = ("momentum_4w", "momentum_13w")


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    estimator: str
    feature_names: Optional[tuple[str, ...]] = None
    prior_precision: float = 6.0


CANDIDATES = (
    CandidateSpec("robust_reduced", "robust", REDUCED_FEATURES, 8.0),
    CandidateSpec("elastic_net_reduced", "elastic_net", REDUCED_FEATURES),
    CandidateSpec("robust_full", "robust", None, 10.0),
    CandidateSpec("momentum_only", "robust", MOMENTUM_FEATURES, 6.0),
)


@dataclass(frozen=True)
class SeriesPolicy:
    max_ffill_weeks: int = 0
    publication_lag_weeks: int = 0
    vintage_safe_for_backtest: bool = True


# Availability is series-specific. Market prices must not be silently carried
# through missing weeks; COT can survive one missed weekly release; current-
# vintage macro series remain promotion-blocking until vintage data is stored.
SERIES_POLICIES: dict[str, SeriesPolicy] = {
    **{key: SeriesPolicy() for keys in PRICE_KEYS.values() for key in keys},
    "us_10y_real_yield": SeriesPolicy(),
    "us_10y_yield": SeriesPolicy(),
    "us_2y_yield": SeriesPolicy(),
    "dxy": SeriesPolicy(),
    "hy_oas": SeriesPolicy(),
    "vix": SeriesPolicy(),
    "vix3m": SeriesPolicy(),
    "mcclellan_oscillator": SeriesPolicy(),
    "pct_above_200ma": SeriesPolicy(),
    "fed_balance_sheet": SeriesPolicy(1, 0, False),
    "tga": SeriesPolicy(1, 0, False),
    "on_rrp": SeriesPolicy(0, 0, False),
    "us_m2": SeriesPolicy(1, 1, False),
    **{key: SeriesPolicy(1, 0, True) for keys in COT_KEYS.values() for key in keys},
}
VINTAGE_UNSAFE_FEATURES = {"net_liquidity_4w_log", "m2_13w_log"}


@dataclass
class PredictiveForecast:
    asset: str
    as_of_date: date
    status: str
    predicted_return: float
    lower_80: float
    upper_80: float
    probability_up: float
    bias_score: float
    regime: str
    n_observations: int
    training_start: date
    training_end: date
    diagnostics: dict
    contributions: list[dict]
    feature_snapshot: dict
    model_version: str = MODEL_VERSION
    horizon_weeks: int = 4


@dataclass
class PredictiveDataset:
    """Features and labels are separate by construction to prevent leakage."""
    features: pd.DataFrame
    target: pd.Series
    price: pd.Series
    source_age_weeks: pd.DataFrame
    vintage_unsafe_features: list[str]


@dataclass
class _Fit:
    beta: np.ndarray
    covariance: np.ndarray
    residual_variance: float
    df: int
    medians: pd.Series
    scales: pd.Series
    columns: list[str]
    effective_n: int
    covariance_method: str
    estimator: str = "robust_ridge"


def _weekly_with_age(
    series: pd.Series,
    policy: SeriesPolicy,
) -> tuple[pd.Series, pd.Series]:
    if series is None or series.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    clean = clean[~clean.index.duplicated(keep="last")].sort_index()
    observed = clean.resample("W-FRI").last()
    if policy.publication_lag_weeks:
        observed = observed.shift(policy.publication_lag_weeks)
    marker = observed.notna()
    groups = marker.cumsum()
    age = (~marker).groupby(groups).cumsum().astype(float)
    age = age.where(groups > 0)
    if policy.max_ffill_weeks > 0:
        weekly = observed.ffill(limit=policy.max_ffill_weeks)
    else:
        weekly = observed
    return weekly, age.where(weekly.notna())


def _weekly(series: pd.Series, limit: int = 0) -> pd.Series:
    """Backward-compatible helper with an explicit, safe default of no fill."""
    return _weekly_with_age(series, SeriesPolicy(max_ffill_weeks=limit))[0]


def _pick(frame: pd.DataFrame, keys: tuple[str, ...]) -> pd.Series:
    for key in keys:
        if key in frame and frame[key].notna().sum() >= 20:
            return frame[key]
    return pd.Series(np.nan, index=frame.index, dtype=float)


def _safe_log_change(series: pd.Series, periods: int) -> pd.Series:
    positive = series.where(series > 0)
    return np.log(positive).diff(periods)


def build_predictive_dataset(
    series_dict: dict[str, pd.Series],
    asset: str,
    horizon: int = 4,
) -> PredictiveDataset:
    """Create a weekly dataset with labels physically separated from features."""
    weekly: dict[str, pd.Series] = {}
    ages: dict[str, pd.Series] = {}
    for key, value in series_dict.items():
        if value is None or value.empty:
            continue
        policy = SERIES_POLICIES.get(key, SeriesPolicy())
        weekly[key], ages[key] = _weekly_with_age(value, policy)
    raw = pd.concat(weekly, axis=1).sort_index() if weekly else pd.DataFrame()
    if raw.empty:
        empty = pd.Series(dtype=float)
        return PredictiveDataset(pd.DataFrame(), empty, empty, pd.DataFrame(), [])
    age_frame = pd.concat(ages, axis=1).reindex(raw.index) if ages else pd.DataFrame(index=raw.index)

    def col(name: str) -> pd.Series:
        return raw[name] if name in raw else pd.Series(np.nan, index=raw.index, dtype=float)

    price = _pick(raw, PRICE_KEYS[asset])
    real10, nominal10, yield2 = col("us_10y_real_yield"), col("us_10y_yield"), col("us_2y_yield")
    breakeven = nominal10 - real10
    curve = nominal10 - yield2

    walcl, tga, rrp = col("fed_balance_sheet"), col("tga"), col("on_rrp")
    # FRED metadata stores WALCL and TGA in millions USD, while ON RRP is in
    # billions USD. Convert only RRP to millions before subtraction.
    net_liquidity = walcl - tga - rrp * 1000.0

    vix, vix3m = col("vix"), col("vix3m")
    mcc = col("mcclellan_oscillator")
    mcc_scale = mcc.rolling(52, min_periods=26).std().replace(0, np.nan)

    cot_net_key, cot_oi_key = COT_KEYS[asset]
    cot_ratio = col(cot_net_key) / col(cot_oi_key).replace(0, np.nan)

    features = pd.DataFrame(index=raw.index)
    # Basis-point changes, not yield levels.  This prevents a persistent high
    # level from dominating and lets rising/falling moves have different betas.
    features["real_yield_4w_bp"] = real10.diff(4) * 100.0
    features["breakeven_4w_bp"] = breakeven.diff(4) * 100.0
    features["curve_4w_bp"] = curve.diff(4) * 100.0
    features["net_liquidity_4w_log"] = _safe_log_change(net_liquidity, 4)
    features["m2_13w_log"] = _safe_log_change(col("us_m2"), 13)
    features["dxy_4w_log"] = _safe_log_change(col("dxy"), 4)
    features["hy_oas_4w_bp"] = col("hy_oas").diff(4) * 100.0
    features["vix_4w_log"] = _safe_log_change(vix, 4)
    features["vix_curve_log"] = np.log((vix3m / vix).where((vix3m > 0) & (vix > 0)))
    features["breadth_mcc_scaled"] = mcc / mcc_scale
    features["breadth_200ma_4w"] = col("pct_above_200ma").diff(4) / 100.0
    features["cot_net_oi"] = cot_ratio
    features["cot_net_oi_4w"] = cot_ratio.diff(4)
    features["momentum_4w"] = _safe_log_change(price, 4)
    features["momentum_13w"] = _safe_log_change(price, 13)
    features = features.replace([np.inf, -np.inf], np.nan)
    target = np.log(price.shift(-horizon) / price).rename("target")
    unsafe = [
        name for name in VINTAGE_UNSAFE_FEATURES
        if name in features and features[name].notna().mean() >= 0.55
    ]
    return PredictiveDataset(features, target, price.rename("price"), age_frame, unsafe)


def build_feature_frame(series_dict: dict[str, pd.Series], asset: str, horizon: int = 4) -> pd.DataFrame:
    """Public feature-only API. Target and price are never returned as columns."""
    return build_predictive_dataset(series_dict, asset, horizon).features


def _expand_asymmetry(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for name in frame.columns:
        if name in ASYMMETRIC:
            out[f"{name}_up"] = frame[name].clip(lower=0)
            out[f"{name}_down"] = (-frame[name]).clip(lower=0)
        else:
            out[name] = frame[name]
    return out


def _newey_west_covariance(
    design: np.ndarray,
    residual: np.ndarray,
    weights: np.ndarray,
    precision: np.ndarray,
    lag: int,
) -> np.ndarray:
    """Bartlett HAC sandwich for weighted ridge score vectors."""
    scores = design * (weights * residual)[:, None]
    meat = scores.T @ scores
    max_lag = min(max(int(lag), 0), len(scores) - 1)
    for offset in range(1, max_lag + 1):
        bartlett = 1.0 - offset / (max_lag + 1.0)
        gamma = scores[offset:].T @ scores[:-offset]
        meat += bartlett * (gamma + gamma.T)
    bread = np.linalg.pinv(precision)
    covariance = bread @ meat @ bread
    covariance = (covariance + covariance.T) / 2.0
    # Numerical round-off or finite-sample HAC estimates can be slightly
    # indefinite. Project to the positive-semidefinite cone for prediction.
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    return eigenvectors @ np.diag(np.maximum(eigenvalues, 0.0)) @ eigenvectors.T


def _fit_model(
    features: pd.DataFrame,
    target: pd.Series,
    prior_precision: float = 6.0,
    horizon: int = 4,
) -> _Fit:
    expanded = _expand_asymmetry(features)
    availability = expanded.notna().mean()
    columns = [c for c in expanded if availability[c] >= 0.55 and expanded[c].nunique(dropna=True) > 5]
    if not columns:
        raise ValueError("No sufficiently complete predictive features")

    x = expanded[columns].astype(float)
    medians = x.median()
    x = x.fillna(medians)
    mad = (x - medians).abs().median()
    scales = (1.4826 * mad).where(lambda value: value > 1e-8, x.std()).fillna(1.0)
    scales = scales.where(scales > 1e-8, 1.0)
    z = ((x - medians) / scales).clip(-5.0, 5.0).to_numpy()
    design = np.column_stack([np.ones(len(z)), z])
    y = target.astype(float).to_numpy()

    penalty = np.eye(design.shape[1]) * prior_precision
    penalty[0, 0] = 1e-8
    weights = np.ones(len(y))
    beta = np.zeros(design.shape[1])
    # Student-t IRLS approximation (nu=5) protects the coefficients from shock
    # weeks while retaining those observations in the uncertainty estimate.
    for _ in range(8):
        xtw = design.T * weights
        beta_new = np.linalg.solve(xtw @ design + penalty, xtw @ y)
        residual = y - design @ beta_new
        robust_scale = max(1.4826 * np.median(np.abs(residual - np.median(residual))), 1e-6)
        weights = 6.0 / (5.0 + (residual / robust_scale) ** 2)
        if np.max(np.abs(beta_new - beta)) < 1e-8:
            beta = beta_new
            break
        beta = beta_new

    residual = y - design @ beta
    raw_df = max(len(y) - design.shape[1], 3)
    sigma2 = max(float(np.sum(weights * residual**2) / raw_df), 1e-8)
    precision = (design.T * weights) @ design + penalty
    covariance = _newey_west_covariance(
        design, residual, weights, precision, lag=max(horizon - 1, 0)
    )
    effective_n = max(int(np.ceil(len(y) / max(horizon, 1))), 1)
    df = max(effective_n - design.shape[1], 3)
    return _Fit(
        beta, covariance, sigma2, df, medians, scales, columns,
        effective_n, f"newey_west_hac_lag_{max(horizon - 1, 0)}",
    )


def _soft_threshold(value: float, threshold: float) -> float:
    return float(np.sign(value) * max(abs(value) - threshold, 0.0))


def _fit_elastic_net(
    features: pd.DataFrame,
    target: pd.Series,
    horizon: int = 4,
    l1_ratio: float = 0.35,
) -> _Fit:
    """Small-sample Elastic Net with a fixed, scale-aware penalty.

    The penalty is intentionally frozen rather than tuned on the headline OOS
    window.  Elastic Net is a challenger for correlated inputs, not a hidden
    hyperparameter search over the same 18 evaluation blocks.
    """
    expanded = _expand_asymmetry(features)
    availability = expanded.notna().mean()
    columns = [
        c for c in expanded
        if availability[c] >= 0.55 and expanded[c].nunique(dropna=True) > 5
    ]
    if not columns:
        raise ValueError("No sufficiently complete predictive features")
    x = expanded[columns].astype(float)
    medians = x.median()
    x = x.fillna(medians)
    mad = (x - medians).abs().median()
    scales = (1.4826 * mad).where(lambda value: value > 1e-8, x.std()).fillna(1.0)
    scales = scales.where(scales > 1e-8, 1.0)
    z = ((x - medians) / scales).clip(-5.0, 5.0).to_numpy(dtype=float)
    y = target.astype(float).to_numpy()
    intercept = float(np.mean(y))
    centered = y - intercept
    beta_features = np.zeros(z.shape[1], dtype=float)
    response_scale = max(float(np.std(centered, ddof=1)), 1e-6)
    # Objective: SSE/2 + lambda * [l1_ratio*|b| + (1-l1_ratio)*b²/2].
    # A five-percent response-scale penalty is conservative at this N and is
    # fixed in MODEL_VERSION so it cannot be selected after seeing OOS results.
    lam = len(y) * response_scale * 0.05
    fitted = np.zeros(len(y), dtype=float)
    for _ in range(500):
        previous = beta_features.copy()
        for j in range(z.shape[1]):
            fitted_without_j = fitted - z[:, j] * beta_features[j]
            partial = centered - fitted_without_j
            numerator = float(z[:, j] @ partial)
            denominator = float(z[:, j] @ z[:, j] + lam * (1.0 - l1_ratio))
            beta_features[j] = _soft_threshold(numerator, lam * l1_ratio) / max(denominator, 1e-12)
            fitted = fitted_without_j + z[:, j] * beta_features[j]
        if np.max(np.abs(beta_features - previous)) < 1e-9:
            break

    design = np.column_stack([np.ones(len(z)), z])
    beta = np.r_[intercept, beta_features]
    residual = y - design @ beta
    active = int(np.count_nonzero(np.abs(beta_features) > 1e-10))
    raw_df = max(len(y) - active - 1, 3)
    sigma2 = max(float(residual @ residual / raw_df), 1e-8)
    ridge_penalty = np.eye(design.shape[1]) * lam * (1.0 - l1_ratio)
    ridge_penalty[0, 0] = 1e-8
    precision = design.T @ design + ridge_penalty
    covariance = _newey_west_covariance(
        design, residual, np.ones(len(y)), precision, lag=max(horizon - 1, 0)
    )
    effective_n = max(int(np.ceil(len(y) / max(horizon, 1))), 1)
    df = max(effective_n - active - 1, 3)
    return _Fit(
        beta, covariance, sigma2, df, medians, scales, columns,
        effective_n, f"newey_west_hac_lag_{max(horizon - 1, 0)}",
        "elastic_net_l1_0.35",
    )


def _candidate_frame(features: pd.DataFrame, spec: CandidateSpec) -> pd.DataFrame:
    if spec.feature_names is None:
        return features
    available = [name for name in spec.feature_names if name in features]
    if not available:
        raise ValueError(f"No features available for candidate {spec.name}")
    return features[available]


def _fit_candidate(
    features: pd.DataFrame,
    target: pd.Series,
    spec: CandidateSpec,
    horizon: int,
) -> _Fit:
    frame = _candidate_frame(features, spec)
    if spec.estimator == "elastic_net":
        return _fit_elastic_net(frame, target, horizon=horizon)
    return _fit_model(
        frame, target, prior_precision=spec.prior_precision, horizon=horizon
    )


def _predict_candidate(
    fit: _Fit,
    row: pd.Series,
    spec: CandidateSpec,
) -> tuple[float, float, float, float, list[dict], dict]:
    selected = row if spec.feature_names is None else row.reindex(spec.feature_names)
    return _predict(fit, selected)


def _fit_equity_pool(
    feature_sets: dict[str, pd.DataFrame],
    targets: dict[str, pd.Series],
    horizon: int,
) -> dict[str, _Fit]:
    """Joint mean-regularized fit for SPX/NASDAQ, never Gold.

    Coefficients equal a shared market component plus an asset deviation. The
    deviations receive stronger shrinkage, so the highly correlated equity
    targets borrow strength without being forced to have identical responses.
    """
    assets = ("SPX", "NASDAQ")
    transformed: dict[str, tuple[np.ndarray, pd.Series, pd.Series, np.ndarray, float]] = {}
    common_columns: Optional[set[str]] = None
    expanded_frames: dict[str, pd.DataFrame] = {}
    for asset in assets:
        frame = _expand_asymmetry(_candidate_frame(feature_sets[asset], CANDIDATES[0]))
        expanded_frames[asset] = frame
        eligible = {
            name for name in frame
            if frame[name].notna().mean() >= 0.55 and frame[name].nunique(dropna=True) > 5
        }
        common_columns = eligible if common_columns is None else common_columns & eligible
    columns = sorted(common_columns or set())
    if not columns:
        raise ValueError("No common equity features for partial pooling")

    for asset in assets:
        x = expanded_frames[asset][columns].astype(float)
        medians = x.median()
        filled = x.fillna(medians)
        mad = (filled - medians).abs().median()
        scales = (1.4826 * mad).where(lambda value: value > 1e-8, filled.std()).fillna(1.0)
        scales = scales.where(scales > 1e-8, 1.0)
        z = ((filled - medians) / scales).clip(-5.0, 5.0).to_numpy(dtype=float)
        y = targets[asset].reindex(x.index).astype(float).to_numpy()
        response_scale = max(float(np.std(y, ddof=1)), 1e-6)
        transformed[asset] = (z, medians, scales, y, response_scale)

    p = len(columns)
    total_parameters = 2 + p + 2 * p
    design_parts, response_parts = [], []
    for asset_index, asset in enumerate(assets):
        z, _, _, y, response_scale = transformed[asset]
        design = np.zeros((len(z), total_parameters), dtype=float)
        design[:, asset_index] = 1.0
        design[:, 2:2 + p] = z
        deviation_start = 2 + p + asset_index * p
        design[:, deviation_start:deviation_start + p] = z
        design_parts.append(design)
        response_parts.append(y / response_scale)
    design = np.vstack(design_parts)
    response = np.concatenate(response_parts)
    penalty = np.zeros(total_parameters, dtype=float)
    penalty[:2] = 1e-8
    penalty[2:2 + p] = 6.0
    penalty[2 + p:] = 18.0
    penalty_matrix = np.diag(penalty)
    weights = np.ones(len(response), dtype=float)
    beta = np.zeros(total_parameters, dtype=float)
    for _ in range(10):
        xtw = design.T * weights
        beta_new = np.linalg.solve(xtw @ design + penalty_matrix, xtw @ response)
        residual = response - design @ beta_new
        robust_scale = max(
            1.4826 * np.median(np.abs(residual - np.median(residual))), 1e-6
        )
        weights = 6.0 / (5.0 + (residual / robust_scale) ** 2)
        if np.max(np.abs(beta_new - beta)) < 1e-8:
            beta = beta_new
            break
        beta = beta_new
    residual = response - design @ beta
    joint_sigma2 = max(float(np.sum(weights * residual**2) / max(len(response) - p, 3)), 1e-8)
    joint_covariance = np.linalg.pinv((design.T * weights) @ design + penalty_matrix) * joint_sigma2

    fits: dict[str, _Fit] = {}
    row_offset = 0
    for asset_index, asset in enumerate(assets):
        z, medians, scales, y, response_scale = transformed[asset]
        mapping = np.zeros((p + 1, total_parameters), dtype=float)
        mapping[0, asset_index] = response_scale
        mapping[1:, 2:2 + p] = np.eye(p) * response_scale
        deviation_start = 2 + p + asset_index * p
        mapping[1:, deviation_start:deviation_start + p] = np.eye(p) * response_scale
        asset_beta = mapping @ beta
        asset_covariance = mapping @ joint_covariance @ mapping.T
        asset_residual = y - np.column_stack([np.ones(len(z)), z]) @ asset_beta
        asset_sigma2 = max(float(np.mean(asset_residual**2)), 1e-8)
        effective_n = max(int(np.ceil(len(y) / max(horizon, 1))), 1)
        fits[asset] = _Fit(
            asset_beta, asset_covariance, asset_sigma2,
            max(effective_n - p - 1, 3), medians, scales, columns,
            effective_n, "joint_laplace_partial_pool", "equity_partial_pool",
        )
        row_offset += len(y)
    return fits


def equity_pool_oos_comparison(
    feature_sets: dict[str, pd.DataFrame],
    targets: dict[str, pd.Series],
    horizon: int,
    min_train: int,
) -> dict[str, dict]:
    """Point-forecast audit for the pooled-equity challenger on frozen folds."""
    reference = feature_sets["SPX"]
    records: dict[str, list[dict]] = {"SPX": [], "NASDAQ": []}
    for test_pos in range(min_train + horizon, len(reference) - horizon, horizon):
        train_end = test_pos - horizon
        forecast_date = reference.index[test_pos]
        train_features: dict[str, pd.DataFrame] = {}
        train_targets: dict[str, pd.Series] = {}
        valid = True
        for asset in records:
            asset_target = targets[asset].loc[:reference.index[train_end]].dropna()
            if len(asset_target) < min_train:
                valid = False
                break
            train_targets[asset] = asset_target
            train_features[asset] = feature_sets[asset].reindex(asset_target.index)
            if forecast_date not in feature_sets[asset].index or pd.isna(targets[asset].get(forecast_date)):
                valid = False
                break
        if not valid:
            continue
        try:
            fits = _fit_equity_pool(train_features, train_targets, horizon)
        except (ValueError, np.linalg.LinAlgError):
            continue
        for asset in records:
            predicted = _predict(fits[asset], feature_sets[asset].loc[forecast_date])[0]
            records[asset].append({
                "date": str(forecast_date.date()),
                "predicted": float(predicted),
                "actual": float(targets[asset].loc[forecast_date]),
                "historical_mean": float(train_targets[asset].mean()),
            })
    output: dict[str, dict] = {}
    for asset, asset_records in records.items():
        errors = np.asarray([abs(r["actual"] - r["predicted"]) for r in asset_records])
        actual = np.asarray([r["actual"] for r in asset_records])
        predicted = np.asarray([r["predicted"] for r in asset_records])
        benchmark = np.asarray([r["historical_mean"] for r in asset_records])
        denominator = float(np.sum((actual - benchmark) ** 2))
        standard_error = float(np.std(errors, ddof=1) / np.sqrt(len(errors))) if len(errors) > 1 else np.nan
        output[asset] = {
            "selection_score": float(np.mean(errors) + 0.25 * standard_error) if len(errors) > 1 else None,
            "mae": float(np.mean(errors)) if len(errors) else None,
            "oos_r2": float(1.0 - np.sum((actual - predicted) ** 2) / denominator) if denominator > 0 else None,
            "directional_accuracy": float(np.mean(np.sign(predicted) == np.sign(actual))) if len(actual) else None,
            "brier_score": None,
            "interval_score_80": None,
            "n_oos": len(asset_records),
            "point_forecast_audit_only": True,
        }
    return output


def _predict(fit: _Fit, row: pd.Series) -> tuple[float, float, float, float, list[dict], dict]:
    expanded = _expand_asymmetry(pd.DataFrame([row])).iloc[0]
    raw = expanded.reindex(fit.columns)
    
    # IMPUTED-1: Identify which features required median imputation
    imputed = raw.index[raw.isna()].tolist()
    if imputed:
        logger.warning("Predictive bias imputation applied for missing features: %s", imputed)
        
    z = ((raw.fillna(fit.medians) - fit.medians) / fit.scales).clip(-5.0, 5.0)
    design = np.r_[1.0, z.to_numpy(dtype=float)]
    mean = float(design @ fit.beta)
    variance = max(float(fit.residual_variance + design @ fit.covariance @ design), 1e-10)
    scale = variance**0.5
    q80 = float(student_t.ppf(0.90, fit.df))
    lower, upper = mean - q80 * scale, mean + q80 * scale
    probability_up = float(student_t.cdf(mean / scale, fit.df))
    coef_sd = np.sqrt(np.maximum(np.diag(fit.covariance), 0.0))
    contributions = [
        {
            "feature": name,
            "contribution": float(fit.beta[i + 1] * z.iloc[i]),
            "coefficient": float(fit.beta[i + 1]),
            "coefficient_sd": float(coef_sd[i + 1]),
        }
        for i, name in enumerate(fit.columns)
    ]
    contributions.sort(key=lambda item: abs(item["contribution"]), reverse=True)
    snapshot = {name: (None if pd.isna(raw[name]) else float(raw[name])) for name in fit.columns}
    snapshot["imputed_features"] = imputed  # store list of imputed column names
    return mean, lower, upper, probability_up, contributions, snapshot

def _bootstrap_skill_interval(loss_difference: np.ndarray, block: int = 4, draws: int = 1000) -> tuple[float, float]:
    """Moving-block bootstrap CI for benchmark loss minus model loss."""
    values = np.asarray(loss_difference, dtype=float)
    if len(values) < 8:
        return float("nan"), float("nan")
    rng = np.random.default_rng(_BOOTSTRAP_SEED)  # LOW-1: use named constant
    starts = np.arange(max(len(values) - block + 1, 1))
    means = []
    blocks_needed = int(np.ceil(len(values) / block))
    for _ in range(draws):
        sample = np.concatenate([values[s:s + block] for s in rng.choice(starts, blocks_needed)])[:len(values)]
        means.append(float(np.mean(sample)))
    return tuple(float(v) for v in np.quantile(means, [0.05, 0.95]))


def walk_forward_diagnostics(
    features: pd.DataFrame,
    target: pd.Series,
    horizon: int,
    min_train: int,
    vintage_unsafe_features: Optional[list[str]] = None,
    candidate: Optional[CandidateSpec] = None,
) -> dict:
    candidate = candidate or CANDIDATES[2]  # backward-compatible robust_full
    target = target.reindex(features.index)
    predictions, actuals, naive, lowers, uppers = [], [], [], [], []
    probabilities, naive_probabilities = [], []
    naive_lowers, naive_uppers = [], []
    forecast_dates = []
    # Non-overlapping test points make the headline metrics less deceptively
    # precise.  At time t, targets after t are never available to training.
    for test_pos in range(min_train + horizon, len(features) - horizon, horizon):
        train_end = test_pos - horizon
        train_target = target.iloc[:train_end + 1].dropna()
        train_features = features.reindex(train_target.index)
        if len(train_target) < min_train or pd.isna(target.iloc[test_pos]):
            continue
        try:
            fit = _fit_candidate(train_features, train_target, candidate, horizon)
            pred, low, high, probability, _, _ = _predict_candidate(
                fit, features.iloc[test_pos], candidate
            )
        except (ValueError, np.linalg.LinAlgError):
            continue
        predictions.append(pred)
        actuals.append(float(target.iloc[test_pos]))
        naive.append(float(train_target.mean()))
        lowers.append(low)
        uppers.append(high)
        probabilities.append(probability)
        naive_probabilities.append(float(np.mean(train_target > 0)))
        naive_lowers.append(float(train_target.quantile(0.10)))
        naive_uppers.append(float(train_target.quantile(0.90)))
        forecast_dates.append(str(features.index[test_pos].date()))

    p, y, b = np.asarray(predictions), np.asarray(actuals), np.asarray(naive)
    if len(y) < 3:
        return {"n_oos": int(len(y)), "accepted": False, "reason": "insufficient_oos_history"}
    model_error, benchmark_error = np.abs(y - p), np.abs(y - b)
    denom = float(np.sum((y - b) ** 2))
    rho = spearmanr(p, y).statistic
    skill_low, skill_high = _bootstrap_skill_interval(benchmark_error - model_error)
    coverage80 = float(np.mean((y >= np.asarray(lowers)) & (y <= np.asarray(uppers))))
    probabilities_array = np.clip(np.asarray(probabilities), 1e-6, 1 - 1e-6)
    naive_probabilities_array = np.clip(np.asarray(naive_probabilities), 1e-6, 1 - 1e-6)
    outcomes = (y > 0).astype(float)

    def interval_score(actual, low, high, alpha=0.20):
        actual, low, high = map(np.asarray, (actual, low, high))
        return (high - low) + (2.0 / alpha) * (
            (low - actual) * (actual < low) + (actual - high) * (actual > high)
        )

    model_interval_score = float(np.mean(interval_score(y, lowers, uppers)))
    naive_interval_score = float(np.mean(interval_score(y, naive_lowers, naive_uppers)))
    brier = float(np.mean((probabilities_array - outcomes) ** 2))
    naive_brier = float(np.mean((naive_probabilities_array - outcomes) ** 2))
    log_loss = float(-np.mean(
        outcomes * np.log(probabilities_array)
        + (1.0 - outcomes) * np.log(1.0 - probabilities_array)
    ))
    # DIAG-1: effective independent observations = non-overlapping OOS points /
    # horizon. With 4-week horizon and weekly rows, 4 training rows share one
    # target window, so effective N ≈ n_oos (already non-overlapping by design).
    # The calendar blocks however overlap the training set by (horizon-1) weeks.
    n_oos = int(len(y))
    n_effective_obs = max(1, n_oos)  # non-overlapping OOS horizon blocks
    metrics = {
        "candidate": candidate.name,
        "estimator": candidate.estimator,
        "n_oos": n_oos,
        "n_effective_obs": n_effective_obs,  # DIAG-1
        "mae": float(model_error.mean()),
        "benchmark_mae": float(benchmark_error.mean()),
        "oos_r2": float(1.0 - np.sum((y - p) ** 2) / denom) if denom > 0 else None,
        "spearman": None if np.isnan(rho) else float(rho),
        "directional_accuracy": float(np.mean(np.sign(p) == np.sign(y))),
        "coverage_80": coverage80,
        "interval_score_80": model_interval_score,
        "benchmark_interval_score_80": naive_interval_score,
        "brier_score": brier,
        "benchmark_brier_score": naive_brier,
        "directional_log_loss": log_loss,
        "mae_skill_bootstrap_90_low": skill_low,
        "mae_skill_bootstrap_90_high": skill_high,
        "forecast_dates": forecast_dates,
        "oos_records": [
            {
                "date": forecast_dates[i], "predicted": float(p[i]),
                "actual": float(y[i]), "historical_mean": float(b[i]),
            }
            for i in range(len(y))
        ],
        "vintage_unsafe_features": sorted(vintage_unsafe_features or []),
    }
    checks = {
        "minimum_oos": len(y) >= 40,
        "beats_mean_mae": metrics["mae"] < metrics["benchmark_mae"],
        "positive_oos_r2": metrics["oos_r2"] is not None and metrics["oos_r2"] > 0,
        "rank_information": metrics["spearman"] is not None and metrics["spearman"] > 0.10,
        "directional_edge": metrics["directional_accuracy"] >= 0.52,
        "beats_naive_interval_score": model_interval_score < naive_interval_score,
        "beats_base_rate_brier": brier < naive_brier,
        "bootstrap_skill": not np.isnan(skill_low) and skill_low > 0,
        "vintage_safe_inputs": not bool(vintage_unsafe_features),
    }
    metrics["acceptance_checks"] = checks
    metrics["accepted"] = all(checks.values())
    return metrics


def model_tournament_diagnostics(
    features: pd.DataFrame,
    target: pd.Series,
    horizon: int,
    min_train: int,
    vintage_unsafe_features: Optional[list[str]] = None,
) -> dict:
    """Evaluate frozen candidates on identical expanding, non-overlap folds.

    Selection uses a one-standard-error style conservative MAE: mean absolute
    error plus 0.25 times its standard error. This slightly penalizes an
    apparently good but unstable candidate without mining extra test metrics.
    """
    results: dict[str, dict] = {}
    scores: dict[str, float] = {}
    for spec in CANDIDATES:
        diagnostics = walk_forward_diagnostics(
            features, target, horizon, min_train, vintage_unsafe_features, spec
        )
        results[spec.name] = diagnostics
        records = diagnostics.get("oos_records", [])
        if len(records) < 3:
            scores[spec.name] = float("inf")
            continue
        errors = np.asarray([
            abs(float(record["actual"]) - float(record["predicted"]))
            for record in records
        ])
        standard_error = float(np.std(errors, ddof=1) / np.sqrt(len(errors)))
        scores[spec.name] = float(np.mean(errors) + 0.25 * standard_error)

    selected_name = min(scores, key=scores.get)
    selected = dict(results[selected_name])
    selected["selected_candidate"] = selected_name
    selected["selection_score"] = scores[selected_name]
    selected["selection_rule"] = "MAE + 0.25 x SE; frozen candidates; identical folds"
    selected["candidate_comparison"] = {
        name: {
            "selection_score": None if not np.isfinite(scores[name]) else scores[name],
            "mae": result.get("mae"),
            "oos_r2": result.get("oos_r2"),
            "directional_accuracy": result.get("directional_accuracy"),
            "brier_score": result.get("brier_score"),
            "interval_score_80": result.get("interval_score_80"),
            "n_oos": result.get("n_oos", 0),
        }
        for name, result in results.items()
    }
    # Selecting among candidates on the same history adds selection risk. The
    # existing >=40 OOS and bootstrap gates remain mandatory; current N=18 can
    # never promote a tournament winner merely because it ranks first.
    selected.setdefault("acceptance_checks", {})["tournament_sample_sufficient"] = (
        selected.get("n_oos", 0) >= 40
    )
    selected["accepted"] = all(selected["acceptance_checks"].values())
    return selected



def _calibrate_provisional(
    predicted: float,
    lower: float,
    upper: float,
    probability_up: float,
    diagnostics: dict,
) -> dict:
    """Replace Laplace-approximation values with OOS-calibrated ones for weak models.

    A model the tournament rejects has no demonstrated edge, so its published
    interval must come from realized OOS forecast errors and its direction
    probability must be damped toward the base rate by its measured directional
    accuracy. Accepted (validated) models keep the model-based values.
    """
    calibrated = {
        "lower_80": float(lower), "upper_80": float(upper),
        "probability_up": float(probability_up),
        "applied": False, "reason": None,
    }
    if diagnostics.get("accepted"):
        calibrated["reason"] = "model_accepted"
        return calibrated
    records = diagnostics.get("oos_records") or []
    if not records:
        calibrated["reason"] = "no_oos_records"
        return calibrated
    residuals = np.asarray(
        [float(r["actual"]) - float(r["predicted"]) for r in records], dtype=float,
    )
    if len(residuals) >= 8:
        low_q, high_q = np.quantile(residuals, [0.10, 0.90])
        calibrated["lower_80"] = float(predicted + low_q)
        calibrated["upper_80"] = float(predicted + high_q)
    direction = diagnostics.get("directional_accuracy")
    if direction is not None and not np.isnan(float(direction)):
        edge = float(np.clip(2.0 * (float(direction) - 0.5), 0.0, 1.0))
        calibrated["probability_up"] = 0.5 + (float(probability_up) - 0.5) * edge
    calibrated["applied"] = True
    return calibrated


def _add_legacy_benchmark(asset: str, diagnostics: dict) -> dict:
    """Compare direction/ranking against the production heuristic point-in-time."""
    records = diagnostics.get("oos_records", [])
    with get_session() as session:
        rows = session.execute(select(BiasResult).where(
            BiasResult.asset == asset,
            BiasResult.timeframe == "weekly",
        ).order_by(BiasResult.date, BiasResult.created_at)).scalars().all()
    if not rows or not records:
        diagnostics["legacy_benchmark"] = {"n": 0, "reason": "unavailable"}
        diagnostics.setdefault("acceptance_checks", {})["beats_current_heuristic"] = False
        diagnostics["accepted"] = False
        return diagnostics

    # Keep the last stored framework result on each date, then use the latest
    # result that was actually available at each historical forecast date.
    by_date = {}
    for row in rows:
        by_date[row.date.date()] = float(row.total_score)
    dates = sorted(by_date)
    legacy_scores, actuals, model_predictions = [], [], []
    for record in records:
        forecast_date = date.fromisoformat(record["date"])
        eligible = [value for value in dates if value <= forecast_date]
        if not eligible:
            continue
        legacy_scores.append(by_date[eligible[-1]])
        actuals.append(float(record["actual"]))
        model_predictions.append(float(record["predicted"]))

    if len(actuals) < 8:
        diagnostics["legacy_benchmark"] = {"n": len(actuals), "reason": "insufficient_overlap"}
        diagnostics.setdefault("acceptance_checks", {})["beats_current_heuristic"] = False
        diagnostics["accepted"] = False
        return diagnostics
    legacy = np.asarray(legacy_scores)
    actual = np.asarray(actuals)
    model = np.asarray(model_predictions)
    legacy_hit = float(np.mean(np.sign(legacy) == np.sign(actual)))
    model_hit = float(np.mean(np.sign(model) == np.sign(actual)))
    legacy_rho = spearmanr(legacy, actual).statistic
    model_rho = spearmanr(model, actual).statistic
    legacy_rho = 0.0 if np.isnan(legacy_rho) else float(legacy_rho)
    model_rho = 0.0 if np.isnan(model_rho) else float(model_rho)
    diagnostics["legacy_benchmark"] = {
        "n": len(actual), "directional_accuracy": legacy_hit, "spearman": legacy_rho,
        "model_directional_accuracy_same_dates": model_hit,
        "model_spearman_same_dates": model_rho,
    }
    diagnostics.setdefault("acceptance_checks", {})["beats_current_heuristic"] = (
        model_hit >= legacy_hit and model_rho >= legacy_rho
    )
    diagnostics["accepted"] = all(diagnostics["acceptance_checks"].values())
    return diagnostics


class PredictiveBiasEngine:
    """Frozen model tournament; weak winners remain research-only."""

    def __init__(self, horizon_weeks: Optional[int] = None, min_train_weeks: Optional[int] = None):
        self.horizon = horizon_weeks or settings.predictive_bias_horizon_weeks
        self.min_train = min_train_weeks or settings.predictive_bias_min_train_weeks

    def is_refresh_due(self, now: Optional[datetime] = None) -> bool:
        """Return True if ANY asset is missing or has not been refreshed within
        the configured refresh window.

        SCHED-4 FIX: Previously queried the single newest row across all assets.
        If SPX succeeded but GOLD failed, the SPX timestamp would suppress the
        next run, leaving GOLD permanently stale. Now checks each asset individually.
        """
        now = now or datetime.now(UTC).replace(tzinfo=None)
        cutoff = now - timedelta(days=settings.predictive_bias_refresh_days)
        with get_session() as session:
            for asset in ASSETS:
                latest = session.execute(
                    select(PredictiveBiasResult).where(
                        PredictiveBiasResult.asset == asset,
                        PredictiveBiasResult.model_version == MODEL_VERSION,
                        PredictiveBiasResult.horizon_weeks == self.horizon,
                    ).order_by(desc(PredictiveBiasResult.created_at)).limit(1)
                ).scalar_one_or_none()
                if latest is None or latest.created_at <= cutoff:
                    return True  # at least one asset needs refresh
        return False

    def run(self, calc_date: Optional[date] = None, force: bool = False, status_callback=None) -> dict[str, PredictiveForecast]:
        def status(message: str) -> None:
            logger.info("[PredictiveBias] %s", message)
            if status_callback:
                status_callback(message)

        if not force and not self.is_refresh_due():
            status("Predictive model is inside the 3-day refresh window; using stored forecast")
            return get_latest_predictive_bias()

        owner_id = uuid.uuid4().hex
        if not self._acquire_run_lease(owner_id):
            status("Another predictive model run owns the database lease; using stored forecast")
            return get_latest_predictive_bias()

        try:
            end_date = calc_date or date.today()
            status("Building point-in-time weekly features")
            raw = load_all_series(ALL_INDICATORS, days=365 * 15, end_date=end_date)
            datasets = {
                asset: build_predictive_dataset(raw, asset, self.horizon)
                for asset in ASSETS
            }
            try:
                pooled_audit = equity_pool_oos_comparison(
                    {
                        asset: datasets[asset].features.loc[:pd.Timestamp(end_date)]
                        for asset in ("SPX", "NASDAQ")
                    },
                    {
                        asset: datasets[asset].target.loc[:pd.Timestamp(end_date)]
                        for asset in ("SPX", "NASDAQ")
                    },
                    self.horizon,
                    self.min_train,
                )
            except (ValueError, np.linalg.LinAlgError, KeyError):
                logger.exception("Equity partial-pooling audit failed")
                pooled_audit = {}
            results: dict[str, PredictiveForecast] = {}
            for asset in ASSETS:
                dataset = datasets[asset]
                features = dataset.features.loc[:pd.Timestamp(end_date)]
                target = dataset.target.reindex(features.index)
                price = dataset.price.reindex(features.index)
                price_rows = price.dropna()
                if len(price_rows) < self.min_train + self.horizon + 1:
                    status(f"{asset}: insufficient weekly history ({len(price_rows)})")
                    continue
                as_of = price_rows.index[-1]
                history_features = features.loc[:as_of]
                history_target = target.loc[:as_of]
                diagnostics = model_tournament_diagnostics(
                    history_features,
                    history_target,
                    self.horizon,
                    self.min_train,
                    dataset.vintage_unsafe_features,
                )
                if asset in pooled_audit:
                    diagnostics.setdefault("candidate_comparison", {})[
                        "equity_partial_pool"
                    ] = pooled_audit[asset]
                    diagnostics["partial_pool_decision"] = (
                        "audit_only_not_selected"
                        if pooled_audit[asset].get("selection_score") is None
                        or pooled_audit[asset]["selection_score"]
                        >= diagnostics.get("selection_score", float("inf"))
                        else "promising_requires_full_uncertainty_validation"
                    )
                diagnostics = _add_legacy_benchmark(asset, diagnostics)
                train_target = history_target.iloc[:-self.horizon].dropna()
                train_features = history_features.reindex(train_target.index)
                selected_name = diagnostics.get("selected_candidate", "robust_reduced")
                selected_spec = next(
                    spec for spec in CANDIDATES if spec.name == selected_name
                )
                fit = _fit_candidate(
                    train_features, train_target, selected_spec, self.horizon
                )
                pred, low, high, probability, contributions, snapshot = _predict_candidate(
                    fit, history_features.loc[as_of], selected_spec
                )
                calibration = _calibrate_provisional(pred, low, high, probability, diagnostics)
                diagnostics["published_value_calibration"] = calibration
                low = calibration["lower_80"]
                high = calibration["upper_80"]
                probability = calibration["probability_up"]
                age_row = dataset.source_age_weeks.reindex([as_of]).iloc[0]
                snapshot["source_age_weeks"] = {
                    key: (None if pd.isna(value) else float(value))
                    for key, value in age_row.items()
                }
                diagnostics["coefficient_covariance"] = fit.covariance_method
                diagnostics["fitted_estimator"] = fit.estimator
                diagnostics["effective_training_blocks"] = fit.effective_n
                model_status = "validated" if diagnostics.get("accepted") else "provisional"
                score = float(np.clip((2.0 * probability - 1.0) * 100.0, -100.0, 100.0))
                regime = classify_regime(score).regime.value
                forecast = PredictiveForecast(
                    asset=asset,
                    as_of_date=as_of.date(),
                    status=model_status,
                    predicted_return=pred,
                    lower_80=low,
                    upper_80=high,
                    probability_up=probability,
                    bias_score=score,
                    regime=regime,
                    n_observations=len(train_target),
                    training_start=train_target.index[0].date(),
                    training_end=train_target.index[-1].date(),
                    diagnostics=diagnostics,
                    contributions=contributions,
                    feature_snapshot=snapshot,
                    horizon_weeks=self.horizon,
                )
                self._store(forecast)
                results[asset] = forecast
                status(f"{asset}: {model_status}, research P(up)={probability:.1%}, expected={pred:.2%}")
            return results
        finally:
            self._release_run_lease(owner_id)

    def _acquire_run_lease(self, owner_id: str, minutes: int = 45) -> bool:
        """Atomically claim one model-version/horizon run across all processes."""
        if db_engine.dialect.name != "sqlite":
            raise RuntimeError("Predictive run leasing currently requires SQLite")
        now = datetime.now(UTC).replace(tzinfo=None)
        lease_key = f"{MODEL_VERSION}:{self.horizon}"
        stmt = sqlite_insert(PredictiveModelRunLease).values(
            lease_key=lease_key,
            owner_id=owner_id,
            acquired_until=now + timedelta(minutes=minutes),
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=[PredictiveModelRunLease.lease_key],
            set_={
                "owner_id": owner_id,
                "acquired_until": now + timedelta(minutes=minutes),
                "updated_at": now,
            },
            where=PredictiveModelRunLease.acquired_until <= now,
        )
        with get_session() as session:
            result = session.execute(stmt)
            session.commit()
            return result.rowcount == 1

    def _release_run_lease(self, owner_id: str) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        lease_key = f"{MODEL_VERSION}:{self.horizon}"
        with get_session() as session:
            lease = session.get(PredictiveModelRunLease, lease_key)
            if lease is not None and lease.owner_id == owner_id:
                lease.acquired_until = now
                lease.updated_at = now
                session.commit()

    def _store(self, result: PredictiveForecast) -> None:
        """Atomically upsert one forecast using its natural unique key."""
        dt = datetime.combine(result.as_of_date, datetime.min.time())
        if db_engine.dialect.name != "sqlite":
            raise RuntimeError("Predictive forecast upsert currently requires SQLite")
        values = asdict(result)
        values.pop("as_of_date")
        values["date"] = dt
        values["training_start"] = datetime.combine(result.training_start, datetime.min.time())
        values["training_end"] = datetime.combine(result.training_end, datetime.min.time())
        values["created_at"] = datetime.now(UTC).replace(tzinfo=None)
        update_values = {
            key: value for key, value in values.items()
            if key not in {"asset", "date", "horizon_weeks", "model_version"}
        }
        stmt = sqlite_insert(PredictiveBiasResult).values(**values).on_conflict_do_update(
            index_elements=[
                PredictiveBiasResult.asset,
                PredictiveBiasResult.date,
                PredictiveBiasResult.horizon_weeks,
                PredictiveBiasResult.model_version,
            ],
            set_=update_values,
        )
        with get_session() as session:
            session.execute(stmt)
            session.commit()



def _from_row(row: PredictiveBiasResult) -> PredictiveForecast:
    return PredictiveForecast(
        asset=row.asset, as_of_date=row.date.date(), status=row.status,
        predicted_return=row.predicted_return, lower_80=row.lower_80,
        upper_80=row.upper_80, probability_up=row.probability_up,
        bias_score=row.bias_score, regime=row.regime,
        n_observations=row.n_observations,
        training_start=(row.training_start or row.date).date(),
        training_end=(row.training_end or row.date).date(),
        diagnostics=row.diagnostics or {}, contributions=row.contributions or [],
        feature_snapshot=row.feature_snapshot or {}, model_version=row.model_version,
        horizon_weeks=row.horizon_weeks,
    )


def get_latest_predictive_bias() -> dict[str, PredictiveForecast]:
    results: dict[str, PredictiveForecast] = {}
    with get_session() as session:
        for asset in ASSETS:
            row = session.execute(select(PredictiveBiasResult).where(
                PredictiveBiasResult.asset == asset,
                PredictiveBiasResult.model_version == MODEL_VERSION,
            ).order_by(desc(PredictiveBiasResult.date), desc(PredictiveBiasResult.created_at)).limit(1)).scalar_one_or_none()
            if row is not None:
                results[asset] = _from_row(row)
    return results
