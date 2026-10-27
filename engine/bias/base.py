"""
Market Bias Platform — Base Asset Bias Calculator
Common bias computation logic shared by SPX, NASDAQ, and GOLD engines.

Each indicator is scored to [-100, +100]:
  - Bullish for the asset → positive score
  - Bearish for the asset → negative score
  - Weight × score = category contribution

Final bias score = sum(weight_i × score_i) / sum(weight_i)  clamped to [-100, +100]
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from bias.regimes import RegimeResult, classify_regime
from metrics.statistics import clamp, zscore_to_score, percentile_to_score

logger = logging.getLogger(__name__)


# ── Indicator Score ────────────────────────────────────────────────────────────

@dataclass
class IndicatorScore:
    """Score for a single indicator."""
    name: str
    category: str
    raw_value: Optional[float]
    zscore: Optional[float]
    percentile: Optional[float]
    score: float          # [-100, +100] before weighting
    weight: float         # Category weight (0–1)
    contribution: float   # score × weight
    note: str = ""

    @property
    def has_signal(self) -> bool:
        """True when enough data exists to justify the computed score."""
        if self.raw_value is None:
            return False
        try:
            if np.isnan(self.raw_value):
                return False
        except TypeError:
            return False
        return (
            self.zscore is not None
            or self.percentile is not None
            or not np.isclose(self.score, 0.0)
        )


# ── Category Scores ────────────────────────────────────────────────────────────

@dataclass
class CategoryScore:
    """Aggregated score for an indicator category."""
    category: str
    weight: float
    raw_score: float       # Weighted average of indicator scores in this category
    contribution: float    # raw_score × weight
    indicators: list[IndicatorScore] = field(default_factory=list)


# ── Final Bias Result ──────────────────────────────────────────────────────────

@dataclass
class BiasCalculation:
    """Complete bias computation result for one asset."""
    asset: str
    timeframe: str
    calc_date: date
    total_score: float
    regime_result: RegimeResult
    category_scores: dict[str, CategoryScore]
    indicator_scores: list[IndicatorScore]
    data_coverage: float   # Fraction of indicators with data (0.0–1.0)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to JSON-serialisable dict for DB storage."""
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "calc_date": str(self.calc_date),
            "total_score": self.total_score,
            "regime": self.regime_result.regime.value,
            "data_coverage": self.data_coverage,
            "category_scores": {
                cat: {
                    "weight": cs.weight,
                    "raw_score": cs.raw_score,
                    "contribution": cs.contribution,
                }
                for cat, cs in self.category_scores.items()
            },
            "indicator_detail": {
                ind.name: {
                    "category": ind.category,
                    "raw_value": ind.raw_value,
                    "zscore": ind.zscore,
                    "percentile": ind.percentile,
                    "score": ind.score,
                    "weight": ind.weight,
                    "contribution": ind.contribution,
                    "note": ind.note,
                }
                for ind in self.indicator_scores
            },
        }


# ── Base Calculator ────────────────────────────────────────────────────────────

