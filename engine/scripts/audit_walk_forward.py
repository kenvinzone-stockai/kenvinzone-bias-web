"""Point-in-time walk-forward diagnostic for the active bias framework.

This intentionally does not write historical bias rows. It slices every input at
the signal date, uses non-overlapping four-week samples, and reports descriptive
performance. FRED revisions and today's constituent universe mean this is not a
strict vintage-data backtest.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from bias.engine import ALL_INDICATORS, BiasEngine
from ingestion.pipeline import load_all_series


PRICE_KEYS = {
    "SPX": "spx_close",
    "NASDAQ": "nasdaq_close",
    "GOLD": "gold_futures",
}


def _finite(value) -> bool:
    return value is not None and np.isfinite(float(value))


def run() -> dict:
    engine = BiasEngine()
    framework = engine._load_active_framework() or {}
    raw = load_all_series(ALL_INDICATORS, days=365 * 4, end_date=date.today())
    weekly = engine._resample_for_timeframe(raw, "weekly")
    calculators = {
        "SPX": engine.spx_calc,
        "NASDAQ": engine.nasdaq_calc,
        "GOLD": engine.gold_calc,
    }

    output = {
        "framework_version": framework.get("version", 1),
        "sampling": "non-overlapping 4-week observations after 52-week warm-up",
        "strict_point_in_time": False,
        "limitations": [
            "FRED history uses the latest available revised observations, not ALFRED vintages.",
            "Breadth history uses the current S&P 500 constituent universe (survivorship bias).",
            "Yahoo continuous futures can contain contract-roll effects.",
            "Public option open interest does not identify dealer-side positioning.",
        ],
        "assets": {},
    }

    for asset, calculator in calculators.items():
        price = weekly.get(PRICE_KEYS[asset], pd.Series(dtype=float)).dropna()
        rows = []
        if len(price) < 60:
            output["assets"][asset] = {"error": "less than 60 weekly prices"}
            continue

        # Four-week step keeps the 4W target approximately non-overlapping.
        for position in range(52, len(price) - 4, 4):
            signal_date = pd.Timestamp(price.index[position])
            future_price = float(price.iloc[position + 4])
            current_price = float(price.iloc[position])
            sliced = {
                name: series.loc[:signal_date]
                for name, series in weekly.items()
            }
            metrics = engine._compute_metrics(sliced, frequency="weekly")
            weight_key = {
                "SPX": "spx_weights",
                "NASDAQ": "nasdaq_weights",
                "GOLD": "gold_weights",
            }[asset]
            result = calculator.compute(
                metrics,
                calc_date=signal_date.date(),
                timeframe="weekly",
                custom_weights=framework.get(weight_key),
                regime_thresholds=framework.get("regime_thresholds"),
            )
            rows.append({
                "date": signal_date,
                "score": result.total_score,
                "coverage": result.data_coverage,
                "return_4w": (future_price / current_price - 1) * 100,
            })

        frame = pd.DataFrame(rows)
        frame = frame[frame["coverage"] >= 0.50].dropna()
        directional = frame[frame["score"].abs() >= 20].copy()
        if not directional.empty:
            directional["correct"] = (
                np.sign(directional["score"]) == np.sign(directional["return_4w"])
            )

        correlations = frame[["score", "return_4w"]].corr()
        spearman = frame[["score", "return_4w"]].corr(method="spearman")
        output["assets"][asset] = {
            "observations": int(len(frame)),
            "directional_observations": int(len(directional)),
            "mean_coverage": round(float(frame["coverage"].mean()), 3) if len(frame) else None,
            "score_min": round(float(frame["score"].min()), 2) if len(frame) else None,
            "score_max": round(float(frame["score"].max()), 2) if len(frame) else None,
            "score_std": round(float(frame["score"].std()), 2) if len(frame) else None,
            "pearson_score_vs_4w_return": (
                round(float(correlations.iloc[0, 1]), 3) if len(frame) >= 3 else None
            ),
            "spearman_score_vs_4w_return": (
                round(float(spearman.iloc[0, 1]), 3) if len(frame) >= 3 else None
            ),
            "directional_hit_rate": (
                round(float(directional["correct"].mean()), 3)
                if len(directional) else None
            ),
            "average_4w_return": (
                round(float(frame["return_4w"].mean()), 3) if len(frame) else None
            ),
        }

    return output


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
