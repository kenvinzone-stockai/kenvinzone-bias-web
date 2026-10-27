"""
Market Bias Platform — Regime Classification
Converts a numeric bias score (-100 to +100) to a named market regime.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Regime(str, Enum):
    STRONG_BULLISH = "Strong Bullish"
    BULLISH = "Bullish"
    NEUTRAL = "Neutral"
    BEARISH = "Bearish"
    STRONG_BEARISH = "Strong Bearish"
    INSUFFICIENT_DATA = "Insufficient Data"


# Default thresholds (can be overridden per framework version)
DEFAULT_THRESHOLDS = {
    # Calibrated to the observed composite distribution.  The old +/-20 and
    # +/-60 boundaries classified every stored weekly observation as neutral.
    "strong_bullish_min": 15.0,
    "bullish_min": 7.0,
    "bearish_max": -7.0,
    "strong_bearish_max": -15.0,
}

# ── Visual Presentation ────────────────────────────────────────────────────────
REGIME_CONFIG = {
    Regime.STRONG_BULLISH:  {"emoji": "🟢", "color": "#00C853", "bg": "#0d2a1a"},
    Regime.BULLISH:         {"emoji": "🟩", "color": "#76FF03", "bg": "#1a2e0d"},
    Regime.NEUTRAL:         {"emoji": "🟨", "color": "#FFD600", "bg": "#2a2200"},
    Regime.BEARISH:         {"emoji": "🟥", "color": "#FF5252", "bg": "#2a0d0d"},
    Regime.STRONG_BEARISH:  {"emoji": "🔴", "color": "#D50000", "bg": "#1a0000"},
    Regime.INSUFFICIENT_DATA: {"emoji": "⚪", "color": "#757575", "bg": "#1a1a1a"},
}


@dataclass
class RegimeResult:
    score: float
    regime: Regime
    emoji: str
    color: str
    bg_color: str
    description: str


def classify_regime(
    score: float,
    thresholds: dict | None = None,
) -> RegimeResult:
    """
    Classify a [-100, +100] score into a market regime.

    Args:
        score: The weighted bias score
        thresholds: Optional custom thresholds dict (uses defaults if None)

    Returns:
        RegimeResult with regime, visual config, and description
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    if score is None or (score != score):  # NaN check
        regime = Regime.INSUFFICIENT_DATA
    elif score >= thresholds["strong_bullish_min"]:
        regime = Regime.STRONG_BULLISH
    elif score >= thresholds["bullish_min"]:
        regime = Regime.BULLISH
    elif score <= thresholds["strong_bearish_max"]:
        regime = Regime.STRONG_BEARISH
    elif score <= thresholds["bearish_max"]:
        regime = Regime.BEARISH
    else:
        regime = Regime.NEUTRAL

    cfg = REGIME_CONFIG[regime]
    descriptions = {
        Regime.STRONG_BULLISH:  f"Score {score:+.1f} — Multiple indicators strongly aligned bullish across liquidity, risk appetite, and momentum.",
        Regime.BULLISH:         f"Score {score:+.1f} — Moderate bullish bias. More indicators lean supportive than headwinds.",
        Regime.NEUTRAL:         f"Score {score:+.1f} — Mixed signals. No clear directional edge; elevated uncertainty.",
        Regime.BEARISH:         f"Score {score:+.1f} — Moderate bearish bias. More headwinds than tailwinds across indicators.",
        Regime.STRONG_BEARISH:  f"Score {score:+.1f} — Multiple indicators strongly aligned bearish. Elevated caution warranted.",
        Regime.INSUFFICIENT_DATA: "Insufficient data to determine regime. Check data sources.",
    }

    return RegimeResult(
        score=score,
        regime=regime,
        emoji=cfg["emoji"],
        color=cfg["color"],
        bg_color=cfg["bg"],
        description=descriptions[regime],
    )