class AssetBiasCalculator(ABC):
    """
    Abstract base for asset-specific bias calculators.

    Subclasses define:
      - CATEGORY_WEIGHTS: {category: weight} (must sum to ~1.0 or will be normalised)
      - score_indicators(metrics): yield IndicatorScore objects per indicator
    """

    _abstract = True

    @property
    @abstractmethod
    def asset_name(self) -> str:
        """Asset identifier: SPX | NASDAQ | GOLD"""
        ...

    @property
    @abstractmethod
    def CATEGORY_WEIGHTS(self) -> dict[str, float]:
        """Default category weights. Will be overridden by active FrameworkVersion."""
        ...

    @abstractmethod
    def score_indicators(
        self,
        metrics: dict[str, Optional[float]],
        weights: dict[str, float],
    ) -> list[IndicatorScore]:
        """
        Given a flat dict of {indicator: latest_value} and the active category weights,
        return a list of IndicatorScore objects.
        """
        ...

    def compute(
        self,
        metrics: dict[str, Optional[float]],
        calc_date: date,
        timeframe: str = "weekly",
        custom_weights: dict[str, float] | None = None,
        regime_thresholds: dict | None = None,
    ) -> BiasCalculation:
        """
        Run the full bias computation pipeline.

        Args:
            metrics: Flat dict {indicator_name: latest_value_or_None}
            calc_date: The as-of date for this calculation
            timeframe: "weekly" or "monthly"
            custom_weights: Override category weights from framework version
            regime_thresholds: Override regime classification thresholds

        Returns:
            BiasCalculation with all scores and regime
        """
        weights = self._resolve_weights(custom_weights)
        indicator_scores = self.score_indicators(metrics, weights)

        # Aggregate by category
        category_scores: dict[str, CategoryScore] = {}
        for ind in indicator_scores:
            cat = ind.category
            if cat not in category_scores:
                category_scores[cat] = CategoryScore(
                    category=cat,
                    weight=weights.get(cat, 0.0),
                    raw_score=0.0,
                    contribution=0.0,
                    indicators=[],
                )
            category_scores[cat].indicators.append(ind)

        warnings: list[str] = []

        # Average indicator scores within each category
        for cat, cs in category_scores.items():
            valid_indicators = [
                i for i in cs.indicators
                if i.has_signal and not np.isnan(i.score)
            ]
            valid_scores = [i.score for i in valid_indicators]
            if not valid_scores:
                cs.raw_score = 0.0
                warnings.append(f"No valid data for category: {cat}")
            else:
                cs.raw_score = float(np.mean(valid_scores))
                for indicator in cs.indicators:
                    indicator.contribution = (
                        indicator.score * cs.weight / len(valid_indicators)
                        if indicator in valid_indicators else 0.0
                    )
            cs.contribution = cs.raw_score * cs.weight

        # Weighted total score
        total_weight = sum(
            cs.weight for cs in category_scores.values()
            if any(i.has_signal for i in cs.indicators)
        )
        if total_weight == 0:
            total_score = 0.0
            warnings.append("Total weight is zero — check framework weights")
        else:
            total_score = clamp(
                sum(cs.contribution for cs in category_scores.values()) / total_weight
            )

        # Data coverage
        total_indicators = len(indicator_scores)
        indicators_with_data = sum(1 for ind in indicator_scores if ind.has_signal)
        coverage = indicators_with_data / max(total_indicators, 1)

        regime_result = classify_regime(total_score, regime_thresholds)
        if coverage < 0.50:
            regime_result = classify_regime(float("nan"), regime_thresholds)
            regime_result.score = total_score
            regime_result.description = (
                f"Only {coverage:.0%} of model signals are usable; "
                "the directional score is withheld."
            )

        logger.info(
            "[%s] %s score=%.1f regime=%s coverage=%.0f%%",
            self.asset_name, timeframe, total_score,
            regime_result.regime.value, coverage * 100,
        )

        return BiasCalculation(
            asset=self.asset_name,
            timeframe=timeframe,
            calc_date=calc_date,
            total_score=total_score,
            regime_result=regime_result,
            category_scores=category_scores,
            indicator_scores=indicator_scores,
            data_coverage=coverage,
            warnings=warnings,
        )

    def _resolve_weights(self, custom_weights: dict[str, float] | None) -> dict[str, float]:
        """Use custom weights if provided, else defaults. Normalise to sum=1."""
        weights = dict(custom_weights) if custom_weights else dict(self.CATEGORY_WEIGHTS)
        total = sum(weights.values())
        if total == 0:
            return weights
        return {k: v / total for k, v in weights.items()}


# ── Scoring Helpers ────────────────────────────────────────────────────────────

def _get(metrics: dict, key: str, default=None):
    """Safe get from metrics dict."""
    return metrics.get(key, default)


