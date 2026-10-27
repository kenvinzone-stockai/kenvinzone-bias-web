"""Calendar-week seasonality statistics built from observed closing prices."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WeekSeasonality:
    """Descriptive statistics for one ISO calendar week."""

    iso_week: int
    observations: int
    up_count: int
    down_count: int
    flat_count: int
    up_rate: float
    down_rate: float
    median_return: float
    mean_return: float
    best_return: float
    worst_return: float
    up_rate_ci_low: float
    up_rate_ci_high: float


@dataclass(frozen=True)
class MonthSeasonality:
    """Descriptive statistics for one calendar month."""

    month: int
    observations: int
    up_count: int
    down_count: int
    flat_count: int
    up_rate: float
    down_rate: float
    median_return: float
    mean_return: float
    best_return: float
    worst_return: float
    up_rate_ci_low: float
    up_rate_ci_high: float


def _clean_prices(prices: pd.Series) -> pd.Series:
    clean = pd.to_numeric(prices, errors="coerce").dropna()
    clean = clean[clean > 0].sort_index()
    if clean.empty:
        return pd.Series(dtype=float, name="close")

    index = pd.DatetimeIndex(pd.to_datetime(clean.index))
    if index.tz is not None:
        index = index.tz_convert(None)
    clean.index = index.normalize()
    clean = clean.groupby(level=0).last().sort_index()
    clean.name = "close"
    return clean


def build_weekly_returns(
    prices: pd.Series,
    *,
    as_of: pd.Timestamp | None = None,
    exclude_incomplete_week: bool = True,
) -> pd.DataFrame:
    """Return one close-to-close observation per completed ISO week.

    The observation assigned to ISO week ``w`` is the return from the last
    available close in the preceding week to the last available close in week
    ``w``.  Friday-labelled buckets keep holiday-shortened weeks comparable.
    """
    clean = _clean_prices(prices)
    columns = [
        "iso_year", "iso_week", "week_ending", "start_close", "end_close",
        "return_pct", "direction",
    ]
    if len(clean) < 2:
        return pd.DataFrame(columns=columns)

    weekly_close = clean.resample("W-FRI").last().dropna()
    if exclude_incomplete_week:
        cutoff = pd.Timestamp(as_of or pd.Timestamp.now()).tz_localize(None).normalize()
        # On Friday the official close may not yet be final. From Saturday on,
        # the Friday-labelled bucket is a completed week and may be included.
        weekly_close = weekly_close[weekly_close.index < cutoff]

    frame = pd.DataFrame({
        "week_ending": weekly_close.index,
        "start_close": weekly_close.shift(1).to_numpy(),
        "end_close": weekly_close.to_numpy(),
    }).dropna(subset=["start_close", "end_close"])
    frame["return_pct"] = (frame["end_close"] / frame["start_close"] - 1.0) * 100.0
    iso = pd.DatetimeIndex(frame["week_ending"]).isocalendar()
    frame["iso_year"] = iso["year"].to_numpy(dtype=int)
    frame["iso_week"] = iso["week"].to_numpy(dtype=int)
    frame["direction"] = frame["return_pct"].map(
        lambda value: "Tăng" if value > 0 else "Giảm" if value < 0 else "Đi ngang"
    )
    return frame[columns].reset_index(drop=True)


def build_monthly_returns(
    prices: pd.Series,
    *,
    as_of: pd.Timestamp | None = None,
    exclude_incomplete_month: bool = True,
) -> pd.DataFrame:
    """Return one close-to-close observation per completed calendar month."""
    clean = _clean_prices(prices)
    columns = [
        "calendar_year", "month", "month_ending", "start_close", "end_close",
        "return_pct", "direction",
    ]
    if len(clean) < 2:
        return pd.DataFrame(columns=columns)

    monthly_close = clean.resample("ME").last().dropna()
    if exclude_incomplete_month:
        cutoff = pd.Timestamp(as_of or pd.Timestamp.now()).tz_localize(None).normalize()
        # A calendar-month bucket becomes eligible only after its month-end.
        monthly_close = monthly_close[monthly_close.index < cutoff]

    frame = pd.DataFrame({
        "month_ending": monthly_close.index,
        "start_close": monthly_close.shift(1).to_numpy(),
        "end_close": monthly_close.to_numpy(),
    }).dropna(subset=["start_close", "end_close"])
    frame["return_pct"] = (frame["end_close"] / frame["start_close"] - 1.0) * 100.0
    frame["calendar_year"] = pd.DatetimeIndex(frame["month_ending"]).year
    frame["month"] = pd.DatetimeIndex(frame["month_ending"]).month
    frame["direction"] = frame["return_pct"].map(
        lambda value: "Tăng" if value > 0 else "Giảm" if value < 0 else "Đi ngang"
    )
    return frame[columns].reset_index(drop=True)


def wilson_interval(successes: int, observations: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, returned as 0..1."""
    if observations <= 0:
        return 0.0, 1.0
    p = successes / observations
    z2 = z * z
    denominator = 1.0 + z2 / observations
    centre = (p + z2 / (2.0 * observations)) / denominator
    margin = z * sqrt((p * (1.0 - p) / observations) + z2 / (4.0 * observations**2)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def summarize_iso_week(weekly_returns: pd.DataFrame, iso_week: int) -> WeekSeasonality | None:
    """Summarize the historical outcomes for one ISO week number."""
    if not 1 <= int(iso_week) <= 53:
        raise ValueError("iso_week must be between 1 and 53")
    sample = weekly_returns.loc[weekly_returns["iso_week"] == int(iso_week)].copy()
    if sample.empty:
        return None

    values = sample["return_pct"].astype(float)
    n = len(values)
    up_count = int((values > 0).sum())
    down_count = int((values < 0).sum())
    flat_count = n - up_count - down_count
    low, high = wilson_interval(up_count, n)
    return WeekSeasonality(
        iso_week=int(iso_week),
        observations=n,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        up_rate=up_count / n * 100.0,
        down_rate=down_count / n * 100.0,
        median_return=float(values.median()),
        mean_return=float(values.mean()),
        best_return=float(values.max()),
        worst_return=float(values.min()),
        up_rate_ci_low=low * 100.0,
        up_rate_ci_high=high * 100.0,
    )


def summarize_all_weeks(weekly_returns: pd.DataFrame) -> pd.DataFrame:
    """Build a compact 1–53 overview for charting and comparison."""
    rows: list[dict[str, float | int]] = []
    for week in sorted(weekly_returns["iso_week"].dropna().astype(int).unique()):
        summary = summarize_iso_week(weekly_returns, week)
        if summary is None:
            continue
        rows.append({
            "Tuần ISO": week,
            "Số năm": summary.observations,
            "Tỷ lệ tăng (%)": summary.up_rate,
            "Tỷ lệ giảm (%)": summary.down_rate,
            "Lợi suất trung vị (%)": summary.median_return,
        })
    return pd.DataFrame(rows)


def summarize_month(monthly_returns: pd.DataFrame, month: int) -> MonthSeasonality | None:
    """Summarize the historical outcomes for one calendar month."""
    if not 1 <= int(month) <= 12:
        raise ValueError("month must be between 1 and 12")
    sample = monthly_returns.loc[monthly_returns["month"] == int(month)].copy()
    if sample.empty:
        return None

    values = sample["return_pct"].astype(float)
    n = len(values)
    up_count = int((values > 0).sum())
    down_count = int((values < 0).sum())
    flat_count = n - up_count - down_count
    low, high = wilson_interval(up_count, n)
    return MonthSeasonality(
        month=int(month),
        observations=n,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        up_rate=up_count / n * 100.0,
        down_rate=down_count / n * 100.0,
        median_return=float(values.median()),
        mean_return=float(values.mean()),
        best_return=float(values.max()),
        worst_return=float(values.min()),
        up_rate_ci_low=low * 100.0,
        up_rate_ci_high=high * 100.0,
    )


def summarize_all_months(monthly_returns: pd.DataFrame) -> pd.DataFrame:
    """Build a compact January–December overview."""
    rows: list[dict[str, float | int]] = []
    for month in range(1, 13):
        summary = summarize_month(monthly_returns, month)
        if summary is None:
            continue
        rows.append({
            "Tháng": month,
            "Số năm": summary.observations,
            "Tỷ lệ tăng (%)": summary.up_rate,
            "Tỷ lệ giảm (%)": summary.down_rate,
            "Lợi suất trung vị (%)": summary.median_return,
        })
    return pd.DataFrame(rows)


ANALOG_FEATURES = (
    "asset_momentum_4w_pct",
    "asset_momentum_13w_pct",
    "asset_realized_vol_4w_pct",
    "vix_level",
    "dxy_change_4w_pct",
    "us10y_change_4w_bps",
)


def build_market_analogs(
    asset_prices: pd.Series,
    context_prices: dict[str, pd.Series],
    period_returns: pd.DataFrame,
    *,
    period_kind: str,
    selected_period: int,
    as_of: pd.Timestamp | None = None,
    top_n: int = 5,
) -> tuple[dict[str, float | str], pd.DataFrame]:
    """Find same-calendar-period analogs from pre-period market conditions.

    Similarity is computed by robustly scaling six features and measuring the
    RMS distance from the latest observable market state. Historical outcomes
    are attached only *after* matching and never enter the distance function.
    """
    if period_kind not in {"iso_week", "month"}:
        raise ValueError("period_kind must be 'iso_week' or 'month'")
    upper = 53 if period_kind == "iso_week" else 12
    if not 1 <= int(selected_period) <= upper:
        raise ValueError("selected_period is outside the valid range")
    if top_n < 1:
        raise ValueError("top_n must be positive")

    series = {"asset": _clean_prices(asset_prices)}
    for name in ("vix", "dxy", "us10y"):
        candidate = context_prices.get(name, pd.Series(dtype=float))
        series[name] = _clean_prices(candidate)
    daily = pd.concat(series, axis=1).sort_index().ffill(limit=5)
    if daily.empty or daily["asset"].dropna().shape[0] < 70:
        return {}, pd.DataFrame()

    log_returns = np.log(daily["asset"] / daily["asset"].shift(1))
    features = pd.DataFrame(index=daily.index)
    features["asset_momentum_4w_pct"] = daily["asset"].pct_change(20) * 100.0
    features["asset_momentum_13w_pct"] = daily["asset"].pct_change(65) * 100.0
    features["asset_realized_vol_4w_pct"] = (
        log_returns.rolling(20, min_periods=15).std() * sqrt(252.0) * 100.0
    )
    features["vix_level"] = daily["vix"]
    features["dxy_change_4w_pct"] = daily["dxy"].pct_change(20) * 100.0
    features["us10y_change_4w_bps"] = (daily["us10y"] - daily["us10y"].shift(20)) * 100.0

    cutoff = pd.Timestamp(as_of or pd.Timestamp.now()).tz_localize(None).normalize()
    reference_rows = features.loc[features.index <= cutoff].dropna(thresh=4)
    if reference_rows.empty:
        return {}, pd.DataFrame()
    reference = reference_rows.iloc[-1]
    reference_date = pd.Timestamp(reference_rows.index[-1])

    period_col = "iso_week" if period_kind == "iso_week" else "month"
    year_col = "iso_year" if period_kind == "iso_week" else "calendar_year"
    ending_col = "week_ending" if period_kind == "iso_week" else "month_ending"
    selected = period_returns.loc[
        period_returns[period_col] == int(selected_period)
    ].copy()

    candidates: list[dict[str, float | int | pd.Timestamp]] = []
    for row in selected.to_dict("records"):
        ending = pd.Timestamp(row[ending_col]).tz_localize(None)
        pre_period = (
            ending - pd.Timedelta(days=7)
            if period_kind == "iso_week"
            else ending - pd.offsets.MonthEnd(1)
        )
        if pre_period >= reference_date:
            continue
        available = features.loc[features.index <= pre_period].dropna(thresh=4)
        if available.empty:
            continue
        feature_row = available.iloc[-1]
        record: dict[str, float | int | pd.Timestamp] = {
            "year": int(row[year_col]),
            "period_ending": ending,
            "historical_return_pct": float(row["return_pct"]),
        }
        record.update({name: float(feature_row[name]) for name in ANALOG_FEATURES})
        candidates.append(record)

    candidate_frame = pd.DataFrame(candidates)
    if len(candidate_frame) < 3:
        return {}, pd.DataFrame()

    usable_features = [
        name for name in ANALOG_FEATURES
        if pd.notna(reference.get(name))
        and candidate_frame[name].notna().sum() >= 3
        and candidate_frame[name].nunique(dropna=True) > 1
    ]
    if len(usable_features) < 3:
        return {}, pd.DataFrame()

    medians = candidate_frame[usable_features].median()
    mad = (candidate_frame[usable_features] - medians).abs().median() * 1.4826
    fallback_scale = candidate_frame[usable_features].std(ddof=0)
    scale = mad.where(mad > 1e-12, fallback_scale).replace(0, np.nan)

    distances = []
    feature_counts = []
    for _, row in candidate_frame.iterrows():
        differences = []
        for name in usable_features:
            if pd.isna(row[name]) or pd.isna(reference[name]) or pd.isna(scale[name]):
                continue
            differences.append((float(row[name]) - float(reference[name])) / float(scale[name]))
        feature_counts.append(len(differences))
        distances.append(
            float(np.sqrt(np.mean(np.square(differences)))) if len(differences) >= 3 else np.nan
        )
    candidate_frame["feature_count"] = feature_counts
    candidate_frame["distance"] = distances
    candidate_frame = candidate_frame.dropna(subset=["distance"])
    candidate_frame["similarity_score"] = 100.0 / (1.0 + candidate_frame["distance"])
    candidate_frame = candidate_frame.sort_values(
        ["similarity_score", "year"], ascending=[False, False]
    ).head(top_n)

    reference_payload: dict[str, float | str] = {
        "as_of": reference_date.date().isoformat(),
        **{
            name: round(float(reference[name]), 4)
            for name in usable_features if pd.notna(reference[name])
        },
    }
    output_columns = [
        "year", "period_ending", "similarity_score", "historical_return_pct",
        "feature_count", *usable_features,
    ]
    return reference_payload, candidate_frame[output_columns].reset_index(drop=True)
