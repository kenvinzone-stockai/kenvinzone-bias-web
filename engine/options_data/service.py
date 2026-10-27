"""Fetch, calculate, persist, and query delayed daily options snapshots."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm
from sqlalchemy import delete, func, select

from core.database import get_session, init_db
from core.models import OptionContractSnapshot, OptionDailySummary, RawDataPoint
from ingestion.raw_storage import store_raw_record
from options_data.providers import (
    AlpacaOptionsProvider,
    OptionProviderError,
    ProviderChainSnapshot,
)
from plugins.data.flashalpha import FlashAlphaAPIError, FlashAlphaPlugin


SUPPORTED_SYMBOLS = ("SPY", "QQQ", "GLD")


class OptionsDataError(RuntimeError):
    """Raised when an options snapshot cannot be fetched or calculated."""


@dataclass(frozen=True)
class RefreshResult:
    symbol: str
    snapshot_date: date
    fetched_at: datetime
    expiration_count: int
    contract_count: int
    provider: str = "Yahoo Finance"


@dataclass(frozen=True)
class ChainQuality:
    usable: bool
    positive_oi_ratio: float
    positive_call_contracts: int
    positive_put_contracts: int
    message: str


@dataclass(frozen=True)
class AnalyticsRefreshResult:
    symbol: str
    success: bool
    provider: str
    message: str
    observation_date: Optional[date] = None


@dataclass(frozen=True)
class FlashAlphaAnalytics:
    symbol: str
    observation_date: date
    fetched_at: datetime
    source: str
    net_gex: Optional[float]
    gamma_flip: Optional[float]
    call_wall: Optional[float]
    put_wall: Optional[float]


def _finite(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _optional_number(value) -> Optional[float]:
    number = _finite(value, float("nan"))
    return number if math.isfinite(number) else None


def _naive_datetime(value) -> Optional[datetime]:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.to_pydatetime()


def black_scholes_greeks(
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    volatility: float,
    option_type: str,
) -> dict[str, Optional[float]]:
    """Return model-estimated delta/gamma/theta/vega for display."""
    if min(spot, strike, time_years, volatility) <= 0:
        return {"delta": None, "gamma": None, "theta": None, "vega": None}

    sqrt_t = math.sqrt(time_years)
    d1 = (
        math.log(spot / strike)
        + (rate + 0.5 * volatility * volatility) * time_years
    ) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t
    discount = math.exp(-rate * time_years)
    pdf = norm.pdf(d1)

    if option_type == "call":
        delta = norm.cdf(d1)
        theta_annual = (
            -(spot * pdf * volatility) / (2 * sqrt_t)
            - rate * strike * discount * norm.cdf(d2)
        )
    else:
        delta = norm.cdf(d1) - 1
        theta_annual = (
            -(spot * pdf * volatility) / (2 * sqrt_t)
            + rate * strike * discount * norm.cdf(-d2)
        )

    return {
        "delta": float(delta),
        "gamma": float(pdf / (spot * volatility * sqrt_t)),
        "theta": float(theta_annual / 365.0),
        "vega": float(spot * pdf * sqrt_t / 100.0),
    }


def calculate_max_pain(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: Optional[float] = None,
) -> Optional[float]:
    """Estimate the settlement strike minimizing aggregate intrinsic payout."""
    profile = calculate_max_pain_profile(calls, puts, spot)
    if profile.empty:
        return None
    result = float(profile.loc[profile["total_payout"].idxmin(), "strike"])
    if spot and not spot * 0.8 <= result <= spot * 1.2:
        return None
    return result


def calculate_max_pain_profile(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: Optional[float] = None,
) -> pd.DataFrame:
    """Return call, put, and total intrinsic payout across settlement strikes."""
    if spot and spot > 0:
        calls = calls[pd.to_numeric(calls["strike"], errors="coerce").between(spot * 0.7, spot * 1.3)]
        puts = puts[pd.to_numeric(puts["strike"], errors="coerce").between(spot * 0.7, spot * 1.3)]
    call_oi_series = pd.to_numeric(calls.get("openInterest"), errors="coerce")
    put_oi_series = pd.to_numeric(puts.get("openInterest"), errors="coerce")
    if call_oi_series.fillna(0).sum() <= 0 or put_oi_series.fillna(0).sum() <= 0:
        return pd.DataFrame(columns=("strike", "call_payout", "put_payout", "total_payout"))
    strikes = sorted(
        set(pd.to_numeric(calls.get("strike"), errors="coerce").dropna())
        | set(pd.to_numeric(puts.get("strike"), errors="coerce").dropna())
    )
    if not strikes:
        return pd.DataFrame(columns=("strike", "call_payout", "put_payout", "total_payout"))

    call_strikes = pd.to_numeric(calls.get("strike"), errors="coerce").fillna(0).to_numpy()
    call_oi = pd.to_numeric(calls.get("openInterest"), errors="coerce").fillna(0).to_numpy()
    put_strikes = pd.to_numeric(puts.get("strike"), errors="coerce").fillna(0).to_numpy()
    put_oi = pd.to_numeric(puts.get("openInterest"), errors="coerce").fillna(0).to_numpy()

    rows = []
    for settlement in strikes:
        call_payout = np.maximum(settlement - call_strikes, 0) @ call_oi
        put_payout = np.maximum(put_strikes - settlement, 0) @ put_oi
        rows.append({
            "strike": float(settlement),
            "call_payout": float(call_payout),
            "put_payout": float(put_payout),
            "total_payout": float(call_payout + put_payout),
        })
    return pd.DataFrame(rows)


def calculate_aggregate_gamma_profile(
    contracts: pd.DataFrame,
    spot: float,
    snapshot_date: date,
    risk_free_rate: float = 0.045,
    price_band: float = 0.15,
    points: int = 81,
) -> pd.DataFrame:
    """Reprice aggregate signed GEX over underlying-price levels.

    This is a model profile, not reported dealer positioning. Calls are assigned
    positive gamma and puts negative gamma to match the dashboard convention.
    """
    columns = ("underlying_price", "net_gex")
    if contracts.empty or spot <= 0:
        return pd.DataFrame(columns=columns)

    frame = contracts.copy()
    frame["strike"] = pd.to_numeric(frame.get("strike"), errors="coerce")
    frame["iv"] = pd.to_numeric(frame.get("implied_volatility"), errors="coerce")
    frame["oi"] = pd.to_numeric(frame.get("open_interest"), errors="coerce")
    frame["sign"] = np.where(frame.get("option_type").eq("call"), 1.0, -1.0)
    frame["expiration"] = pd.to_datetime(frame.get("expiration"), errors="coerce")
    frame = frame.dropna(subset=["strike", "iv", "oi", "expiration"])
    frame = frame[
        (frame["strike"] > 0)
        & (frame["iv"] >= 0.03)
        & (frame["oi"] > 0)
        & frame["strike"].between(spot * 0.5, spot * 1.5)
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    strikes = frame["strike"].to_numpy(dtype=float)
    iv = frame["iv"].to_numpy(dtype=float)
    signed_oi = (frame["oi"] * frame["sign"]).to_numpy(dtype=float)
    expirations = frame["expiration"].dt.date
    time_years = np.array(
        [max((expiration - snapshot_date).days, 1) / 365.0 for expiration in expirations],
        dtype=float,
    )
    sqrt_t = np.sqrt(time_years)
    levels = np.linspace(spot * (1 - price_band), spot * (1 + price_band), points)
    prices = levels[:, None]
    d1 = (
        np.log(prices / strikes[None, :])
        + (risk_free_rate + 0.5 * iv[None, :] ** 2) * time_years[None, :]
    ) / (iv[None, :] * sqrt_t[None, :])
    gamma = norm.pdf(d1) / (prices * iv[None, :] * sqrt_t[None, :])
    exposure = (
        gamma
        * signed_oi[None, :]
        * 100.0
        * prices ** 2
        * 0.01
    ).sum(axis=1)
    return pd.DataFrame({"underlying_price": levels, "net_gex": exposure})


def _contract_mark(row: pd.Series) -> Optional[float]:
    bid = _optional_number(row.get("bid"))
    ask = _optional_number(row.get("ask"))
    if bid is not None and ask is not None and ask >= bid and ask > 0:
        return (bid + ask) / 2.0
    return _optional_number(row.get("lastPrice"))


def calculate_expected_move(
    spot: float,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
) -> Optional[float]:
    """Estimate expected move from the nearest-to-ATM call-plus-put straddle."""
    if calls.empty or puts.empty or spot <= 0:
        return None
    call = calls.iloc[(pd.to_numeric(calls["strike"]) - spot).abs().argsort()[:1]].iloc[0]
    put = puts.iloc[(pd.to_numeric(puts["strike"]) - spot).abs().argsort()[:1]].iloc[0]
    call_mark = _contract_mark(call)
    put_mark = _contract_mark(put)
    if call_mark is None or put_mark is None:
        return None
    return float(call_mark + put_mark)


def calculate_gex_metrics(
    spot: float,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    days_to_expiration: int,
    risk_free_rate: float,
) -> tuple[float, Optional[float]]:
    """Vectorized net GEX and zero-crossing estimate for one expiration."""
    frames = []
    for sign, frame in ((1.0, calls), (-1.0, puts)):
        if frame.empty:
            continue
        part = pd.DataFrame({
            "strike": pd.to_numeric(frame.get("strike"), errors="coerce"),
            "iv": pd.to_numeric(frame.get("impliedVolatility"), errors="coerce"),
            "oi": pd.to_numeric(frame.get("openInterest"), errors="coerce"),
            "sign": sign,
        }).dropna()
        part = part[
            (part["strike"] > 0)
            & (part["iv"] >= 0.03)
            & (part["oi"] > 0)
        ]
        frames.append(part)
    if not frames:
        return 0.0, None

    options = pd.concat(frames, ignore_index=True)
    strikes = options["strike"].to_numpy(dtype=float)
    iv = options["iv"].to_numpy(dtype=float)
    signed_oi = (options["oi"] * options["sign"]).to_numpy(dtype=float)
    time_years = max(days_to_expiration, 1) / 365.0
    sqrt_t = math.sqrt(time_years)

    def exposure(price_levels: np.ndarray) -> np.ndarray:
        prices = price_levels[:, None]
        d1 = (
            np.log(prices / strikes[None, :])
            + (risk_free_rate + 0.5 * iv[None, :] ** 2) * time_years
        ) / (iv[None, :] * sqrt_t)
        gamma = norm.pdf(d1) / (prices * iv[None, :] * sqrt_t)
        return (
            gamma
            * signed_oi[None, :]
            * 100.0
            * prices ** 2
            * 0.01
        ).sum(axis=1)

    net_gex = float(exposure(np.array([spot], dtype=float))[0])
    levels = np.linspace(spot * 0.7, spot * 1.3, 121)
    profile = exposure(levels)
    crossings = np.where(np.signbit(profile[:-1]) != np.signbit(profile[1:]))[0]
    if crossings.size == 0:
        return net_gex, None

    index = int(crossings[np.argmin(np.abs(levels[crossings] - spot))])
    x1, x2 = levels[index], levels[index + 1]
    y1, y2 = profile[index], profile[index + 1]
    gamma_flip = x1 if y2 == y1 else x1 - y1 * (x2 - x1) / (y2 - y1)
    return net_gex, float(gamma_flip)


def _nearest_iv(frame: pd.DataFrame, target_strike: float) -> Optional[float]:
    if frame.empty:
        return None
    valid = frame.copy()
    valid["impliedVolatility"] = pd.to_numeric(valid["impliedVolatility"], errors="coerce")
    valid["strike"] = pd.to_numeric(valid["strike"], errors="coerce")
    valid = valid.dropna(subset=["strike", "impliedVolatility"])
    # Yahoo occasionally emits tiny placeholder IVs for newly listed dailies.
    valid = valid[
        (valid["impliedVolatility"] >= 0.03)
        & (valid["strike"].sub(target_strike).abs() <= target_strike * 0.03)
    ]
    if valid.empty:
        return None
    row = valid.iloc[(valid["strike"] - target_strike).abs().argsort()[:1]].iloc[0]
    return float(row["impliedVolatility"])


def calculate_expiry_summary(
    spot: float,
    expiration: date,
    snapshot_date: date,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    risk_free_rate: float,
) -> dict[str, Optional[float]]:
    """Calculate one expiry's display-oriented options metrics."""
    dte = max((expiration - snapshot_date).days, 0)
    call_oi = float(pd.to_numeric(calls.get("openInterest"), errors="coerce").fillna(0).sum())
    put_oi = float(pd.to_numeric(puts.get("openInterest"), errors="coerce").fillna(0).sum())
    call_volume = float(pd.to_numeric(calls.get("volume"), errors="coerce").fillna(0).sum())
    put_volume = float(pd.to_numeric(puts.get("volume"), errors="coerce").fillna(0).sum())
    expected_move = calculate_expected_move(spot, calls, puts)
    call_atm_iv = _nearest_iv(calls, spot)
    put_atm_iv = _nearest_iv(puts, spot)
    atm_values = [v for v in (call_atm_iv, put_atm_iv) if v is not None]
    atm_iv = sum(atm_values) / len(atm_values) if atm_values else None
    put_downside_iv = _nearest_iv(puts, spot * 0.9)
    call_upside_iv = _nearest_iv(calls, spot * 1.1)
    vol_skew = (
        put_downside_iv - call_upside_iv
        if put_downside_iv is not None and call_upside_iv is not None
        else None
    )

    if call_oi + put_oi > 0:
        net_gex, gamma_flip = calculate_gex_metrics(
            spot, calls, puts, dte, risk_free_rate
        )
    else:
        net_gex, gamma_flip = None, None

    call_wall = None
    if not calls.empty and call_oi > 0:
        idx = pd.to_numeric(calls["openInterest"], errors="coerce").fillna(0).idxmax()
        call_wall = _optional_number(calls.loc[idx, "strike"])
    put_wall = None
    if not puts.empty and put_oi > 0:
        idx = pd.to_numeric(puts["openInterest"], errors="coerce").fillna(0).idxmax()
        put_wall = _optional_number(puts.loc[idx, "strike"])

    return {
        "days_to_expiration": dte,
        "max_pain": calculate_max_pain(calls, puts, spot),
        "expected_move": expected_move,
        "expected_move_pct": expected_move / spot if expected_move is not None else None,
        "put_call_oi_ratio": put_oi / call_oi if call_oi > 0 and put_oi > 0 else None,
        "put_call_vol_ratio": (
            put_volume / call_volume if call_volume > 0 and put_volume > 0 else None
        ),
        "atm_iv": atm_iv,
        "vol_skew": vol_skew,
        "net_gex": net_gex,
        "gamma_flip": gamma_flip,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "call_volume": call_volume,
        "put_volume": put_volume,
        "call_open_interest": call_oi,
        "put_open_interest": put_oi,
    }


