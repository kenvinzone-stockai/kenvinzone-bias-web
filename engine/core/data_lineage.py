"""Human-readable provenance labels for dashboard and audit exports."""
from __future__ import annotations


def classify_data(indicator: str, source: str) -> tuple[str, str]:
    """Return (data class, explanation) without overstating provider data."""
    key = indicator.lower()
    src = source.lower()

    if "signed_turnover_proxy" in key:
        return (
            "Proxy",
            "Price × volume × return direction; not ETF creations/redemptions.",
        )

    option_estimates = (
        "_gex", "net_gex", "gamma_flip", "wall_midpoint", "call_wall", "put_wall",
    )
    if any(token in key for token in option_estimates) and "yfinance" in src:
        return (
            "Estimate",
            "Calculated from Yahoo option-chain OI/IV; not dealer-reported exposure.",
        )

    if src == "yf_breadth" or key.startswith("spx_pct_above_") or key in {
        "advance_decline_line", "mcclellan_oscillator", "pct_above_200ma",
    }:
        return (
            "Derived",
            "Calculated from observed constituent prices; not an official breadth feed.",
        )

    if src.startswith("fred:"):
        return (
            "Observed",
            "Official FRED series; historical observations may include later revisions.",
        )

    if src.startswith("cftc:"):
        return (
            "Observed",
            "Official CFTC report, timestamped at public release availability.",
        )

    if src.startswith("yfinance:"):
        return (
            "Observed",
            "Yahoo Finance market observation; vendor data, not an exchange API feed.",
        )

    return "Unclassified", "Review source metadata before using this series."
