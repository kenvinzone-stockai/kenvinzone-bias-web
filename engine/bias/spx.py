"""
Market Bias Platform — SPX Bias Calculator
Scores all indicator categories for the S&P 500.

Category logic:
  LIQUIDITY   → Bullish when net liquidity rising, ON RRP falling, TGA drawing down
  RATES       → Nuanced: cutting cycle bullish, but high/rising rates can be bearish
  USD         → Rising DXY generally bearish for SPX (risk-off)
  RISK        → Low VIX, tight spreads = bullish; high VIX/wide spreads = bearish
  BREADTH     → Strong breadth = bullish confirmation
  OPTIONS     → Positive GEX, low P/C = bullish; negative GEX, high P/C = bearish
  POSITIONING → Crowded longs can be contra-indicator; extreme shorts = fuel for squeeze
  FLOWS       → Price/rotation proxies only; no observed ETF creations/redemptions
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


class SPXBiasCalculator(AssetBiasCalculator):

    _abstract = False

    @property
    def asset_name(self) -> str:
        return "SPX"

    @property
    def CATEGORY_WEIGHTS(self) -> dict[str, float]:
        # Equal weight across 8 categories — adjustable in Framework Editor
        return {
            "liquidity":    1.0,
            "rates":        1.0,
            "usd":          1.0,
            "risk":         1.0,
            "breadth":      1.0,
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

        # Net Liquidity Z-score: rising liquidity = bullish
        nl_z = _get(metrics, "net_liquidity_zscore_1y")
        scores.append(IndicatorScore(
            name="net_liquidity_zscore", category=cat,
            raw_value=_get(metrics, "net_liquidity"),
            zscore=nl_z, percentile=_get(metrics, "net_liquidity_pct_1y"),
            score=_zscore_score(nl_z),
            weight=w, contribution=_zscore_score(nl_z) * w,
            note="Rising net liquidity → bullish for equities",
        ))

        # Net Liquidity 4W momentum
        nl_4w = _get(metrics, "net_liquidity_4w_chg")
        nl_4w_z = _get(metrics, "net_liquidity_4w_chg_zscore_1y")
        scores.append(IndicatorScore(
            name="net_liquidity_momentum_4w", category=cat,
            raw_value=nl_4w, zscore=nl_4w_z, percentile=None,
            score=_zscore_score(nl_4w_z),
            weight=w, contribution=_zscore_score(nl_4w_z) * w,
            note="4W net liquidity momentum",
        ))

        # ON RRP: declining = bullish (cash leaving Fed → entering markets)
        rrp_z = _get(metrics, "on_rrp_zscore_1y")
        rrp_score = _zscore_score(rrp_z, invert=True)  # falling RRP = bullish
        scores.append(IndicatorScore(
            name="on_rrp", category=cat,
            raw_value=_get(metrics, "on_rrp"),
            zscore=rrp_z, percentile=_get(metrics, "on_rrp_pct_1y"),
            score=rrp_score, weight=w, contribution=rrp_score * w,
            note="Declining ON RRP → cash moving into markets → bullish",
        ))

        # Fed Balance Sheet momentum: expanding = bullish
        bs_z = _get(metrics, "fed_balance_sheet_zscore_1y")
        scores.append(IndicatorScore(
            name="fed_balance_sheet", category=cat,
            raw_value=_get(metrics, "fed_balance_sheet"),
            zscore=bs_z, percentile=None,
            score=_zscore_score(bs_z),
            weight=w, contribution=_zscore_score(bs_z) * w,
            note="Expanding Fed BS → monetary tailwind",
        ))

        # ── RATES ─────────────────────────────────────────────────────────
        cat = "rates"
        w = weights.get(cat, 0.125)

        # Yield transition: magnitude and direction lead; level is only a
        # bounded valuation modifier. High-but-falling yields can therefore
        # improve bias instead of remaining permanently bearish.
        y10_z = _get(metrics, "us_10y_yield_zscore_1y")
        y10_change_z = _get(metrics, "us_10y_yield_4w_chg_zscore_1y")
        y10_score = _rate_change_score(y10_change_z, y10_z)
        scores.append(IndicatorScore(
            name="us_10y_yield", category=cat,
            raw_value=_get(metrics, "us_10y_yield"),
            zscore=y10_change_z, percentile=_get(metrics, "us_10y_yield_pct_1y"),
            score=y10_score, weight=w, contribution=y10_score * w,
            note="4W yield change leads; current level is a bounded valuation modifier",
        ))

        # Real-yield transition receives a slightly larger change multiplier.
        ry_z = _get(metrics, "us_10y_real_yield_zscore_1y")
        ry_change_z = _get(metrics, "us_10y_real_yield_4w_chg_zscore_1y")
        ry_score = _rate_change_score(
            ry_change_z, ry_z, change_multiplier=30.0, level_multiplier=5.0,
        )
        scores.append(IndicatorScore(
            name="us_10y_real_yield", category=cat,
            raw_value=_get(metrics, "us_10y_real_yield"),
            zscore=ry_change_z, percentile=None,
            score=ry_score, weight=w, contribution=ry_score * w,
            note="4W real-yield change leads; level only adjusts valuation pressure",
        ))

        # Yield curve (2Y-10Y spread): steepening = bullish, inversion = bearish
        y2 = _get(metrics, "us_2y_yield")
        y10 = _get(metrics, "us_10y_yield")
        curve = (y10 - y2) if (y2 is not None and y10 is not None) else None
        curve_score = clamp((curve or 0) * 35) if curve is not None else 0.0  # +2% spread → +100
        scores.append(IndicatorScore(
            name="yield_curve_2y10y", category=cat,
            raw_value=curve, zscore=None, percentile=None,
            score=curve_score, weight=w, contribution=curve_score * w,
            note="Steepening 2Y-10Y curve → bullish economic outlook",
        ))

        # SOFR vs FFR: spread indicates funding stress
        sofr = _get(metrics, "sofr")
        ffr = _get(metrics, "fed_funds_rate")
        sofr_spread = (sofr - ffr) if (sofr is not None and ffr is not None) else None
        sofr_score = clamp(-(sofr_spread or 0) * 300) if sofr_spread is not None else 0.0
        scores.append(IndicatorScore(
            name="sofr_ffr_spread", category=cat,
            raw_value=sofr_spread, zscore=None, percentile=None,
            score=sofr_score, weight=w, contribution=sofr_score * w,
            note="SOFR-FFR spread: funding stress indicator",
        ))

        # ── USD ───────────────────────────────────────────────────────────
        cat = "usd"
        w = weights.get(cat, 0.125)

        # One USD vote: signed 4W/13W log momentum sets direction. DXY level
        # and absolute shock only modify magnitude, so they cannot double-count
        # or flip the directional signal.
        dxy_direction_z = _get(metrics, "dxy_direction_strength_1y")
        dxy_z = _get(metrics, "dxy_zscore_1y")
        dxy_shock_z = _get(metrics, "dxy_shock_zscore_1y")
        usd_score, usd_effective_z = _usd_direction_score(
            dxy_direction_z, dxy_z, dxy_shock_z,
            multiplier=22.0, invert=True,
        )
        scores.append(IndicatorScore(
            name="usd_directional_pressure", category=cat,
            raw_value=_get(metrics, "dxy_signed_log_momentum"),
            zscore=usd_effective_z, percentile=None,
            score=usd_score, weight=w, contribution=usd_score * w,
            note=(
                "Signed DXY log momentum (65% 4W / 35% 13W); level confirms "
                "and absolute move only scales confidence"
            ),
        ))

        # USDJPY is a carry/risk regime input, not another USD-direction vote.
        jpy_z = _get(metrics, "usdjpy_zscore_1y")
        carry_cat = "risk"
        carry_w = weights.get(carry_cat, 0.125)
        scores.append(IndicatorScore(
            name="usdjpy_carry", category=carry_cat,
            raw_value=_get(metrics, "usdjpy"),
            zscore=jpy_z, percentile=None,
            score=_zscore_score(jpy_z, multiplier=15.0),  # weaker impact than DXY
            weight=carry_w,
            contribution=_zscore_score(jpy_z, multiplier=15.0) * carry_w,
            note="USDJPY carry regime; kept outside the USD directional vote",
        ))

        # ── RISK ──────────────────────────────────────────────────────────
        cat = "risk"
        w = weights.get(cat, 0.125)

        # VIX: low VIX = bullish; high VIX = bearish (fear)
        vix_z = _get(metrics, "vix_zscore_1y")
        scores.append(IndicatorScore(
            name="vix", category=cat,
            raw_value=_get(metrics, "vix"),
            zscore=vix_z, percentile=_get(metrics, "vix_pct_1y"),
            score=_zscore_score(vix_z, invert=True),
            weight=w, contribution=_zscore_score(vix_z, invert=True) * w,
            note="Low VIX = complacency/calm = bullish; high VIX = fear = bearish",
        ))

        # VIX term structure (contango = bullish, backwardation = bearish)
        vix_spot = _get(metrics, "vix")
        vix3m = _get(metrics, "vix3m")
        ts_ratio = None
        if vix_spot and vix3m and vix_spot > 0:
            ts_ratio = vix3m / vix_spot  # >1 = contango (bullish), <1 = backwardation
            ts_score = clamp((ts_ratio - 1.0) * 120)
        else:
            ts_score = 0.0
        scores.append(IndicatorScore(
            name="vix_term_structure", category=cat,
            raw_value=ts_ratio,
            zscore=None, percentile=None,
            score=ts_score, weight=w, contribution=ts_score * w,
            note="VIX3M/VIX >1 = contango = bullish; <1 = backwardation = bearish",
        ))


        # HY OAS: tight spreads = risk-on = bullish SPX
        hy_z = _get(metrics, "hy_oas_zscore_1y")
        scores.append(IndicatorScore(
            name="hy_oas", category=cat,
            raw_value=_get(metrics, "hy_oas"),
            zscore=hy_z, percentile=_get(metrics, "hy_oas_pct_1y"),
            score=_zscore_score(hy_z, invert=True),
            weight=w, contribution=_zscore_score(hy_z, invert=True) * w,
            note="Tight HY spreads = risk appetite = bullish SPX",
        ))

        # IG OAS
        ig_z = _get(metrics, "ig_oas_zscore_1y")
        scores.append(IndicatorScore(
            name="ig_oas", category=cat,
            raw_value=_get(metrics, "ig_oas"),
            zscore=ig_z, percentile=None,
            score=_zscore_score(ig_z, invert=True),
            weight=w, contribution=_zscore_score(ig_z, invert=True) * w,
            note="Tight IG spreads = credit health = mild bullish",
        ))

        # ── BREADTH ───────────────────────────────────────────────────────
        cat = "breadth"
        w = weights.get(cat, 0.125)

        # McClellan Oscillator: positive = broad participation = bullish
        mcclellan = _get(metrics, "mcclellan_oscillator")
        mccl_std = _get(metrics, 'mcclellan_std_1y') or 1.5  # dynamic from engine, fallback 1.5
        mcclellan_score = clamp((mcclellan or 0) / mccl_std * 25) if mcclellan is not None else 0.0
        scores.append(IndicatorScore(
            name="mcclellan_oscillator", category=cat,
            raw_value=mcclellan, zscore=None, percentile=None,
            score=mcclellan_score, weight=w, contribution=mcclellan_score * w,
            note="Positive McClellan = broad market participation = bullish",
        ))

        # % stocks above 200D MA: high = broad uptrend
        pct_above_200 = _get(metrics, "pct_above_200ma")
        pct_200_score = percentile_to_score(pct_above_200) if pct_above_200 is not None else 0.0
        scores.append(IndicatorScore(
            name="pct_above_200ma", category=cat,
            raw_value=pct_above_200, zscore=None, percentile=pct_above_200,
            score=pct_200_score, weight=w, contribution=pct_200_score * w,
            note=">60% stocks above 200D MA = healthy broad market",
        ))

        # Net new highs is level-invariant.  Do not score the cumulative A/D
        # line: its arbitrary rebase changes whenever the provider fetch
        # window changes and previously produced a false -3.4 z-score.
        net_new_highs = _get(metrics, "spx_net_new_highs")
        new_highs_score = clamp(float(net_new_highs) * 2.5) if net_new_highs is not None else 0.0
        scores.append(IndicatorScore(
            name="spx_net_new_highs", category=cat,
            raw_value=net_new_highs, zscore=None, percentile=None,
            score=new_highs_score,
            weight=w, contribution=new_highs_score * w,
            note="Net 52W highs/lows; stable across incremental fetch windows",
        ))

        # ── OPTIONS ───────────────────────────────────────────────────────
        cat = "options"
        w = weights.get(cat, 0.125)

        # GEX: positive = MM long gamma → dampened vol → bullish
        spy_gex = _get(metrics, "spy_gex")
        if spy_gex is not None:
            gex_score = _gex_score(spy_gex, scale_millions=500, value_is_millions=False)
            note_str = (
                "Preferred SPY GEX analytics: same-day FlashAlpha, "
                "Yahoo OI/IV model fallback (USD)"
            )
        else:
            spy_gex = _get(metrics, "spy_net_gex_fa")
            gex_score = _gex_score(spy_gex, scale_millions=500, value_is_millions=True)
            note_str = "Legacy Yahoo GEX fallback (USD millions)"
        scores.append(IndicatorScore(
            name="spy_gex", category=cat,
            raw_value=spy_gex, zscore=None, percentile=None,
            score=gex_score, weight=w, contribution=gex_score * w,
            note=note_str,
        ))

        # Gamma Flip & Walls
        gamma_flip = _get(metrics, "spy_gamma_flip")
        if gamma_flip is not None:
            spy_close = _get(metrics, "spy_close")
            if spy_close is not None and gamma_flip is not None:
                distance_pct = (spy_close - gamma_flip) / gamma_flip * 100  # % distance from flip
                flip_score = clamp(distance_pct * 10)  # 1% above flip = +10, 3% = +30
                flip_note = f"SPY distance from estimated Gamma Flip ({gamma_flip:.0f}): {distance_pct:+.2f}%"
            else:
                flip_score = 0.0
                flip_note = "Missing close or gamma flip"
            
            scores.append(IndicatorScore(
                name="spy_gamma_flip", category=cat,
                raw_value=gamma_flip, zscore=None, percentile=None,
                score=flip_score, weight=w, contribution=flip_score * w,
                note=flip_note,
            ))

        # Put/Call ratio: low P/C = call buying = bullish (with contraindication for extremes)
        pc_z = _get(metrics, "spy_pc_ratio_oi_zscore_1y")
        pc_val = _get(metrics, "spy_pc_ratio_oi")
        # Invert: high P/C (fear/puts) → bearish
        scores.append(IndicatorScore(
            name="spy_pc_ratio", category=cat,
            raw_value=pc_val, zscore=pc_z, percentile=None,
            score=_zscore_score(pc_z, invert=True),
            weight=w, contribution=_zscore_score(pc_z, invert=True) * w,
            note="Low P/C ratio = call dominance = bullish",
        ))

        # CBOE total P/C
        cboe_pc_z = _get(metrics, "cboe_total_pc_zscore_1y")
        scores.append(IndicatorScore(
            name="cboe_total_pc", category=cat,
            raw_value=_get(metrics, "cboe_total_pc"),
            zscore=cboe_pc_z, percentile=None,
            score=_zscore_score(cboe_pc_z, invert=True),
            weight=w, contribution=_zscore_score(cboe_pc_z, invert=True) * w,
            note="CBOE total P/C ratio",
        ))

        # ── POSITIONING ───────────────────────────────────────────────────
        cat = "positioning"
        w = weights.get(cat, 0.125)

        # COT Leveraged Money Net: high longs = crowded = mild bearish risk
        # COT Index (0–100): 50 = neutral, >70 = crowded long (contra), <30 = crowded short (fuel)
        cot_spx_idx = _get(metrics, "cot_spx_net_leveraged_cot_index")
        if cot_spx_idx is not None:
            # <30: extreme short → contrarian bullish (+70)
            # >70: extreme long → contrarian bearish (-50)
            # 40-60: neutral (0)
            cot_score = clamp((50 - cot_spx_idx) * 1.5)
        else:
            cot_score = 0.0
        scores.append(IndicatorScore(
            name="cot_spx_leveraged", category=cat,
            raw_value=_get(metrics, "cot_spx_net_leveraged"),
            zscore=None, percentile=cot_spx_idx,
            score=cot_score, weight=w, contribution=cot_score * w,
            note="Extreme short positioning (COT Index <30) = fuel for squeeze = bullish",
        ))

        # Asset Manager net positioning (trend followers)
        cot_am = _get(metrics, "cot_spx_net_asset_mgr")
        cot_am_z = _get(metrics, "cot_spx_net_asset_mgr_zscore_1y")
        scores.append(IndicatorScore(
            name="cot_spx_asset_mgr", category=cat,
            raw_value=cot_am, zscore=cot_am_z, percentile=None,
            score=_zscore_score(cot_am_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(cot_am_z, multiplier=20.0) * w,
            note="Rising asset manager longs = institutional conviction = mild bullish",
        ))

        # ── FLOWS ─────────────────────────────────────────────────────────
        cat = "flows"
        w = weights.get(cat, 0.125)

        # SPY price momentum (market trend, not observed ETF flow)
        spy_z = _get(metrics, "spy_close_zscore_1y")
        scores.append(IndicatorScore(
            name="spy_momentum", category=cat,
            raw_value=_get(metrics, "spy_close"),
            zscore=spy_z, percentile=None,
            score=_zscore_score(spy_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(spy_z, multiplier=20.0) * w,
            note="SPY price trend; this is not observed ETF creations/redemptions",
        ))

        # SPY 4W return momentum
        spy_4w_z = _get(metrics, "spy_close_4w_chg_zscore_1y")
        scores.append(IndicatorScore(
            name="spy_return_momentum_4w", category=cat,
            raw_value=_get(metrics, "spy_close_chg_4w"),
            zscore=spy_4w_z, percentile=None,
            score=_zscore_score(spy_4w_z, multiplier=20.0),
            weight=w, contribution=_zscore_score(spy_4w_z, multiplier=20.0) * w,
            note="SPY 4W return momentum; not an ETF flow measurement",
        ))

        turnover_z = _get(metrics, "spy_signed_turnover_proxy_zscore_1y")
        turnover_score = _zscore_score(turnover_z, multiplier=15.0)
        scores.append(IndicatorScore(
            name="spy_signed_turnover_proxy", category=cat,
            raw_value=_get(metrics, "spy_signed_turnover_proxy"),
            zscore=turnover_z, percentile=None,
            score=turnover_score,
            weight=w, contribution=turnover_score * w,
            note="Weekly signed dollar turnover proxy; not ETF creations/redemptions",
        ))

        # TLT relative momentum (inverse relationship; no flow inference)
        tlt_z = _get(metrics, "tlt_close_zscore_1y")
        scores.append(IndicatorScore(
            name="tlt_relative_momentum", category=cat,
            raw_value=_get(metrics, "tlt_close"),
            zscore=tlt_z, percentile=None,
            score=_zscore_score(tlt_z, invert=True, multiplier=15.0),
            weight=w, contribution=_zscore_score(tlt_z, invert=True, multiplier=15.0) * w,
            note="Falling TLT is a relative-price rotation proxy, not measured fund flow",
        ))

        return scores