def _risk_free_rate() -> float:
    with get_session() as session:
        for indicator in ("sofr", "fed_funds_rate"):
            record = session.execute(
                select(RawDataPoint)
                .where(RawDataPoint.indicator == indicator)
                .order_by(RawDataPoint.date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if record and record.value is not None:
                return float(record.value) / 100.0
    return 0.045


def select_expirations(
    expiration_values: list[str],
    snapshot_date: date,
    count: int,
) -> list[str]:
    """Select near-term plus weekly/monthly expiries instead of only daily listings."""
    dated = sorted(
        (pd.Timestamp(value).date(), value)
        for value in expiration_values
        if pd.Timestamp(value).date() >= snapshot_date
    )
    if len(dated) <= count:
        return [value for _, value in dated]

    chosen: list[tuple[date, str]] = dated[: min(3, count)]

    # Standard monthly expiries (third Friday) generally carry much better OI
    # than newly listed daily options, so always include them when available.
    monthlies = [
        item for item in dated
        if item[0].weekday() == 4 and 15 <= item[0].day <= 21
    ]
    for candidate in monthlies:
        if len(chosen) >= count:
            break
        if candidate not in chosen:
            chosen.append(candidate)

    targets = (7, 14, 30, 45, 60, 90, 120)
    for target in targets:
        if len(chosen) >= count:
            break
        candidate = min(dated, key=lambda item: abs((item[0] - snapshot_date).days - target))
        if candidate not in chosen:
            chosen.append(candidate)

    for candidate in dated:
        if len(chosen) >= count:
            break
        if candidate not in chosen:
            chosen.append(candidate)
    return [value for _, value in sorted(chosen)]


def assess_chain_quality(snapshot: ProviderChainSnapshot) -> ChainQuality:
    """Reject structurally successful responses whose OI is unusably sparse."""
    calls = []
    puts = []
    for call_frame, put_frame in snapshot.chains.values():
        if not call_frame.empty:
            calls.append(call_frame)
        if not put_frame.empty:
            puts.append(put_frame)
    call_data = pd.concat(calls, ignore_index=True) if calls else pd.DataFrame()
    put_data = pd.concat(puts, ignore_index=True) if puts else pd.DataFrame()
    all_data = pd.concat([call_data, put_data], ignore_index=True)
    if all_data.empty or "openInterest" not in all_data:
        return ChainQuality(False, 0.0, 0, 0, "no open-interest observations")

    oi = pd.to_numeric(all_data["openInterest"], errors="coerce")
    reported = oi.notna()
    positive_ratio = float((oi[reported] > 0).mean()) if reported.any() else 0.0
    call_oi = (
        pd.to_numeric(call_data["openInterest"], errors="coerce").fillna(0)
        if "openInterest" in call_data else pd.Series(dtype=float)
    )
    put_oi = (
        pd.to_numeric(put_data["openInterest"], errors="coerce").fillna(0)
        if "openInterest" in put_data else pd.Series(dtype=float)
    )
    positive_calls = int((call_oi > 0).sum())
    positive_puts = int((put_oi > 0).sum())

    near_call = call_data[
        pd.to_numeric(call_data.get("strike"), errors="coerce").between(
            snapshot.spot * 0.8, snapshot.spot * 1.2
        )
    ] if not call_data.empty else call_data
    near_put = put_data[
        pd.to_numeric(put_data.get("strike"), errors="coerce").between(
            snapshot.spot * 0.8, snapshot.spot * 1.2
        )
    ] if not put_data.empty else put_data
    near_call_oi = (
        pd.to_numeric(near_call["openInterest"], errors="coerce").fillna(0).sum()
        if "openInterest" in near_call else 0.0
    )
    near_put_oi = (
        pd.to_numeric(near_put["openInterest"], errors="coerce").fillna(0).sum()
        if "openInterest" in near_put else 0.0
    )

    reasons = []
    if positive_ratio < 0.08:
        reasons.append(f"only {positive_ratio:.1%} of reported contracts have positive OI")
    if positive_calls < 3 or positive_puts < 3:
        reasons.append(
            f"too few positive-OI contracts (calls {positive_calls}, puts {positive_puts})"
        )
    if near_call_oi <= 0 or near_put_oi <= 0:
        reasons.append("no two-sided positive OI within 20% of spot")
    usable = not reasons
    return ChainQuality(
        usable,
        positive_ratio,
        positive_calls,
        positive_puts,
        "quality checks passed" if usable else "; ".join(reasons),
    )


def _fetch_yahoo_snapshot(
    symbol: str,
    max_expirations: int,
) -> ProviderChainSnapshot:
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="5d", auto_adjust=False)
        if history.empty or history["Close"].dropna().empty:
            raise OptionsDataError(f"{symbol}: no recent market price")
        spot = float(history["Close"].dropna().iloc[-1])
        snapshot_date = pd.Timestamp(history.index[-1]).date()
        expiration_values = select_expirations(
            list(ticker.options), snapshot_date, max_expirations
        )
    except OptionsDataError:
        raise
    except Exception as exc:
        raise OptionsDataError(f"{symbol}: failed to load options metadata: {exc}") from exc
    if not expiration_values:
        raise OptionsDataError(f"{symbol}: no option expirations returned")

    chains: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    errors: list[str] = []
    for expiration_value in expiration_values:
        try:
            chain = ticker.option_chain(expiration_value)
            chains[expiration_value] = (chain.calls.copy(), chain.puts.copy())
        except Exception as exc:
            errors.append(f"{expiration_value}: {exc}")
    if not chains:
        raise OptionsDataError(
            f"{symbol}: all expiration fetches failed. {'; '.join(errors[:3])}"
        )
    return ProviderChainSnapshot("Yahoo Finance", spot, snapshot_date, chains)


def refresh_options_snapshot(symbol: str, max_expirations: int = 6) -> RefreshResult:
    """Fetch a quality-gated chain with Alpaca-first, Yahoo-second failover."""
    symbol = symbol.upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"Unsupported options symbol: {symbol}")
    max_expirations = max(1, min(int(max_expirations), 12))
    init_db()

    attempts: list[str] = []
    selected_snapshot: Optional[ProviderChainSnapshot] = None
    alpaca = AlpacaOptionsProvider()
    if alpaca.is_available:
        try:
            candidate = alpaca.fetch(symbol, select_expirations, max_expirations)
            quality = assess_chain_quality(candidate)
            if quality.usable:
                selected_snapshot = candidate
            else:
                attempts.append(f"Alpaca degraded: {quality.message}")
        except OptionProviderError as exc:
            attempts.append(str(exc))

    if selected_snapshot is None:
        try:
            candidate = _fetch_yahoo_snapshot(symbol, max_expirations)
            quality = assess_chain_quality(candidate)
            if quality.usable:
                selected_snapshot = candidate
            else:
                attempts.append(f"Yahoo degraded: {quality.message}")
        except OptionsDataError as exc:
            attempts.append(str(exc))

    if selected_snapshot is None:
        raise OptionsDataError(
            f"{symbol}: no provider returned a trustworthy option chain. "
            + " | ".join(attempts)
        )

    spot = selected_snapshot.spot
    snapshot_date = selected_snapshot.snapshot_date

    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    risk_free_rate = _risk_free_rate()
    contracts: list[OptionContractSnapshot] = []
    summaries: list[OptionDailySummary] = []
    for expiration_value, (calls, puts) in selected_snapshot.chains.items():
        expiration = pd.Timestamp(expiration_value).date()
        summary = calculate_expiry_summary(
            spot, expiration, snapshot_date, calls, puts, risk_free_rate
        )

        summaries.append(OptionDailySummary(
            snapshot_date=snapshot_date,
            fetched_at=fetched_at,
            symbol=symbol,
            expiration=expiration,
            spot_price=spot,
            **summary,
        ))

        dte = max((expiration - snapshot_date).days, 1)
        time_years = dte / 365.0
        for option_type, frame in (("call", calls), ("put", puts)):
            for _, row in frame.iterrows():
                strike = _finite(row.get("strike"))
                iv = _finite(row.get("impliedVolatility"))
                oi = _finite(row.get("openInterest"))
                model_iv = iv if iv >= 0.03 else 0.0
                greeks = black_scholes_greeks(
                    spot, strike, time_years, risk_free_rate, model_iv, option_type
                )
                sign = 1 if option_type == "call" else -1
                gex = (
                    sign * greeks["gamma"] * oi * 100 * spot * spot * 0.01
                    if greeks["gamma"] is not None
                    else None
                )
                contracts.append(OptionContractSnapshot(
                    snapshot_date=snapshot_date,
                    fetched_at=fetched_at,
                    symbol=symbol,
                    expiration=expiration,
                    option_type=option_type,
                    contract_symbol=str(row.get("contractSymbol") or "") or None,
                    last_trade_date=_naive_datetime(row.get("lastTradeDate")),
                    strike=strike,
                    spot_price=spot,
                    last_price=_optional_number(row.get("lastPrice")),
                    bid=_optional_number(row.get("bid")),
                    ask=_optional_number(row.get("ask")),
                    volume=_optional_number(row.get("volume")),
                    open_interest=_optional_number(row.get("openInterest")),
                    implied_volatility=_optional_number(row.get("impliedVolatility")),
                    in_the_money=(
                        bool(row.get("inTheMoney"))
                        if not pd.isna(row.get("inTheMoney"))
                        else None
                    ),
                    gex=gex,
                    **greeks,
                ))

    with get_session() as session:
        session.execute(delete(OptionContractSnapshot).where(
            OptionContractSnapshot.symbol == symbol,
            OptionContractSnapshot.snapshot_date == snapshot_date,
        ))
        session.execute(delete(OptionDailySummary).where(
            OptionDailySummary.symbol == symbol,
            OptionDailySummary.snapshot_date == snapshot_date,
        ))
        session.add_all(contracts)
        session.add_all(summaries)
        store_raw_record(
            session,
            indicator=f"{symbol.lower()}_options_chain_provider",
            observation_date=datetime.combine(snapshot_date, datetime.min.time()),
            value=1.0 if selected_snapshot.provider.startswith("Alpaca") else 0.0,
            source=f"{selected_snapshot.provider}:{symbol}_options",
            plugin="options_snapshot",
            unit="provider_code",
            frequency="daily",
            api_response_ts=fetched_at,
        )

    return RefreshResult(
        symbol=symbol,
        snapshot_date=snapshot_date,
        fetched_at=fetched_at,
        expiration_count=len(summaries),
        contract_count=len(contracts),
        provider=selected_snapshot.provider,
    )