def _zscore_score(z: Optional[float], multiplier: float = 25.0, invert: bool = False) -> float:
    """Convert Z-score to score, optionally inverting direction (bearish when high)."""
    if z is None or np.isnan(z):
        return 0.0
    score = zscore_to_score(z, multiplier)
    return -score if invert else score


def _rate_change_score(
    change_z: Optional[float],
    level_z: Optional[float],
    *,
    change_multiplier: float = 25.0,
    level_multiplier: float = 4.0,
) -> float:
    """Score rates by direction/magnitude, with level only a small modifier.

    A large rise is bearish and a large fall is bullish.  The current yield
    level cannot dominate or reverse that transition signal; it only applies
    a bounded valuation/opportunity-cost adjustment.  If change history is
    unavailable, return no signal instead of silently reverting to a level-
    only model.
    """
    if change_z is None or not np.isfinite(change_z):
        return 0.0
    level_adjustment = 0.0
    if level_z is not None and np.isfinite(level_z):
        level_adjustment = -float(np.clip(level_z, -2.5, 2.5)) * level_multiplier
    return clamp(-float(change_z) * change_multiplier + level_adjustment)


def _usd_direction_score(
    direction_z: Optional[float],
    level_z: Optional[float],
    shock_z: Optional[float],
    multiplier: float = 25.0,
    invert: bool = True,
) -> tuple[float, Optional[float]]:
    """Score USD direction once, using level/shock only as bounded modifiers.

    The signed momentum is mandatory and therefore always determines the
    sign. DXY level can confirm or damp the move by at most 20%; unusually
    large absolute moves can amplify it by at most another 20%.
    """
    if direction_z is None or not np.isfinite(direction_z):
        return 0.0, None

    level_factor = 1.0
    if level_z is not None and np.isfinite(level_z) and direction_z != 0:
        alignment = np.sign(direction_z) * float(np.clip(level_z / 2.0, -1.0, 1.0))
        level_factor += 0.20 * alignment

    shock_factor = 1.0
    if shock_z is not None and np.isfinite(shock_z):
        shock_factor += 0.10 * float(np.clip(shock_z, 0.0, 2.0))

    effective_z = float(direction_z * level_factor * shock_factor)
    score = clamp(effective_z * multiplier)
    return (-score if invert else score), effective_z


def _pct_score(pct: Optional[float], invert: bool = False) -> float:
    """Convert percentile rank to score, optionally inverting."""
    if pct is None or np.isnan(pct):
        return 0.0
    score = percentile_to_score(pct)
    return -score if invert else score


def _level_score(
    value: Optional[float],
    bullish_above: Optional[float] = None,
    bullish_below: Optional[float] = None,
    neutral_buffer: float = 0.0,
    max_score: float = 50.0,
) -> float:
    """
    Simple level-based score:
    - bullish_above: values above this threshold are bullish (positive score)
    - bullish_below: values below this threshold are bullish (negative score)
    Returns a score in [-max_score, +max_score].
    """
    if value is None or np.isnan(value):
        return 0.0
    if bullish_above is not None:
        if value > bullish_above + neutral_buffer:
            return max_score
        elif value < bullish_above - neutral_buffer:
            return -max_score
        else:
            return 0.0
    if bullish_below is not None:
        if value < bullish_below - neutral_buffer:
            return max_score
        elif value > bullish_below + neutral_buffer:
            return -max_score
        else:
            return 0.0
    return 0.0


def _gex_score(
    value: Optional[float],
    scale_millions: float,
    value_is_millions: bool,
    max_abs_score: float = 18.0,
) -> float:
    """Conservative GEX score after normalising providers to USD millions.

    Public OI/IV GEX is an estimate rather than observed dealer inventory, so
    it is capped below macro and breadth signals.
    """
    if value is None or np.isnan(value) or scale_millions <= 0:
        return 0.0
    value_millions = value if value_is_millions else value / 1_000_000
    return clamp(float(np.tanh(value_millions / scale_millions) * max_abs_score))
