"""
Market Bias Platform — NASDAQ Bias Calculator
Scores all indicator categories for the Nasdaq 100 (NDX/QQQ).

NASDAQ-specific considerations:
  - More rate-sensitive than SPX (longer duration, high-growth tech)
  - VXN (Nasdaq volatility) more relevant than VIX
  - QQQ positioning and flows
  - Higher DXY sensitivity (tech = global revenue)
  - Growth factor: USDJPY carry trade unwind hit NASDAQ harder
"""
from __future__ import annotations

import numpy as np
from typing import Optional

from bias.base import (
    AssetBiasCalculator, IndicatorScore,
    _get, _zscore_score, _pct_score, _level_score, _gex_score,
    _usd_direction_score, _rate_change_score,
)
from metrics.statistics import clamp, percentile_to_score


class NASDAQBiasCalculator(AssetBiasCalculator):

    _abstract = False

    @property
    def asset_name(self) -> str:
        return "NASDAQ"

    @property
    def CATEGORY_WEIGHTS(self) -> dict[str, float]:
        # NASDAQ: overweight rates (more rate-sensitive) and underweight breadth
        return {
            "liquidity":    1.0,
            "rates":        1.5,  # Higher rate sensitivity than SPX
            "usd":          1.0,
            "risk":         1.0,
            "breadth":      0.75,
            "options":      1.0,
            "positioning":  1.0,
            "flows":        1.0,
        }

    def score_indicators(
        self,
        metrics: dict[str, Optional[float]],
        weights: dict[str, float],
    ) -> list[IndicatorScore]:
        scores: list[IndicatorScore] = []

        # ── LIQUIDITY ─────────────────────────────────────────────────────
        cat = "liquidity"
        w = weights.get(cat, 0.125)

        nl_z = _get(metrics, "net_liquidity_zscore_1y")
        scores.append(IndicatorScore(
            name="net_liquidity_zscore", category=cat,
            raw_value=_get(metrics, "net_liquidity"),
            zscore=nl_z, percentile=_get(metrics, "net_liquidity_pct_1y"),
            score=_zscore_score(nl_z),
            weight=w, contribution=_zscore_score(nl_z) * w,
            note="Liquidity expansion = NASDAQ tailwind (high beta)",
        ))

        nl_4w_z = _get(metrics, "net_liquidity_4w_chg_zscore_1y")
        scores.append(IndicatorScore(
            name="net_liquidity_momentum_4w", category=cat,
            raw_value=_get(metrics, "net_liquidity_4w_chg"),
            zscore=nl_4w_z, percentile=None,
            score=_zscore_score(nl_4w_z),
            weight=w, contribution=_zscore_score(nl_4w_z) * w,
            note="Liquidity momentum — NASDAQ amplifies SPX liquidity response",
        ))

        rrp_z = _get(metrics, "on_rrp_zscore_1y")
        rrp_score = _zscore_score(rrp_z, invert=True)
        scores.append(IndicatorScore(
            name="on_rrp", category=cat,
            raw_value=_get(metrics, "on_rrp"),
            zscore=rrp_z, percentile=None,
            score=rrp_score, weight=w, contribution=rrp_score * w,
            note="Declining RRP → cash deployment into risk assets",
        ))

        # ── RATES ─────────────────────────────────────────────────────────
        # NASDAQ is more rate-sensitive — real yield impact is amplified
        cat = "rates"
        w = weights.get(cat, 0.1875)

        # 10Y real yield is THE key driver for growth/tech valuation
        ry_z = _get(metrics, "us_10y_real_yield_zscore_1y")
        ry_change_z = _get(metrics, "us_10y_real_yield_4w_chg_zscore_1y")
        ry_score = _rate_change_score(
            ry_change_z, ry_z, change_multiplier=38.0, level_multiplier=6.0,
        )
        scores.append(IndicatorScore(
            name="us_10y_real_yield", category=cat,
            raw_value=_get(metrics, "us_10y_real_yield"),
            zscore=ry_change_z, percentile=_get(metrics, "us_10y_real_yield_pct_1y"),
            score=ry_score, weight=w, contribution=ry_score * w,
            note="4W real-yield change leads; level is a bounded growth-valuation modifier",
        ))

        y5_ry_z = _get(metrics, "us_5y_real_yield_zscore_1y")
        y5_change_z = _get(metrics, "us_5y_real_yield_4w_chg_zscore_1y")
        y5_score = _rate_change_score(
            y5_change_z, y5_ry_z, change_multiplier=32.0, level_multiplier=5.0,
        )
        scores.append(IndicatorScore(
            name="us_5y_real_yield", category=cat,
            raw_value=_get(metrics, "us_5y_real_yield"),
            zscore=y5_change_z, percentile=None,
            score=y5_score, weight=w, contribution=y5_score * w,
            note="4W 5Y real-yield transition; level is a bounded modifier",
        ))

        y10_z = _get(metrics, "us_10y_yield_zscore_1y")
        y10_change_z = _get(metrics, "us_10y_yield_4w_chg_zscore_1y")
        y10_score = _rate_change_score(y10_change_z, y10_z)
        scores.append(IndicatorScore(
            name="us_10y_nominal_yield", category=cat,
            raw_value=_get(metrics, "us_10y_yield"),
            zscore=y10_change_z, percentile=None,
            score=y10_score, weight=w, contribution=y10_score * w,
            note="4W nominal-yield transition; level only adjusts valuation pressure",
        ))

        # Yield curve steepening signals recovery — positive for growth
        y2 = _get(metrics, "us_2y_yield")
        y10 = _get(metrics, "us_10y_yield")
        curve = (y10 - y2) if (y2 is not None and y10 is not None) else None
        curve_score = clamp((curve or 0) * 35) if curve is not None else 0.0
        scores.append(IndicatorScore(
            name="yield_curve_2y10y", category=cat,
            raw_value=curve, zscore=None, percentile=None,
            score=curve_score, weight=w, contribution=curve_score * w,
            note="Curve steepening = growth expectations = NASDAQ bullish",
        ))

        # ── USD ───────────────────────────────────────────────────────────
        cat = "usd"
        w = weights.get(cat, 0.125)

        dxy_direction_z = _get(metrics, "dxy_direction_strength_1y")
        dxy_z = _get(metrics, "dxy_zscore_1y")
        dxy_shock_z = _get(metrics, "dxy_shock_zscore_1y")
        usd_score, usd_effective_z = _usd_direction_score(
            dxy_direction_z, dxy_z, dxy_shock_z,
            multiplier=25.0, invert=True,
        )
        scores.append(IndicatorScore(
            name="usd_directional_pressure", category=cat,
            raw_value=_get(metrics, "dxy_signed_log_momentum"),
            zscore=usd_effective_z, percentile=None,
            score=usd_score, weight=w, contribution=usd_score * w,
            note=(
                "Signed DXY log momentum; level/shock only modify confidence. "
                "USD strength is a global-revenue and liquidity headwind"
            ),
        ))

        # USDJPY belongs to carry/risk, not the USD directional category.
        jpy_z = _get(metrics, "usdjpy_zscore_1y")
        carry_cat = "risk"
        carry_w = weights.get(carry_cat, 0.125)
        scores.append(IndicatorScore(
            name="usdjpy_carry", category=carry_cat,
            raw_value=_get(metrics, "usdjpy"),
            zscore=jpy_z, percentile=None,
            score=_zscore_score(jpy_z, multiplier=20.0),
            weight=carry_w,
            contribution=_zscore_score(jpy_z, multiplier=20.0) * carry_w,
            note="USDJPY collapse = JPY carry unwind = tech selling pressure",
        ))

        # ── RISK ──────────────────────────────────────────────────────────
        cat = "risk"
        w = weights.get(cat, 0.125)

        # VXN more relevant for NASDAQ than VIX
        vxn_z = _get(metrics, "vxn_zscore_1y")
        scores.append(IndicatorScore(
            name="vxn", category=cat,
            raw_value=_get(metrics, "vxn"),
            zscore=vxn_z, percentile=_get(metrics, "vxn_pct_1y"),
            score=_zscore_score(vxn_z, invert=True, multiplier=28.0),
            weight=w, contribution=_zscore_score(vxn_z, invert=True, multiplier=28.0) * w,
            note="VXN is NASDAQ-specific volatility — key risk indicator",
        ))

        # VXN/VIX spread: when VXN >> VIX, NASDAQ-specific fear is elevated
        vix = _get(metrics, "vix")
        vxn = _get(metrics, "vxn")
        vxn_vix_ratio = None
        if vix and vxn and vix > 0:
            vxn_vix_ratio = vxn / vix
            # ratio > 1.15 = elevated NASDAQ fear = bearish
            vxn_vix_z = _get(metrics, 'vxn_vix_ratio_zscore_1y')
            if vxn_vix_z is not None:
                vxn_ratio_score = clamp(-vxn_vix_z * 25)  # inverted: high ratio = more NQ fear = bearish
            else:
                vxn_ratio_score = clamp((1.1 - vxn_vix_ratio) * 120)  # reduced multiplier fallback
        else:
            vxn_ratio_score = 0.0
        scores.append(IndicatorScore(
            name="vxn_vix_ratio", category=cat,
            raw_value=vxn_vix_ratio,
            zscore=None, percentile=None,
            score=vxn_ratio_score, weight=w, contribution=vxn_ratio_score * w,
            note="VXN/VIX >1.1 = excess NASDAQ fear vs SPX = headwind",
        ))


        hy_z = _get(metrics, "hy_oas_zscore_1y")
        scores.append(IndicatorScore(
            name="hy_oas", category=cat,
            raw_value=_get(metrics, "hy_oas"),
            zscore=hy_z, percentile=None,
            score=_zscore_score(hy_z, invert=True),
            weight=w, contribution=_zscore_score(hy_z, invert=True) * w,
            note="HY spreads signal credit conditions affecting growth financing",
        ))

        # ── BREADTH ───────────────────────────────────────────────────────
        cat = "breadth"
        w = weights.get(cat, 0.09375)

        mcclellan = _get(metrics, "mcclellan_oscillator")
        mccl_std = _get(metrics, 'mcclellan_std_1y') or 1.5  # dynamic from engine, fallback 1.5
        mcclellan_score = clamp((mcclellan or 0) / mccl_std * 25) if mcclellan is not None else 0.0
        scores.append(IndicatorScore(
            name="mcclellan_oscillator", category=cat,
            raw_value=mcclellan, zscore=None, percentile=None,
            score=mcclellan_score, weight=w, contribution=mcclellan_score * w,
        ))

        pct_above_200 = _get(metrics, "pct_above_200ma")
        pct_200_score = percentile_to_score(pct_above_200) if pct_above_200 is not None else 0.0
        scores.append(IndicatorScore(
            name="pct_above_200ma", category=cat,
            raw_value=pct_above_200, zscore=None, percentile=pct_above_200,
            score=pct_200_score, weight=w, contribution=pct_200_score * w,
        ))

        # ── OPTIONS ───────────────────────────────────────────────────────
        cat = "options"
        w = weights.get(cat, 0.125)

        # GEX: positive = MM long gamma = suppressed volatility = bullish
        qqq_gex = _get(metrics, "qqq_gex")
        if qqq_gex is not None:
            gex_score = _gex_score(qqq_gex, scale_millions=400, value_is_millions=False)
            note_str = (
                "Preferred QQQ GEX analytics: same-day FlashAlpha, "
                "Yahoo OI/IV model fallback (USD)"
            )
        else:
            qqq_gex = _get(metrics, "qqq_net_gex_fa")
            gex_score = _gex_score(qqq_gex, scale_millions=400, value_is_millions=True)
            note_str = "Legacy Yahoo GEX fallback (USD millions)"
        scores.append(IndicatorScore(
            name="qqq_gex", category=cat,
            raw_value=qqq_gex, zscore=None, percentile=None,
            score=gex_score, weight=w, contribution=gex_score * w,
            note=note_str,
        ))

        # Gamma Flip
        gamma_flip = _get(metrics, "qqq_gamma_flip")
        if gamma_flip is not None:
            qqq_close = _get(metrics, "qqq_close")
            if qqq_close is not None and gamma_flip is not None:
                distance_pct = (qqq_close - gamma_flip) / gamma_flip * 100  # % distance from flip
                flip_score = clamp(distance_pct * 10)  # 1% above flip = +10, 3% = +30
                flip_note = f"QQQ distance from estimated Gamma Flip ({gamma_flip:.0f}): {distance_pct:+.2f}%"
            else:
                flip_score = 0.0
                flip_note = "Missing close or gamma flip"
            
            scores.append(IndicatorScore(
                name="qqq_gamma_flip", category=cat,
                raw_value=gamma_flip, zscore=None, percentile=None,
                score=flip_score, weight=w, contribution=flip_score * w,
                note=flip_note,
            ))

        qqq_pc_z = _get(metrics, "qqq_pc_ratio_oi_zscore_1y")
        scores.append(IndicatorScore(
            name="qqq_pc_ratio", category=cat,
            raw_value=_get(metrics, "qqq_pc_ratio_oi"),
            zscore=qqq_pc_z, percentile=None,
            score=_zscore_score(qqq_pc_z, invert=True),
            weight=w, contribution=_zscore_score(qqq_pc_z, invert=True) * w,
        ))

        cboe_pc_z = _get(metrics, "cboe_total_pc_zscore_1y")
        scores.append(IndicatorScore(
            name="cboe_total_pc", category=cat,
            raw_value=_get(metrics, "cboe_total_pc"),
            zscore=cboe_pc_z, percentile=None,
            score=_zscore_score(cboe_pc_z, invert=True),
            weight=w, contribution=_zscore_score(cboe_pc_z, invert=True) * w,
        ))

        # ── POSITIONING ───────────────────────────────────────────────────
        cat = "positioning"
        w = weights.get(cat, 0.125)

        cot_nq_idx = _get(metrics, "cot_nasdaq_net_leveraged_cot_index")
        if cot_nq_idx is not None:
            cot_nq_score = clamp((50 - cot_nq_idx) * 1.5)
        else:
            cot_nq_score = 0.0
        scores.append(IndicatorScore(
            name="cot_nasdaq_leveraged", category=cat,
            raw_value=_get(metrics, "cot_nasdaq_net_leveraged"),
            zscore=None, percentile=cot_nq_idx,
            score=cot_nq_score, weight=w, contribution=cot_nq_score * w,
            note="COT NQ leveraged positioning index",
        ))

        cot_am_z = _get(metrics, "cot_nasdaq_net_asset_mgr_zscore_1y")
        scores.append(IndicatorScore(
            name="cot_nasdaq_asset_mgr", category=cat,
            raw_value=_get(metrics, "cot_nasdaq_net_asset_mgr"),
            zscore=cot_am_z, percentile=None,
            score=_zscore_score(cot_am_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(cot_am_z, multiplier=20.0) * w,
        ))

        # ── FLOWS ─────────────────────────────────────────────────────────
        cat = "flows"
        w = weights.get(cat, 0.125)

        qqq_z = _get(metrics, "qqq_close_zscore_1y")
        scores.append(IndicatorScore(
            name="qqq_momentum", category=cat,
            raw_value=_get(metrics, "qqq_close"),
            zscore=qqq_z, percentile=None,
            score=_zscore_score(qqq_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(qqq_z, multiplier=20.0) * w,
        ))

        qqq_4w_z = _get(metrics, "qqq_close_4w_chg_zscore_1y")
        scores.append(IndicatorScore(
            name="qqq_return_momentum_4w", category=cat,
            raw_value=_get(metrics, "qqq_close_chg_4w"),
            zscore=qqq_4w_z, percentile=None,
            score=_zscore_score(qqq_4w_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(qqq_4w_z, multiplier=20.0) * w,
            note="QQQ 4W return momentum; not an ETF flow measurement",
        ))

        turnover_z = _get(metrics, "qqq_signed_turnover_proxy_zscore_1y")
        turnover_score = _zscore_score(turnover_z, multiplier=15.0)
        scores.append(IndicatorScore(
            name="qqq_signed_turnover_proxy", category=cat,
            raw_value=_get(metrics, "qqq_signed_turnover_proxy"),
            zscore=turnover_z, percentile=None,
            score=turnover_score,
            weight=w, contribution=turnover_score * w,
            note="Weekly signed dollar turnover proxy; not ETF creations/redemptions",
        ))

        return scores