def refresh_flashalpha_analytics(symbol: str) -> AnalyticsRefreshResult:
    """Refresh preferred aggregate analytics without breaking Yahoo fallback."""
    symbol = symbol.upper()
    plugin = FlashAlphaPlugin()
    if not plugin.is_available:
        return AnalyticsRefreshResult(
            symbol=symbol,
            success=False,
            provider="Yahoo model fallback",
            message="FlashAlpha API key is not configured.",
        )

    try:
        levels = plugin.fetch_symbol(symbol)
    except FlashAlphaAPIError as exc:
        return AnalyticsRefreshResult(
            symbol=symbol,
            success=False,
            provider="Yahoo model fallback",
            message=exc.user_message,
        )

    with get_session() as session:
        for record in levels.records():
            store_raw_record(
                session,
                indicator=record["indicator"],
                observation_date=datetime.combine(
                    levels.observation_date, datetime.min.time()
                ),
                value=record["value"],
                source=record["source"],
                plugin=plugin.name,
                unit=record["unit"],
                frequency="daily",
                api_response_ts=levels.fetched_at,
            )

    return AnalyticsRefreshResult(
        symbol=symbol,
        success=True,
        provider="FlashAlpha",
        message="FlashAlpha aggregate exposure analytics refreshed.",
        observation_date=levels.observation_date,
    )


