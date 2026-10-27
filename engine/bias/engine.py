"""
Market Bias Platform — Bias Engine Orchestrator
Loads all indicator data, computes derived metrics, runs all three asset
bias calculators, and stores results to the database.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import select, desc

from core.config import settings
from core.database import get_session
from core.models import BiasResult, FrameworkVersion
from bias.spx import SPXBiasCalculator
from bias.nasdaq import NASDAQBiasCalculator
from bias.gold import GoldBiasCalculator
from bias.base import BiasCalculation
from bias.regimes import DEFAULT_THRESHOLDS
from ingestion.pipeline import load_raw_series, load_all_series
from metrics.statistics import (
    compute_all_windows, cot_index, periods_for_frequency, rolling_zscore,
)

logger = logging.getLogger(__name__)

# ── All indicators needed for metric computation ───────────────────────────────
ALL_INDICATORS = [
    # Liquidity
    "fed_balance_sheet", "fed_reserves", "on_rrp", "tga", "us_m2",
    # Rates
    "fed_funds_rate", "sofr", "us_2y_yield", "us_5y_yield",
    "us_10y_yield", "us_30y_yield", "us_10y_real_yield", "us_5y_real_yield",
    # Credit
    "hy_oas", "ig_oas",
    # USD
    "dxy", "usdjpy",
    # Vol
    "vix", "vxn", "vix3m", "move",
    # Equity indices
    "spx_close", "nasdaq_close", "ndx_close", "rut_close",
    # ETFs
    "spy_close", "qqq_close", "gld_close", "iau_close", "tlt_close",
    # Signed dollar turnover proxies (not ETF creations/redemptions)
    "spy_signed_turnover_proxy", "qqq_signed_turnover_proxy",
    "gld_signed_turnover_proxy",
    # Official GLD holdings / primary-market estimate (diagnostic for now)
    "gld_shares_outstanding_official", "gld_gold_tonnes_official",
    "gld_primary_market_flow", "gld_gold_tonnes_change",
    # Atlanta Fed MPT policy distribution (diagnostic for now)
    "fed_policy_hike_probability_near", "fed_policy_cut_probability_near",
    "fed_policy_hold_probability_near", "fed_policy_expected_rate_near",
    "fed_policy_expected_change_bps_near", "fed_policy_horizon_days_near",
    "fed_policy_hike_probability_next", "fed_policy_cut_probability_next",
    "fed_policy_hold_probability_next", "fed_policy_expected_rate_next",
    "fed_policy_expected_change_bps_next", "fed_policy_horizon_days_next",
    # Commodities
    "gold_futures", "silver", "crude_oil", "copper",
    # Breadth (computed externally or placeholder)
    "mcclellan_oscillator", "pct_above_200ma", "advance_decline_line",
    "spx_net_new_highs",
    # Options
    "spy_gex", "spy_pc_ratio_oi", "spy_gamma_flip",
    "qqq_gex", "qqq_pc_ratio_oi",
    "gld_gex", "gld_pc_ratio_oi",
    "cboe_equity_pc", "cboe_index_pc", "cboe_total_pc",
    # COT
    "cot_spx_net_leveraged", "cot_spx_net_asset_mgr", "cot_spx_open_interest",
    "cot_nasdaq_net_leveraged", "cot_nasdaq_net_asset_mgr", "cot_nasdaq_open_interest",
    "cot_gold_net_noncommercial", "cot_gold_open_interest", "cot_gold_net_commercial",
]

FLOW_SUM_INDICATORS = {
    "spy_signed_turnover_proxy",
    "qqq_signed_turnover_proxy",
    "gld_signed_turnover_proxy",
    "gld_primary_market_flow",
    "gld_gold_tonnes_change",
}


class BiasEngine:
    """
    Orchestrates the full bias computation pipeline:
      1. Load raw series from DB
      2. Compute derived metrics (MA, Z-score, Percentile, COT Index)
      3. Build flat metrics dict (latest values + derived stats)
      4. Run SPX, NASDAQ, Gold bias calculators
      5. Store results in DB
    """

    def __init__(self):
        self.spx_calc = SPXBiasCalculator()
        self.nasdaq_calc = NASDAQBiasCalculator()
        self.gold_calc = GoldBiasCalculator()

    def run(
        self,
        calc_date: Optional[date] = None,
        timeframe: str = "weekly",
        status_callback=None,
    ) -> dict[str, BiasCalculation]:
        """
        Run bias calculations for all assets.

        Args:
            calc_date: Calculation date (defaults to today)
            timeframe: "weekly" or "monthly"
            status_callback: Optional callable(msg: str)

        Returns:
            Dict {asset: BiasCalculation}
        """
        if calc_date is None:
            calc_date = date.today()

        def _status(msg: str):
            logger.info("[BiasEngine] %s", msg)
            if status_callback:
                status_callback(msg)

        _status(f"Loading data for {calc_date} ({timeframe})...")
        framework = self._load_active_framework()

        if timeframe not in {"daily", "weekly", "monthly"}:
            raise ValueError("timeframe must be daily, weekly, or monthly")

        # Load point-in-time data only; future observations must never leak into a score.
        series_dict = load_all_series(ALL_INDICATORS, days=365 * 4, end_date=calc_date)
        series_dict = self._resample_for_timeframe(series_dict, timeframe)
        _status(f"Loaded {sum(1 for s in series_dict.values() if not s.empty)} indicators with data")

        # Compute derived metrics
        _status("Computing derived metrics...")
        metrics = self._compute_metrics(series_dict, frequency=timeframe)
        _status(f"Computed {len(metrics)} metric values")

        # Run each bias calculator
        results = {}
        for calc, asset in [
            (self.spx_calc, "SPX"),
            (self.nasdaq_calc, "NASDAQ"),
            (self.gold_calc, "GOLD"),
        ]:
            _status(f"Scoring {asset}...")
            custom_weights = (
                framework.get("spx_weights") if asset == "SPX" else
                framework.get("nasdaq_weights") if asset == "NASDAQ" else
                framework.get("gold_weights")
            ) if framework else None

            result = calc.compute(
                metrics=metrics,
                calc_date=calc_date,
                timeframe=timeframe,
                custom_weights=custom_weights,
                regime_thresholds=framework.get("regime_thresholds") if framework else None,
            )
            results[asset] = result
            _status(
                f"  {asset}: score={result.total_score:+.1f} "
                f"regime={result.regime_result.regime.value} "
                f"coverage={result.data_coverage:.0%}"
            )

        # Store results
        _status("Storing bias results...")
        fw_version = framework.get("version", 1) if framework else 1
        for asset, result in results.items():
            self._store_bias_result(result, calc_date, timeframe, fw_version)

        _status("✅ Bias engine complete")
        return results

    @staticmethod
    def _resample_for_timeframe(
        series_dict: dict[str, pd.Series], timeframe: str
    ) -> dict[str, pd.Series]:
        if timeframe == "daily":
            return series_dict
        rule = "W-SUN" if timeframe == "weekly" else "ME"
        resampled = {}
        for name, series in series_dict.items():
            clean = series.dropna()
            if clean.empty:
                resampled[name] = series
            elif name in FLOW_SUM_INDICATORS:
                resampled[name] = clean.resample(rule).sum(min_count=1).dropna()
            else:
                resampled[name] = clean.resample(rule).last().dropna()
        return resampled

    def _compute_metrics(
        self,
        series_dict: dict[str, pd.Series],
        frequency: str = "daily",
    ) -> dict[str, Optional[float]]:
        """
        Build a flat dict of {metric_name: latest_value} with all derived stats.
        Includes: raw latest value, Z-score, percentile rank, rolling changes, COT index.
        """
        metrics: dict[str, Optional[float]] = {}
        year_periods = periods_for_frequency(frequency)["year"] or 252
        min_history = max(6, year_periods // 2)

        for indicator, series in series_dict.items():
            if series.empty:
                metrics[indicator] = None
                continue

            # Latest value
            latest = series.dropna().iloc[-1] if not series.dropna().empty else None
            metrics[indicator] = float(latest) if latest is not None else None

            # Compute all window statistics
            try:
                stats = compute_all_windows(series.dropna(), freq=frequency)
                if not stats.empty:
                    latest_stats = stats.iloc[-1]
                    metrics[f"{indicator}_zscore_1y"] = _safe_float(latest_stats.get("zscore_1y"))
                    metrics[f"{indicator}_pct_1y"] = _safe_float(latest_stats.get("pct_rank_1y"))
                    metrics[f"{indicator}_chg_1w"] = _safe_float(latest_stats.get("chg_1w"))
                    metrics[f"{indicator}_chg_4w"] = _safe_float(latest_stats.get("chg_4w"))
                    metrics[f"{indicator}_chg_13w"] = _safe_float(latest_stats.get("chg_13w"))
                    metrics[f"{indicator}_chg_26w"] = _safe_float(latest_stats.get("chg_26w"))
                    metrics[f"{indicator}_chg_52w"] = _safe_float(latest_stats.get("chg_52w"))
                    metrics[f"{indicator}_ma_21"] = _safe_float(latest_stats.get("ma_21"))
                    metrics[f"{indicator}_ma_50"] = _safe_float(latest_stats.get("ma_50"))
                    metrics[f"{indicator}_ma_200"] = _safe_float(latest_stats.get("ma_200"))

                    # Z-score of the 4W change (momentum Z-score)
                    chg_4w_series = stats["chg_4w"].dropna()
                    if len(chg_4w_series) >= max(6, year_periods // 2):
                        chg_4w_z = rolling_zscore(
                            chg_4w_series, year_periods, freq=frequency
                        )
                        if not chg_4w_z.empty:
                            metrics[f"{indicator}_4w_chg_zscore_1y"] = _safe_float(chg_4w_z.iloc[-1])
            except Exception as exc:
                logger.debug("Stats compute failed for %s: %s", indicator, exc)

        # ── Dynamic Baseline Z-scores ──────────────────────────────────────
        nominal_10y = series_dict.get('us_10y_yield', pd.Series(dtype=float))
        real_10y = series_dict.get('us_10y_real_yield', pd.Series(dtype=float))
        if not nominal_10y.empty and not real_10y.empty:
            be_series = (nominal_10y - real_10y).dropna()
            if len(be_series) >= min_history:
                be_z = rolling_zscore(be_series, freq=frequency)
                if not be_z.empty:
                    metrics['breakeven_inflation_zscore_1y'] = _safe_float(be_z.iloc[-1])

        gold_series = series_dict.get('gold_futures', pd.Series(dtype=float))
        silver_series = series_dict.get('silver', pd.Series(dtype=float))
        if not gold_series.empty and not silver_series.empty:
            gsr = gold_series / silver_series
            gsr = gsr.dropna()
            if len(gsr) >= min_history:
                gsr_z = rolling_zscore(gsr, freq=frequency)
                if not gsr_z.empty:
                    metrics['gold_silver_ratio_zscore_1y'] = _safe_float(gsr_z.iloc[-1])

        copper_series = series_dict.get('copper', pd.Series(dtype=float))
        if not gold_series.empty and not copper_series.empty:
            cgr = copper_series / gold_series
            cgr = cgr.dropna()
            if len(cgr) >= min_history:
                cgr_z = rolling_zscore(cgr, freq=frequency)
                if not cgr_z.empty:
                    metrics['copper_gold_ratio_zscore_1y'] = _safe_float(cgr_z.iloc[-1])

        vix_series = series_dict.get('vix', pd.Series(dtype=float))
        vxn_series = series_dict.get('vxn', pd.Series(dtype=float))
        if not vix_series.empty and not vxn_series.empty:
            vxn_vix = vxn_series / vix_series
            vxn_vix = vxn_vix.dropna()
            if len(vxn_vix) >= min_history:
                ratio_z = rolling_zscore(vxn_vix, freq=frequency)
                if not ratio_z.empty:
                    metrics['vxn_vix_ratio_zscore_1y'] = _safe_float(ratio_z.iloc[-1])

        mccl_series = series_dict.get('mcclellan_oscillator', pd.Series(dtype=float))
        if not mccl_series.empty:
            mccl_std = mccl_series.rolling(
                year_periods, min_periods=max(6, year_periods // 2)
            ).std()
            if not mccl_std.empty:
                metrics['mcclellan_std_1y'] = _safe_float(mccl_std.iloc[-1])

        # ── USD Direction / Shock ─────────────────────────────────────────
        # Signed log momentum determines direction. Absolute movement only
        # measures shock intensity and can never create or flip a bias.
        from metrics.usd import compute_usd_direction_metrics
        dxy_series = series_dict.get("dxy", pd.Series(dtype=float))
        if not dxy_series.empty:
            metrics.update(compute_usd_direction_metrics(dxy_series, frequency))

        # ── Net Liquidity ─────────────────────────────────────────────────
        from metrics.liquidity import compute_net_liquidity, compute_global_m2_proxy
        walcl = series_dict.get("fed_balance_sheet", pd.Series(dtype=float))
        tga = series_dict.get("tga", pd.Series(dtype=float))
        rrp = series_dict.get("on_rrp", pd.Series(dtype=float))
        if not walcl.empty and not tga.empty and not rrp.empty:
            try:
                nl = compute_net_liquidity(walcl, tga, rrp)
                nl_stats = compute_all_windows(nl.dropna(), freq=frequency)
                if not nl_stats.empty:
                    latest = nl_stats.iloc[-1]
                    metrics["net_liquidity"] = _safe_float(latest.get("value"))
                    metrics["net_liquidity_zscore_1y"] = _safe_float(latest.get("zscore_1y"))
                    metrics["net_liquidity_pct_1y"] = _safe_float(latest.get("pct_rank_1y"))
                    metrics["net_liquidity_4w_chg"] = _safe_float(latest.get("chg_4w"))
                    
                    if 'chg_4w' in nl_stats.columns:
                        chg_series = nl_stats['chg_4w'].dropna()
                        if len(chg_series) >= max(6, year_periods // 2):
                            chg_z = rolling_zscore(
                                chg_series,
                                min(len(chg_series), year_periods),
                                freq=frequency,
                            )
                            if not chg_z.empty:
                                metrics['net_liquidity_4w_chg_zscore_1y'] = _safe_float(chg_z.iloc[-1])
            except Exception as exc:
                logger.warning("Net liquidity failed: %s", exc)

        # ── COT Indices (3-year min-max normalization) ─────────────────────
        cot_series_map = {
            "cot_spx_net_leveraged": "cot_spx_net_leveraged_cot_index",
            "cot_nasdaq_net_leveraged": "cot_nasdaq_net_leveraged_cot_index",
            "cot_gold_net_noncommercial": "cot_gold_net_noncommercial_cot_index",
        }
        for raw_key, cot_key in cot_series_map.items():
            series = series_dict.get(raw_key, pd.Series(dtype=float))
            if not series.empty and len(series.dropna()) > 30:
                try:
                    cot_window = {"daily": 756, "weekly": 156, "monthly": 36}[frequency]
                    idx = cot_index(series.dropna(), window=cot_window)
                    if not idx.empty:
                        metrics[cot_key] = _safe_float(idx.iloc[-1])
                except Exception as exc:
                    logger.debug("COT index failed for %s: %s", raw_key, exc)

        # ── VIX Term Structure ─────────────────────────────────────────────
        vix_s = series_dict.get("vix", pd.Series(dtype=float))
        vix3m_s = series_dict.get("vix3m", pd.Series(dtype=float))
        if not vix_s.empty and not vix3m_s.empty:
            metrics["vix"] = _safe_float(vix_s.dropna().iloc[-1]) if not vix_s.dropna().empty else None
            metrics["vix3m"] = _safe_float(vix3m_s.dropna().iloc[-1]) if not vix3m_s.dropna().empty else None

        return metrics

    def _load_active_framework(self):
        """Load the active framework version — returns a plain dict to avoid detached session issues."""
        with get_session() as session:
            fw = session.execute(
                select(FrameworkVersion)
                .where(FrameworkVersion.is_active == True)
                .order_by(desc(FrameworkVersion.version))
            ).scalar_one_or_none()

            if fw is None:
                return None

            # Extract all data inside the session before it closes
            return {
                "version":           fw.version,
                "spx_weights":       dict(fw.spx_weights or {}),
                "nasdaq_weights":    dict(fw.nasdaq_weights or {}),
                "gold_weights":      dict(fw.gold_weights or {}),
                "regime_thresholds": dict(fw.regime_thresholds or {}),
            }

    def _store_bias_result(
        self,
        result: BiasCalculation,
        calc_date: date,
        timeframe: str,
        fw_version: int,
    ) -> None:
        """Upsert a bias result into the database."""
        with get_session() as session:
            target_date = datetime.combine(calc_date, datetime.min.time())
            existing = session.execute(
                select(BiasResult).where(
                    BiasResult.asset == result.asset,
                    BiasResult.date == datetime.combine(calc_date, datetime.min.time()),
                    BiasResult.timeframe == timeframe,
                    BiasResult.framework_version == fw_version,
                )
            ).scalar_one_or_none()

            previous = session.execute(
                select(BiasResult)
                .where(
                    BiasResult.asset == result.asset,
                    BiasResult.timeframe == timeframe,
                    BiasResult.framework_version == fw_version,
                    BiasResult.date < target_date,
                )
                .order_by(desc(BiasResult.date), desc(BiasResult.id))
                .limit(1)
            ).scalar_one_or_none()
            previous_score = previous.total_score if previous is not None else None
            previous_regime = previous.regime if previous is not None else None
            score_change = (
                result.total_score - previous_score
                if previous_score is not None else None
            )

            data = result.to_dict()
            if existing:
                existing.total_score = result.total_score
                existing.regime = result.regime_result.regime.value
                existing.prev_score = previous_score
                existing.score_change = score_change
                existing.prev_regime = previous_regime
                existing.category_scores = data["category_scores"]
                existing.indicator_detail = data["indicator_detail"]
                existing.data_coverage = result.data_coverage
                existing.top_positive = sorted(
                    [
                        {"name": i.name, "contribution": i.contribution}
                        for i in result.indicator_scores if i.has_signal
                    ],
                    key=lambda item: item["contribution"], reverse=True,
                )[:5]
                existing.top_negative = sorted(
                    [
                        {"name": i.name, "contribution": i.contribution}
                        for i in result.indicator_scores if i.has_signal
                    ],
                    key=lambda item: item["contribution"],
                )[:5]
            else:
                br = BiasResult(
                    asset=result.asset,
                    date=datetime.combine(calc_date, datetime.min.time()),
                    timeframe=timeframe,
                    total_score=result.total_score,
                    regime=result.regime_result.regime.value,
                    prev_score=previous_score,
                    score_change=score_change,
                    prev_regime=previous_regime,
                    category_scores=data["category_scores"],
                    indicator_detail=data["indicator_detail"],
                    data_coverage=result.data_coverage,
                    top_positive=sorted(
                        [
                            {"name": i.name, "contribution": i.contribution}
                            for i in result.indicator_scores if i.has_signal
                        ],
                        key=lambda item: item["contribution"], reverse=True,
                    )[:5],
                    top_negative=sorted(
                        [
                            {"name": i.name, "contribution": i.contribution}
                            for i in result.indicator_scores if i.has_signal
                        ],
                        key=lambda item: item["contribution"],
                    )[:5],
                    framework_version=fw_version,
                )
                session.add(br)


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return None if np.isnan(f) or np.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _bias_to_dict(br) -> dict:
    """Convert a BiasResult ORM row to a plain dict (avoids DetachedInstanceError)."""
    return {
        "id":                br.id,
        "asset":             br.asset,
        "date":              br.date,
        "timeframe":         br.timeframe,
        "total_score":       br.total_score,
        "regime":            br.regime,
        "prev_score":        br.prev_score,
        "score_change":      br.score_change,
        "prev_regime":       br.prev_regime,
        "category_scores":   dict(br.category_scores or {}),
        "indicator_detail":  dict(br.indicator_detail or {}),
        "framework_version": br.framework_version,
        "data_coverage":     br.data_coverage,
    }


def get_latest_bias(asset: str, timeframe: str = "weekly") -> Optional[dict]:
    """Fetch the most recent bias result for an asset as a plain dict."""
    with get_session() as session:
        active_version = session.execute(
            select(FrameworkVersion.version)
            .where(FrameworkVersion.is_active == True)
            .order_by(desc(FrameworkVersion.version))
        ).scalar_one_or_none()
        conditions = [BiasResult.asset == asset, BiasResult.timeframe == timeframe]
        if active_version is not None:
            conditions.append(BiasResult.framework_version == active_version)
        result = session.execute(
            select(BiasResult)
            .where(*conditions)
            .order_by(desc(BiasResult.date))
        ).scalars().first()
        return _bias_to_dict(result) if result else None


def get_bias_history(asset: str, timeframe: str = "weekly", limit: int = 52) -> list[dict]:
    """Fetch historical bias results for an asset as plain dicts."""
    with get_session() as session:
        active_version = session.execute(
            select(FrameworkVersion.version)
            .where(FrameworkVersion.is_active == True)
            .order_by(desc(FrameworkVersion.version))
        ).scalar_one_or_none()
        conditions = [BiasResult.asset == asset, BiasResult.timeframe == timeframe]
        if active_version is not None:
            conditions.append(BiasResult.framework_version == active_version)
        results = session.execute(
            select(BiasResult)
            .where(*conditions)
            .order_by(desc(BiasResult.date))
            .limit(limit)
        ).scalars().all()
        return list(reversed([_bias_to_dict(r) for r in results]))
