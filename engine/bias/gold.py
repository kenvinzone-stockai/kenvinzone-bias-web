"""
Market Bias Platform — GOLD Bias Calculator
Scores all indicator categories for Gold (XAUUSD/GC).

Gold-specific logic:
  LIQUIDITY   → Money supply expansion → gold bullish (inflation hedge)
  RATES       → Real yields are the PRIMARY driver (inverse relationship)
  USD         → USD weakens → gold strengthens (inverse)
  RISK        → Fear/crisis → gold as safe haven (nuanced — not always)
  BREADTH     → Market breadth divergence → flight to gold
  OPTIONS     → GLD options, GEX for gold ETF
  POSITIONING → COT Gold COMEX non-commercial positioning
  FLOWS       → Price-momentum proxies; no observed ETF creations/redemptions
  GOLD_SPECIFIC → CB purchases, COMEX OI, GLD holdings, gold-silver ratio
"""
from __future__ import annotations

import numpy as np
from typing import Optional

from bias.base import (
    AssetBiasCalculator, IndicatorScore,
    _get, _zscore_score, _pct_score, _gex_score, _usd_direction_score,
    _rate_change_score,
)
from metrics.statistics import clamp, percentile_to_score


class GoldBiasCalculator(AssetBiasCalculator):

    _abstract = False

    @property
    def asset_name(self) -> str:
        return "GOLD"

    @property
    def CATEGORY_WEIGHTS(self) -> dict[str, float]:
        # Gold: heavily weights real yields and USD; adds gold-specific category
        return {
            "liquidity":      1.0,
            "rates":          2.0,   # Real yield is the dominant gold driver
            "usd":            2.0,   # USD is the second-largest driver
            "risk":           0.75,  # Gold safe-haven bid is situational
            "breadth":        0.25,  # Less relevant for gold
            "options":        0.75,
            "positioning":    1.5,   # COT gold positioning is highly predictive
            "flows":          1.5,   # ETF flows and CB purchases matter a lot
            "gold_specific":  1.5,   # Gold-native metrics
        }

    def score_indicators(
        self,
        metrics: dict[str, Optional[float]],
        weights: dict[str, float],
    ) -> list[IndicatorScore]:
        scores: list[IndicatorScore] = []

        # ── LIQUIDITY ─────────────────────────────────────────────────────
        cat = "liquidity"
        w = weights.get(cat, 0.09)

        nl_z = _get(metrics, "net_liquidity_zscore_1y")
        scores.append(IndicatorScore(
            name="net_liquidity_zscore", category=cat,
            raw_value=_get(metrics, "net_liquidity"),
            zscore=nl_z, percentile=None,
            score=_zscore_score(nl_z),
            weight=w, contribution=_zscore_score(nl_z) * w,
            note="Liquidity expansion → inflation hedge demand for gold",
        ))

        m2_z = _get(metrics, "us_m2_zscore_1y")
        scores.append(IndicatorScore(
            name="us_m2", category=cat,
            raw_value=_get(metrics, "us_m2"),
            zscore=m2_z, percentile=None,
            score=_zscore_score(m2_z),
            weight=w, contribution=_zscore_score(m2_z) * w,
            note="M2 growth → monetary debasement → gold bullish",
        ))

        # ── RATES — PRIMARY GOLD DRIVER ───────────────────────────────────
        cat = "rates"
        w = weights.get(cat, 0.18)

        # STRONGEST SIGNAL: Real 10Y yield (inverse of gold)
        ry_z = _get(metrics, "us_10y_real_yield_zscore_1y")
        ry_change_z = _get(metrics, "us_10y_real_yield_4w_chg_zscore_1y")
        ry_score = _rate_change_score(
            ry_change_z, ry_z, change_multiplier=32.0, level_multiplier=5.0,
        )
        scores.append(IndicatorScore(
            name="us_10y_real_yield", category=cat,
            raw_value=_get(metrics, "us_10y_real_yield"),
            zscore=ry_change_z, percentile=_get(metrics, "us_10y_real_yield_pct_1y"),
            score=ry_score, weight=w, contribution=ry_score * w,
            note="MOST IMPORTANT: 4W real-yield direction/magnitude; level is secondary",
        ))

        ry5_z = _get(metrics, "us_5y_real_yield_zscore_1y")
        ry5_change_z = _get(metrics, "us_5y_real_yield_4w_chg_zscore_1y")
        ry5_score = _rate_change_score(
            ry5_change_z, ry5_z, change_multiplier=28.0, level_multiplier=4.0,
        )
        scores.append(IndicatorScore(
            name="us_5y_real_yield", category=cat,
            raw_value=_get(metrics, "us_5y_real_yield"),
            zscore=ry5_change_z, percentile=None,
            score=ry5_score, weight=w, contribution=ry5_score * w,
            note="4W 5Y real-yield transition: gold opportunity-cost impulse",
        ))

        # Breakeven remains available in the engine's diagnostic metrics.
        # Do not give its level an independent directional vote: nominal minus
        # real yield includes inflation/risk/liquidity compensation, and a high
        # level alone does not establish a bullish gold impulse. Real yields
        # and USD retain their own votes. Removing this row (rather than adding
        # a zero score) also avoids diluting the two real-yield observations.

        # ── USD — SECOND MAJOR DRIVER ─────────────────────────────────────
        cat = "usd"
        w = weights.get(cat, 0.18)

        dxy_direction_z = _get(metrics, "dxy_direction_strength_1y")
        dxy_z = _get(metrics, "dxy_zscore_1y")
        dxy_shock_z = _get(metrics, "dxy_shock_zscore_1y")
        usd_score, usd_effective_z = _usd_direction_score(
            dxy_direction_z, dxy_z, dxy_shock_z,
            multiplier=32.0, invert=True,
        )
        scores.append(IndicatorScore(
            name="usd_directional_pressure", category=cat,
            raw_value=_get(metrics, "dxy_signed_log_momentum"),
            zscore=usd_effective_z, percentile=None,
            score=usd_score, weight=w, contribution=usd_score * w,
            note=(
                "Signed DXY log momentum is the sole USD direction vote for gold; "
                "DXY level and absolute shock are bounded confidence modifiers"
            ),
        ))

        # ── RISK / SAFE HAVEN ─────────────────────────────────────────────
        cat = "risk"
        w = weights.get(cat, 0.07)

        # VIX: fear drives safe-haven demand for gold — BUT not always linear
        vix_z = _get(metrics, "vix_zscore_1y")
        vix_val = _get(metrics, "vix")
        vix_pct = _get(metrics, 'vix_pct_1y')  # percentile rank 0-100
        if vix_pct is not None:
            if vix_pct > 80:  # VIX in top 20% = fear = gold bullish
                vix_score = clamp((vix_pct - 50) * 1.5)
            elif vix_pct < 20:  # VIX very low = complacency
                vix_score = 0.0
            else:
                vix_score = clamp((vix_pct - 50) * 0.8)
        else:
            # fallback to old static threshold
            if vix_val and vix_val > 20:
                vix_score = _zscore_score(vix_z, multiplier=15.0)  # mild positive for gold
            elif vix_val and vix_val < 15:
                vix_score = 0.0  # Low VIX: risk-on environment, gold less interesting
            else:
                vix_score = 0.0
        scores.append(IndicatorScore(
            name="vix", category=cat,
            raw_value=vix_val, zscore=vix_z, percentile=None,
            score=vix_score, weight=w, contribution=vix_score * w,
            note="High VIX (>20) can drive gold safe-haven demand",
        ))

        # HY spreads widening = credit stress = gold safe haven
        hy_z = _get(metrics, "hy_oas_zscore_1y")
        scores.append(IndicatorScore(
            name="hy_oas", category=cat,
            raw_value=_get(metrics, "hy_oas"),
            zscore=hy_z, percentile=None,
            score=_zscore_score(hy_z, multiplier=15.0),  # wider spreads → gold positive
            weight=w, contribution=_zscore_score(hy_z, multiplier=15.0) * w,
            note="Credit stress → flight to gold safety",
        ))

        # MOVE index: Treasury volatility = macro uncertainty = gold bid
        move_z = _get(metrics, "move_zscore_1y")
        scores.append(IndicatorScore(
            name="move_index", category=cat,
            raw_value=_get(metrics, "move"),
            zscore=move_z, percentile=None,
            score=_zscore_score(move_z, multiplier=15.0),
            weight=w, contribution=_zscore_score(move_z, multiplier=15.0) * w,
            note="High MOVE = rate uncertainty = gold as store of value",
        ))

        # ── BREADTH ───────────────────────────────────────────────────────
        cat = "breadth"
        w = weights.get(cat, 0.02)

        # SPX breadth divergence: when SPX is weak but gold strong = flight to safety
        mcclellan = _get(metrics, "mcclellan_oscillator")
        # For gold, negative breadth is mildly bullish (risk-off flows)
        mccl_std = _get(metrics, 'mcclellan_std_1y') or 3.0  # dynamic from engine, fallback 3.0
        mcclellan_score = clamp(-(mcclellan or 0) / mccl_std * 25) if mcclellan is not None else 0.0
        scores.append(IndicatorScore(
            name="mcclellan_oscillator_inverse", category=cat,
            raw_value=mcclellan, zscore=None, percentile=None,
            score=mcclellan_score, weight=w, contribution=mcclellan_score * w,
            note="Weak market breadth → flight to gold (inverse signal)",
        ))

        # ── OPTIONS ───────────────────────────────────────────────────────
        cat = "options"
        w = weights.get(cat, 0.07)

        # GEX
        gld_gex = _get(metrics, "gld_gex")
        if gld_gex is not None:
            gex_score = _gex_score(gld_gex, scale_millions=100, value_is_millions=False)
            note_str = (
                "Preferred GLD GEX analytics: same-day FlashAlpha, "
                "Yahoo OI/IV model fallback (USD)"
            )
        else:
            gld_gex = _get(metrics, "gld_net_gex_fa")
            gex_score = _gex_score(gld_gex, scale_millions=100, value_is_millions=True)
            note_str = "Legacy Yahoo GEX fallback (USD millions)"
        scores.append(IndicatorScore(
            name="gld_gex", category=cat,
            raw_value=gld_gex, zscore=None, percentile=None,
            score=gex_score, weight=w, contribution=gex_score * w,
            note=note_str,
        ))

        # Gamma Flip
        gamma_flip = _get(metrics, "gld_gamma_flip")
        if gamma_flip is not None:
            gld_close = _get(metrics, "gld_close")
            if gld_close is not None and gamma_flip is not None:
                distance_pct = (gld_close - gamma_flip) / gamma_flip * 100  # % distance from flip
                flip_score = clamp(distance_pct * 10)  # 1% above flip = +10, 3% = +30
                flip_note = f"GLD distance from estimated Gamma Flip ({gamma_flip:.0f}): {distance_pct:+.2f}%"
            else:
                flip_score = 0.0
                flip_note = "Missing close or gamma flip"
            
            scores.append(IndicatorScore(
                name="gld_gamma_flip", category=cat,
                raw_value=gamma_flip, zscore=None, percentile=None,
                score=flip_score, weight=w, contribution=flip_score * w,
                note=flip_note,
            ))

        gld_pc_z = _get(metrics, "gld_pc_ratio_oi_zscore_1y")
        scores.append(IndicatorScore(
            name="gld_pc_ratio", category=cat,
            raw_value=_get(metrics, "gld_pc_ratio_oi"),
            zscore=gld_pc_z, percentile=None,
            score=_zscore_score(gld_pc_z, invert=True),
            weight=w, contribution=_zscore_score(gld_pc_z, invert=True) * w,
        ))

        # ── POSITIONING ───────────────────────────────────────────────────
        cat = "positioning"
        w = weights.get(cat, 0.14)

        # COT Gold Non-Commercial: positioning index (0=extreme short, 100=extreme long)
        cot_gold_idx = _get(metrics, "cot_gold_net_noncommercial_cot_index")
        if cot_gold_idx is not None:
            # Extreme short = bullish fuel; extreme long = caution
            cot_score = clamp((50 - cot_gold_idx) * 1.5)
        else:
            cot_score = 0.0
        scores.append(IndicatorScore(
            name="cot_gold_noncommercial", category=cat,
            raw_value=_get(metrics, "cot_gold_net_noncommercial"),
            zscore=None, percentile=cot_gold_idx,
            score=cot_score, weight=w, contribution=cot_score * w,
            note="COT Gold: extreme shorts = squeeze fuel; extreme longs = crowded",
        ))

        # COT Gold net trend (Z-score)
        cot_gold_z = _get(metrics, "cot_gold_net_noncommercial_zscore_1y")
        scores.append(IndicatorScore(
            name="cot_gold_trend", category=cat,
            raw_value=_get(metrics, "cot_gold_net_noncommercial"),
            zscore=cot_gold_z, percentile=None,
            score=_zscore_score(cot_gold_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(cot_gold_z, multiplier=20.0) * w,
            note="COT trend: rising spec longs = momentum in gold",
        ))

        # ── FLOWS ─────────────────────────────────────────────────────────
        cat = "flows"
        w = weights.get(cat, 0.14)

        # GLD price momentum (market trend, not observed ETF flow)
        gld_z = _get(metrics, "gld_close_zscore_1y")
        scores.append(IndicatorScore(
            name="gld_momentum", category=cat,
            raw_value=_get(metrics, "gld_close"),
            zscore=gld_z, percentile=None,
            score=_zscore_score(gld_z, multiplier=25.0),
            weight=w, contribution=_zscore_score(gld_z, multiplier=25.0) * w,
            note="GLD price trend; this is not observed ETF creations/redemptions",
        ))

        gld_4w_z = _get(metrics, "gld_close_4w_chg_zscore_1y")
        scores.append(IndicatorScore(
            name="gld_return_momentum_4w", category=cat,
            raw_value=_get(metrics, "gld_close_chg_4w"),
            zscore=gld_4w_z, percentile=None,
            score=_zscore_score(gld_4w_z, multiplier=25.0),
            weight=w, contribution=_zscore_score(gld_4w_z, multiplier=25.0) * w,
            note="GLD 4W return momentum; not an ETF flow measurement",
        ))

        turnover_z = _get(metrics, "gld_signed_turnover_proxy_zscore_1y")
        turnover_score = _zscore_score(turnover_z, multiplier=15.0)
        scores.append(IndicatorScore(
            name="gld_signed_turnover_proxy", category=cat,
            raw_value=_get(metrics, "gld_signed_turnover_proxy"),
            zscore=turnover_z, percentile=None,
            score=turnover_score,
            weight=w, contribution=turnover_score * w,
            note="Weekly signed dollar turnover proxy; not ETF creations/redemptions",
        ))

        # Gold futures momentum
        gc_z = _get(metrics, "gold_futures_zscore_1y")
        scores.append(IndicatorScore(
            name="gold_futures_momentum", category=cat,
            raw_value=_get(metrics, "gold_futures"),
            zscore=gc_z, percentile=_get(metrics, "gold_futures_pct_1y"),
            score=_zscore_score(gc_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(gc_z, multiplier=20.0) * w,
        ))

        # ── GOLD-SPECIFIC ─────────────────────────────────────────────────
        cat = "gold_specific"
        w = weights.get(cat, 0.14)

        # Gold-Silver Ratio: very high ratio = gold outperforming silver = flight to safety
        gold = _get(metrics, "gold_futures")
        silver = _get(metrics, "silver")
        if gold and silver and silver > 0:
            gsr = gold / silver
        else:
            gsr = None
        gsr_z = _get(metrics, 'gold_silver_ratio_zscore_1y')  # dynamic from engine
        if gsr_z is None and gsr is not None:
            gsr_z = (gsr - 75) / 15  # fallback
        scores.append(IndicatorScore(
            name="gold_silver_ratio", category=cat,
            raw_value=gsr, zscore=gsr_z, percentile=None,
            score=_zscore_score(gsr_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(gsr_z, multiplier=20.0) * w,
            note="High GSR = gold outperforming silver = safe-haven demand = bullish gold",
        ))

        # COMEX OI: rising OI in futures = growing interest = bullish
        comex_oi_z = _get(metrics, "cot_gold_open_interest_zscore_1y")
        scores.append(IndicatorScore(
            name="comex_open_interest", category=cat,
            raw_value=_get(metrics, "cot_gold_open_interest"),
            zscore=comex_oi_z, percentile=None,
            score=_zscore_score(comex_oi_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(comex_oi_z, multiplier=20.0) * w,
            note="Rising COMEX OI = increasing speculative interest in gold",
        ))

        # Gold vs SPX momentum divergence
        # Rising gold while SPX falling = safe-haven confirmation
        gold_z = _get(metrics, "gold_futures_zscore_1y")
        spx_z = _get(metrics, "spx_close_zscore_1y")
        divergence = None
        if gold_z is not None and spx_z is not None:
            divergence = gold_z - spx_z  # positive = gold outperforming
            div_score = clamp(divergence * 20)
        else:
            div_score = 0.0
        scores.append(IndicatorScore(
            name="gold_spx_divergence", category=cat,
            raw_value=divergence,
            zscore=None, percentile=None,
            score=div_score, weight=w, contribution=div_score * w,
            note="Gold outperforming SPX (positive divergence) = safe-haven regime",
        ))

        # Copper-Gold ratio: falling ratio = growth pessimism = gold bullish
        copper = _get(metrics, "copper")
        if copper and gold and gold > 0:
            cg_ratio = copper / gold
            cg_z = _get(metrics, 'copper_gold_ratio_zscore_1y')  # dynamic from engine
            if cg_z is None:
                cg_z = (cg_ratio - 0.0018) / 0.0004  # fallback
        else:
            cg_ratio = None
            cg_z = None
        scores.append(IndicatorScore(
            name="copper_gold_ratio", category=cat,
            raw_value=cg_ratio, zscore=cg_z, percentile=None,
            score=_zscore_score(cg_z, invert=True, multiplier=20.0) if cg_z else 0.0,
            weight=w,
            contribution=(_zscore_score(cg_z, invert=True, multiplier=20.0) if cg_z else 0.0) * w,
            note="Falling copper-gold ratio = growth pessimism = gold bullish",
        ))

        return scores