def load_latest_flashalpha_analytics(
    symbol: str,
    reference_date: Optional[date] = None,
) -> Optional[FlashAlphaAnalytics]:
    """Load a current FlashAlpha snapshot; stale data never masks Yahoo."""
    symbol = symbol.upper()
    prefix = symbol.lower()
    indicator_map = {
        f"{prefix}_gex": "net_gex",
        f"{prefix}_gamma_flip": "gamma_flip",
        f"{prefix}_call_wall": "call_wall",
        f"{prefix}_put_wall": "put_wall",
    }
    with get_session() as session:
        rows = session.execute(
            select(RawDataPoint).where(
                RawDataPoint.indicator.in_(indicator_map),
                RawDataPoint.source.like("flashalpha:%"),
            ).order_by(
                RawDataPoint.date.desc(),
                RawDataPoint.api_response_ts.desc(),
                RawDataPoint.id.desc(),
            )
        ).scalars().all()

    if not rows:
        return None
    latest_date = max(row.date.date() for row in rows)
    if reference_date and latest_date < reference_date:
        age = len(pd.bdate_range(latest_date, reference_date, inclusive="right"))
        if age > 1:
            return None

    selected: dict[str, RawDataPoint] = {}
    for row in rows:
        if row.date.date() != latest_date or row.indicator in selected:
            continue
        selected[row.indicator] = row

    values = {
        field: (
            float(selected[indicator].value)
            if indicator in selected and selected[indicator].value is not None
            else None
        )
        for indicator, field in indicator_map.items()
    }
    fetched_at = max(
        (row.api_response_ts or row.created_at for row in selected.values()),
        default=datetime.combine(latest_date, datetime.min.time()),
    )
    source = next(iter(selected.values())).source if selected else "flashalpha"
    return FlashAlphaAnalytics(
        symbol=symbol,
        observation_date=latest_date,
        fetched_at=fetched_at,
        source=source,
        **values,
    )


def _rows_to_frame(rows, columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame([{column: getattr(row, column) for column in columns} for row in rows])


def load_options_chain_provider(symbol: str, snapshot_date: date) -> str:
    """Return persisted provider provenance for an options snapshot."""
    indicator = f"{symbol.lower()}_options_chain_provider"
    with get_session() as session:
        row = session.execute(
            select(RawDataPoint).where(
                RawDataPoint.indicator == indicator,
                RawDataPoint.date == datetime.combine(snapshot_date, datetime.min.time()),
            ).order_by(
                RawDataPoint.api_response_ts.desc(), RawDataPoint.id.desc()
            ).limit(1)
        ).scalar_one_or_none()
    if not row:
        return "Yahoo Finance"
    return "Alpaca indicative" if row.value == 1.0 else "Yahoo Finance"


def load_latest_options(symbol: str) -> tuple[Optional[date], pd.DataFrame, pd.DataFrame]:
    """Return latest snapshot date, contract frame, and summary frame."""
    init_db()
    symbol = symbol.upper()
    with get_session() as session:
        latest_date = session.scalar(
            select(func.max(OptionDailySummary.snapshot_date)).where(
                OptionDailySummary.symbol == symbol
            )
        )
        if latest_date is None:
            return None, pd.DataFrame(), pd.DataFrame()
        contracts = session.execute(
            select(OptionContractSnapshot).where(
                OptionContractSnapshot.symbol == symbol,
                OptionContractSnapshot.snapshot_date == latest_date,
            )
        ).scalars().all()
        summaries = session.execute(
            select(OptionDailySummary).where(
                OptionDailySummary.symbol == symbol,
                OptionDailySummary.snapshot_date == latest_date,
                OptionDailySummary.expiration >= date.today(),
            ).order_by(OptionDailySummary.expiration)
        ).scalars().all()

    active_expirations = {row.expiration for row in summaries}
    contracts = [row for row in contracts if row.expiration in active_expirations]

    contract_columns = (
        "fetched_at", "symbol", "expiration", "option_type", "contract_symbol",
        "last_trade_date", "strike", "spot_price", "last_price", "bid", "ask",
        "volume", "open_interest", "implied_volatility", "in_the_money", "delta",
        "gamma", "theta", "vega", "gex",
    )
    summary_columns = (
        "fetched_at", "symbol", "expiration", "days_to_expiration", "spot_price",
        "max_pain", "expected_move", "expected_move_pct", "put_call_oi_ratio",
        "put_call_vol_ratio", "atm_iv", "vol_skew", "net_gex", "gamma_flip",
        "call_wall", "put_wall", "call_volume", "put_volume",
        "call_open_interest", "put_open_interest",
    )
    return (
        latest_date,
        _rows_to_frame(contracts, contract_columns),
        _rows_to_frame(summaries, summary_columns),
    )


def load_options_history(symbol: str, expiration: date) -> pd.DataFrame:
    """Return stored daily summaries for one symbol/expiration."""
    init_db()
    with get_session() as session:
        rows = session.execute(
            select(OptionDailySummary).where(
                OptionDailySummary.symbol == symbol.upper(),
                OptionDailySummary.expiration == expiration,
            ).order_by(OptionDailySummary.snapshot_date)
        ).scalars().all()
    columns = (
        "snapshot_date", "expiration", "spot_price", "max_pain", "expected_move",
        "expected_move_pct", "put_call_oi_ratio", "put_call_vol_ratio", "atm_iv",
        "vol_skew", "net_gex", "gamma_flip", "call_wall", "put_wall",
    )
    return _rows_to_frame(rows, columns)
