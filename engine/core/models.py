"""
Market Bias Platform — ORM Models (Full Spec)

Database layers:
  raw_data          — Latest value exactly as returned by the provider
  raw_data_revisions — Immutable archive of replaced provider values
  processed_data    — Normalized: timezone, units, outliers
  derived_metrics   — Computed: changes, Z-scores, percentiles, momentum
  plugin_status     — Plugin health, last success, error counts
  fetch_log         — Every fetch attempt with timing
  alerts            — Triggered alert events
  framework_versions — Bias weight snapshots with activation workflow
  bias_results      — Final bias scores per asset/date/timeframe
  backtest_results  — Forward return tracking
  ai_narratives     — AI explanations (optional layer)
  ingestion_logs    — Legacy run tracking
"""
from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float,
    ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

_NOW = lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None)  # noqa: E731


# ══════════════════════════════════════════════════════════════════════════════
# RAW LAYER — exactly what the provider returned
# ══════════════════════════════════════════════════════════════════════════════

class RawDataPoint(Base):
    """Latest provider value for one indicator/date/source observation.

    When a provider revises a value, the previous snapshot is archived in
    ``raw_data_revisions`` before this current-value row is updated.
    """
    __tablename__ = "raw_data"
    __table_args__ = (
        UniqueConstraint("indicator", "date", "source", name="uq_raw_indicator_date_source"),
    )

    id:               Mapped[int]              = mapped_column(Integer, primary_key=True, autoincrement=True)
    indicator:        Mapped[str]              = mapped_column(String(128), nullable=False, index=True)
    date:             Mapped[datetime.datetime]= mapped_column(DateTime,   nullable=False, index=True)
    value:            Mapped[Optional[float]]  = mapped_column(Float,      nullable=True)

    # Provenance — full audit trail
    source:           Mapped[str]              = mapped_column(String(64),  nullable=False)
    plugin:           Mapped[Optional[str]]    = mapped_column(String(64),  nullable=True)   # plugin name
    original_unit:    Mapped[Optional[str]]    = mapped_column(String(32),  nullable=True)   # unit as returned
    original_frequency: Mapped[Optional[str]]  = mapped_column(String(16), nullable=True)   # daily|weekly|monthly
    api_response_ts:  Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    data_version:     Mapped[int]              = mapped_column(Integer, default=1)           # bumped on re-fetch

    created_at:       Mapped[datetime.datetime]= mapped_column(DateTime, default=_NOW)


class RawDataRevision(Base):
    """Immutable archive of a provider value replaced by a later revision."""
    __tablename__ = "raw_data_revisions"
    __table_args__ = (
        UniqueConstraint("raw_data_id", "data_version", name="uq_raw_revision_version"),
    )

    id:               Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_data_id:      Mapped[int]               = mapped_column(Integer, ForeignKey("raw_data.id"), nullable=False, index=True)
    indicator:        Mapped[str]               = mapped_column(String(128), nullable=False, index=True)
    date:             Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    value:            Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    source:           Mapped[str]               = mapped_column(String(64), nullable=False)
    plugin:           Mapped[Optional[str]]     = mapped_column(String(64), nullable=True)
    original_unit:    Mapped[Optional[str]]     = mapped_column(String(32), nullable=True)
    original_frequency: Mapped[Optional[str]]   = mapped_column(String(16), nullable=True)
    api_response_ts:  Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    data_version:     Mapped[int]               = mapped_column(Integer, nullable=False)
    archived_at:      Mapped[datetime.datetime] = mapped_column(DateTime, default=_NOW, nullable=False)


# ══════════════════════════════════════════════════════════════════════════════
# OPTIONS SNAPSHOTS — delayed daily chain and derived expiry summaries
# ══════════════════════════════════════════════════════════════════════════════

class OptionContractSnapshot(Base):
    """One delayed option-chain contract observation for a trading day."""

    __tablename__ = "option_contract_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date", "symbol", "expiration", "option_type", "strike",
            name="uq_option_contract_daily",
        ),
    )

    id:                 Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date:      Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    fetched_at:         Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    symbol:             Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    expiration:         Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    option_type:        Mapped[str] = mapped_column(String(4), nullable=False)  # call|put
    contract_symbol:    Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_trade_date:    Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    strike:             Mapped[float] = mapped_column(Float, nullable=False)
    spot_price:         Mapped[float] = mapped_column(Float, nullable=False)
    last_price:         Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bid:                Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ask:                Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume:             Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    open_interest:      Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    implied_volatility: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    in_the_money:       Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    delta:              Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gamma:              Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    theta:              Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vega:               Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gex:                Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class OptionDailySummary(Base):
    """Derived daily options metrics for one symbol and expiration."""

    __tablename__ = "option_daily_summaries"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date", "symbol", "expiration",
            name="uq_option_summary_daily",
        ),
    )

    id:                  Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date:       Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    fetched_at:          Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    symbol:              Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    expiration:          Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    days_to_expiration:  Mapped[int] = mapped_column(Integer, nullable=False)
    spot_price:          Mapped[float] = mapped_column(Float, nullable=False)
    max_pain:            Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_move:       Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_move_pct:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    put_call_oi_ratio:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    put_call_vol_ratio:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atm_iv:              Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vol_skew:            Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_gex:             Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gamma_flip:          Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    call_wall:           Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    put_wall:            Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    call_volume:         Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    put_volume:          Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    call_open_interest:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    put_open_interest:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)


# ══════════════════════════════════════════════════════════════════════════════
# PROCESSED LAYER — normalized: timezone, units, outliers, standardized names
# ══════════════════════════════════════════════════════════════════════════════

class ProcessedDataPoint(Base):
    """
    Normalized version of raw data.
    - UTC datetime
    - Standard units (B USD, %, bps, index, etc.)
    - Outliers flagged/capped
    - Gaps forward-filled where appropriate
    """
    __tablename__ = "processed_data"
    __table_args__ = (
        UniqueConstraint("indicator", "date", name="uq_processed_indicator_date"),
    )

    id:             Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    indicator:      Mapped[str]               = mapped_column(String(128), nullable=False, index=True)
    date:           Mapped[datetime.datetime] = mapped_column(DateTime,    nullable=False, index=True)
    value:          Mapped[Optional[float]]   = mapped_column(Float,       nullable=True)

    unit:           Mapped[Optional[str]]     = mapped_column(String(32),  nullable=True)
    frequency:      Mapped[Optional[str]]     = mapped_column(String(16),  nullable=True)  # daily|weekly|monthly
    is_interpolated: Mapped[bool]             = mapped_column(Boolean, default=False)       # gap-filled
    is_outlier:     Mapped[bool]              = mapped_column(Boolean, default=False)

    source_raw_id:  Mapped[Optional[int]]     = mapped_column(Integer, ForeignKey("raw_data.id"), nullable=True)
    updated_at:     Mapped[datetime.datetime] = mapped_column(DateTime, default=_NOW)


# ══════════════════════════════════════════════════════════════════════════════
# DERIVED METRICS LAYER — computed metrics stored for fast dashboard access
# ══════════════════════════════════════════════════════════════════════════════

class DerivedMetric(Base):
    """
    All computed metrics for an indicator at a given date.
    Includes: rolling changes, moving averages, Z-scores, percentiles, momentum.
    """
    __tablename__ = "derived_metrics"
    __table_args__ = (
        UniqueConstraint("indicator", "date", name="uq_derived_indicator_date"),
    )

    id:             Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    indicator:      Mapped[str]               = mapped_column(String(128), nullable=False, index=True)
    date:           Mapped[datetime.datetime] = mapped_column(DateTime,    nullable=False, index=True)

    # Current value
    value:          Mapped[Optional[float]]   = mapped_column(Float, nullable=True)

    # Rolling changes (% unless noted)
    chg_1w:         Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    chg_4w:         Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    chg_13w:        Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    chg_26w:        Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    chg_52w:        Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    chg_yoy:        Mapped[Optional[float]]   = mapped_column(Float, nullable=True)

    # Moving averages
    ma_20:          Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    ma_50:          Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    ma_200:         Mapped[Optional[float]]   = mapped_column(Float, nullable=True)

    # Statistical measures
    zscore_1y:      Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    zscore_3y:      Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    zscore_5y:      Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    pct_rank_1y:    Mapped[Optional[float]]   = mapped_column(Float, nullable=True)  # 0–100
    pct_rank_3y:    Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    pct_rank_5y:    Mapped[Optional[float]]   = mapped_column(Float, nullable=True)

    # Momentum
    momentum_4w:    Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    momentum_13w:   Mapped[Optional[float]]   = mapped_column(Float, nullable=True)

    computed_at:    Mapped[datetime.datetime] = mapped_column(DateTime, default=_NOW)


# ══════════════════════════════════════════════════════════════════════════════
# META LAYER — plugin health, fetch logs, alerts
# ══════════════════════════════════════════════════════════════════════════════

class PluginStatus(Base):
    """Tracks the operational status of each data plugin."""
    __tablename__ = "plugin_status"
    __table_args__ = (
        UniqueConstraint("plugin_name", name="uq_plugin_name"),
    )

    id:                 Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_name:        Mapped[str]               = mapped_column(String(64), nullable=False)
    plugin_type:        Mapped[Optional[str]]      = mapped_column(String(16), nullable=True)  # macro|market|ai|utility

    enabled:            Mapped[bool]               = mapped_column(Boolean, default=True)
    healthy:            Mapped[Optional[bool]]      = mapped_column(Boolean, nullable=True)
    last_health_check:  Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    health_message:     Mapped[Optional[str]]       = mapped_column(Text, nullable=True)

    last_success_at:    Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    last_error_at:      Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    last_error_msg:     Mapped[Optional[str]]       = mapped_column(Text, nullable=True)
    consecutive_errors: Mapped[int]                = mapped_column(Integer, default=0)
    total_records:      Mapped[int]                = mapped_column(Integer, default=0)

    updated_at:         Mapped[datetime.datetime]  = mapped_column(DateTime, default=_NOW)


class FetchLog(Base):
    """Every data fetch attempt — success or failure — logged here."""
    __tablename__ = "fetch_log"

    id:             Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_name:    Mapped[str]               = mapped_column(String(64),  nullable=False, index=True)
    run_id:         Mapped[Optional[str]]      = mapped_column(String(64),  nullable=True)
    job_type:       Mapped[Optional[str]]      = mapped_column(String(16),  nullable=True)  # daily|weekly|monthly|manual

    started_at:     Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    completed_at:   Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    duration_s:     Mapped[Optional[float]]   = mapped_column(Float, nullable=True)

    records_fetched: Mapped[int]              = mapped_column(Integer, default=0)
    records_stored:  Mapped[int]              = mapped_column(Integer, default=0)
    status:         Mapped[str]               = mapped_column(String(16), nullable=False)   # success|error|partial|skipped
    error_message:  Mapped[Optional[str]]      = mapped_column(Text, nullable=True)
    warnings:       Mapped[Optional[str]]      = mapped_column(Text, nullable=True)


class Alert(Base):
    """Triggered alert events (regime changes, threshold crossings, etc.)."""
    __tablename__ = "alerts"

    id:             Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_type:     Mapped[str]               = mapped_column(String(64),  nullable=False, index=True)
    # Types: regime_change | bias_threshold | liquidity_event | gex_flip | vix_spike | credit_stress | flow_reversal

    asset:          Mapped[Optional[str]]      = mapped_column(String(16),  nullable=True)   # SPX|NASDAQ|GOLD|ALL
    indicator:      Mapped[Optional[str]]      = mapped_column(String(128), nullable=True)

    title:          Mapped[str]               = mapped_column(String(256), nullable=False)
    message:        Mapped[str]               = mapped_column(Text,        nullable=False)
    severity:       Mapped[str]               = mapped_column(String(16),  nullable=False, default="info")  # info|warning|critical

    previous_value: Mapped[Optional[str]]      = mapped_column(String(64),  nullable=True)
    current_value:  Mapped[Optional[str]]      = mapped_column(String(64),  nullable=True)

    is_read:        Mapped[bool]               = mapped_column(Boolean, default=False)
    triggered_at:   Mapped[datetime.datetime]  = mapped_column(DateTime, default=_NOW, index=True)
    read_at:        Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)


# ══════════════════════════════════════════════════════════════════════════════
# FRAMEWORK LAYER — versioned bias configurations
# ══════════════════════════════════════════════════════════════════════════════

class FrameworkVersion(Base):
    """
    Immutable snapshot of indicator weights and rules.
    Changes create a NEW version (draft) that must be explicitly activated.
    This is essential for honest backtesting.
    """
    __tablename__ = "framework_versions"

    id:               Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    version:          Mapped[int]               = mapped_column(Integer, nullable=False, unique=True)
    name:             Mapped[Optional[str]]      = mapped_column(String(128), nullable=True)
    description:      Mapped[Optional[str]]      = mapped_column(Text,        nullable=True)

    # Weights per asset (JSON: {category: weight})
    spx_weights:      Mapped[dict]              = mapped_column(JSON, nullable=False)
    nasdaq_weights:   Mapped[dict]              = mapped_column(JSON, nullable=False)
    gold_weights:     Mapped[dict]              = mapped_column(JSON, nullable=False)

    # Regime thresholds (JSON: {regime_name: threshold})
    regime_thresholds: Mapped[dict]             = mapped_column(JSON, nullable=False)

    # Per-indicator config (JSON: {indicator: {enabled, lookback_days, weight_override}})
    indicator_config: Mapped[Optional[dict]]    = mapped_column(JSON, nullable=True)

    # Lifecycle: draft → active → archived
    status:           Mapped[str]               = mapped_column(String(16), nullable=False, default="draft")
    is_active:        Mapped[bool]              = mapped_column(Boolean, default=False)

    # Who changed what
    created_by:       Mapped[Optional[str]]      = mapped_column(String(64),  nullable=True)
    activated_at:     Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at:       Mapped[datetime.datetime]  = mapped_column(DateTime, default=_NOW)


# ══════════════════════════════════════════════════════════════════════════════
# BIAS LAYER — computed scores and regime classifications
# ══════════════════════════════════════════════════════════════════════════════

class BiasResult(Base):
    """
    Final bias score and regime for an asset at a given date/timeframe.
    Linked to the framework version used to compute it.
    """
    __tablename__ = "bias_results"
    __table_args__ = (
        UniqueConstraint("asset", "date", "timeframe", "framework_version",
                         name="uq_bias_asset_date_tf_fv"),
    )

    id:               Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset:            Mapped[str]               = mapped_column(String(16),  nullable=False, index=True)  # SPX|NASDAQ|GOLD
    date:             Mapped[datetime.datetime] = mapped_column(DateTime,    nullable=False, index=True)
    timeframe:        Mapped[str]               = mapped_column(String(16),  nullable=False)  # weekly|monthly

    # Scores
    total_score:      Mapped[float]             = mapped_column(Float, nullable=False)
    regime:           Mapped[str]               = mapped_column(String(32), nullable=False)

    # Score change vs prior period
    prev_score:       Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    score_change:     Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    prev_regime:      Mapped[Optional[str]]      = mapped_column(String(32), nullable=True)

    # Drill-down detail (JSON)
    category_scores:  Mapped[Optional[dict]]    = mapped_column(JSON, nullable=True)
    indicator_detail: Mapped[Optional[dict]]    = mapped_column(JSON, nullable=True)

    # Top drivers (JSON list of {name, contribution})
    top_positive:     Mapped[Optional[list]]    = mapped_column(JSON, nullable=True)
    top_negative:     Mapped[Optional[list]]    = mapped_column(JSON, nullable=True)

    data_coverage:    Mapped[Optional[float]]   = mapped_column(Float, nullable=True)  # 0–1
    framework_version: Mapped[int]              = mapped_column(Integer, default=1)
    created_at:       Mapped[datetime.datetime] = mapped_column(DateTime, default=_NOW)

    # Relationships
    ai_narrative:     Mapped[Optional["AINarrative"]]    = relationship("AINarrative", back_populates="bias_result", uselist=False)
    backtest_results: Mapped[list["BacktestResult"]]     = relationship("BacktestResult", back_populates="bias_result")


class PredictiveBiasResult(Base):
    """Auditable output of the unified probabilistic four-week model.

    This table is separate from ``bias_results`` so an unvalidated research
    model can never silently replace the production heuristic.
    """
    __tablename__ = "predictive_bias_results"
    __table_args__ = (
        UniqueConstraint(
            "asset", "date", "horizon_weeks", "model_version",
            name="uq_predictive_bias_asset_date_horizon_version",
        ),
    )

    id:                  Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset:               Mapped[str]               = mapped_column(String(16), nullable=False, index=True)
    date:                Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    horizon_weeks:       Mapped[int]               = mapped_column(Integer, nullable=False, default=4)
    model_version:       Mapped[str]               = mapped_column(String(64), nullable=False)
    status:              Mapped[str]               = mapped_column(String(32), nullable=False)
    predicted_return:    Mapped[float]             = mapped_column(Float, nullable=False)
    lower_80:            Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    upper_80:            Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    probability_up:      Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    bias_score:          Mapped[float]             = mapped_column(Float, nullable=False)
    regime:              Mapped[str]               = mapped_column(String(32), nullable=False)
    n_observations:      Mapped[int]               = mapped_column(Integer, nullable=False)
    training_start:      Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    training_end:        Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    diagnostics:         Mapped[Optional[dict]]    = mapped_column(JSON, nullable=True)
    contributions:       Mapped[Optional[list]]    = mapped_column(JSON, nullable=True)
    feature_snapshot:    Mapped[Optional[dict]]    = mapped_column(JSON, nullable=True)
    created_at:          Mapped[datetime.datetime] = mapped_column(DateTime, default=_NOW, index=True)


class PredictiveModelRunLease(Base):
    """Database-backed lease preventing concurrent predictive model fits."""
    __tablename__ = "predictive_model_run_leases"

    lease_key:       Mapped[str]               = mapped_column(String(128), primary_key=True)
    owner_id:        Mapped[str]               = mapped_column(String(64), nullable=False)
    acquired_until:  Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    updated_at:      Mapped[datetime.datetime] = mapped_column(DateTime, default=_NOW, nullable=False)


# ══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE RESEARCH FOUNDATION — immutable PIT data/model audit artifacts
# ══════════════════════════════════════════════════════════════════════════════

class SeriesDefinition(Base):
    """Versioned policy metadata for one canonical input series."""

    __tablename__ = "series_definitions"
    __table_args__ = (
        UniqueConstraint("series_key", "definition_version", name="uq_series_definition_version"),
    )

    id:                 Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_key:         Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    provider:           Mapped[str] = mapped_column(String(64), nullable=False)
    plugin:             Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    unit:               Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    frequency:          Mapped[str] = mapped_column(String(16), nullable=False)
    publication_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    revision_class:     Mapped[str] = mapped_column(String(32), nullable=False)
    ttl_seconds:        Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    oos_eligible:       Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status:             Mapped[str] = mapped_column(String(24), nullable=False, default="research")
    created_at:         Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class ObservationVintage(Base):
    """Append-only value carrying observation, availability, and recording time."""

    __tablename__ = "observation_vintages"
    __table_args__ = (
        UniqueConstraint(
            "series_definition_id", "observed_at", "available_at", "payload_hash",
            name="uq_observation_vintage_payload",
        ),
    )

    id:                   Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_definition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("series_definitions.id"), nullable=False, index=True
    )
    observed_at:          Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    available_at:         Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    recorded_at:          Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW, index=True)
    value:                Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vintage_id:           Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    vintage_source:       Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    payload_hash:         Mapped[str] = mapped_column(String(64), nullable=False)
    ingest_run_id:        Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    quality_flags:        Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class FeatureDefinition(Base):
    """Formula and eligibility contract for a feature-set member."""

    __tablename__ = "feature_definitions"
    __table_args__ = (
        UniqueConstraint("feature_set_version", "name", name="uq_feature_definition_set_name"),
    )

    id:                 Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_set_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name:               Mapped[str] = mapped_column(String(128), nullable=False)
    formula_ref:        Mapped[str] = mapped_column(String(256), nullable=False)
    lookback_periods:   Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    eligibility_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at:         Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class FeatureSnapshot(Base):
    """Immutable feature vector for one asset/horizon/as-of decision point."""

    __tablename__ = "feature_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "feature_set_version", "asset", "horizon", "as_of",
            name="uq_feature_snapshot_natural_key",
        ),
        UniqueConstraint("snapshot_hash", name="uq_feature_snapshot_hash"),
    )

    id:                  Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_set_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset:               Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    horizon:             Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    as_of:               Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    values_json:         Mapped[dict] = mapped_column(JSON, nullable=False)
    availability_json:   Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quality_json:        Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lineage_json:        Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    vintage_source:      Mapped[str] = mapped_column(String(40), nullable=False)
    snapshot_hash:       Mapped[str] = mapped_column(String(64), nullable=False)
    created_at:          Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class ResearchModelSpec(Base):
    """Frozen estimator/target/validation contract, separate from a fitted artifact."""

    __tablename__ = "research_model_specs"
    __table_args__ = (
        UniqueConstraint("name", "spec_version", name="uq_research_model_spec_version"),
    )

    id:                          Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:                        Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    spec_version:                Mapped[int] = mapped_column(Integer, nullable=False)
    family:                      Mapped[str] = mapped_column(String(64), nullable=False)
    target_spec:                 Mapped[dict] = mapped_column(JSON, nullable=False)
    horizon:                     Mapped[str] = mapped_column(String(16), nullable=False)
    feature_set_version:         Mapped[str] = mapped_column(String(64), nullable=False)
    estimator_config:            Mapped[dict] = mapped_column(JSON, nullable=False)
    validation_protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    complexity_rank:             Mapped[int] = mapped_column(Integer, nullable=False)
    status:                      Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    created_at:                  Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class ResearchModelVersion(Base):
    """Immutable fitted artifact metadata for a frozen model specification."""

    __tablename__ = "research_model_versions"
    __table_args__ = (
        UniqueConstraint("model_spec_id", "version", name="uq_research_model_version"),
        UniqueConstraint("artifact_hash", name="uq_research_model_artifact_hash"),
    )

    id:              Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_spec_id:   Mapped[int] = mapped_column(
        Integer, ForeignKey("research_model_specs.id"), nullable=False, index=True
    )
    version:         Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_hash:   Mapped[str] = mapped_column(String(64), nullable=False)
    code_version:    Mapped[str] = mapped_column(String(64), nullable=False)
    training_cutoff: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    artifact_uri:    Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status:          Mapped[str] = mapped_column(String(24), nullable=False, default="candidate")
    created_at:      Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class ResearchPrediction(Base):
    """Immutable horizon prediction referencing exact model and feature artifacts."""

    __tablename__ = "research_predictions"
    __table_args__ = (
        UniqueConstraint(
            "asset", "horizon", "decision_at", "model_version_id",
            name="uq_research_prediction_decision",
        ),
    )

    id:                      Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset:                   Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    horizon:                 Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    decision_at:             Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    eligible_entry_at:       Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    model_version_id:        Mapped[int] = mapped_column(
        Integer, ForeignKey("research_model_versions.id"), nullable=False, index=True
    )
    feature_snapshot_id:     Mapped[int] = mapped_column(
        Integer, ForeignKey("feature_snapshots.id"), nullable=False, index=True
    )
    feature_snapshot_hash:   Mapped[str] = mapped_column(String(64), nullable=False)
    config_version:          Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_score:          Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    point_forecast:          Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_probability:         Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    calibrated_probability:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_grade:        Mapped[str] = mapped_column(String(24), nullable=False, default="research_only")
    status:                  Mapped[str] = mapped_column(String(24), nullable=False, default="provisional")
    created_at:              Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class ResearchPredictionFactor(Base):
    """Persisted explanation contribution; historical explanations are not recomputed."""

    __tablename__ = "research_prediction_factors"
    __table_args__ = (
        UniqueConstraint("prediction_id", "feature_name", name="uq_prediction_factor_name"),
    )

    id:            Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("research_predictions.id"), nullable=False, index=True
    )
    feature_name:  Mapped[str] = mapped_column(String(128), nullable=False)
    value:         Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coefficient:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    contribution:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detail:        Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ResearchOutcome(Base):
    """Versioned deterministic market outcome; corrections append a new version."""

    __tablename__ = "research_outcomes"
    __table_args__ = (
        UniqueConstraint("prediction_id", "outcome_version", name="uq_research_outcome_version"),
    )

    id:                      Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id:           Mapped[int] = mapped_column(
        Integer, ForeignKey("research_predictions.id"), nullable=False, index=True
    )
    outcome_version:         Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    correction_of_id:        Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("research_outcomes.id"), nullable=True
    )
    matured_at:              Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    entry_price:             Mapped[float] = mapped_column(Float, nullable=False)
    exit_price:              Mapped[float] = mapped_column(Float, nullable=False)
    actual_return:           Mapped[float] = mapped_column(Float, nullable=False)
    excess_return:           Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mfe:                     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mae:                     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    direction_correct:       Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    price_source:            Mapped[str] = mapped_column(String(128), nullable=False)
    calendar_rule_version:   Mapped[str] = mapped_column(String(64), nullable=False)
    price_observed_at:       Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    price_fetched_at:        Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    price_revision_possible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contract_identity:       Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    roll_adjustment_rule:    Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    provenance:              Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at:              Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class ResearchEvaluationRun(Base):
    """Immutable validation artifact comparing a candidate to a declared benchmark.

    ``artifact_hash`` is the unique artifact identity. Logical re-runs for the same
    candidate/cutoff/protocol are intentionally retained so the evaluation service can
    detect non-reproducibility instead of a uniqueness constraint hiding that evidence.
    A protocol version must freeze its seed, benchmark, folds, and configuration.
    """

    __tablename__ = "research_evaluation_runs"

    id:                       Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    protocol_version:         Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_model_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("research_model_versions.id"), nullable=False, index=True
    )
    champion_model_version_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("research_model_versions.id"), nullable=True
    )
    cutoff:                   Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    prediction_outcome_manifest: Mapped[list] = mapped_column(JSON, nullable=False)
    metrics:                  Mapped[dict] = mapped_column(JSON, nullable=False)
    bootstrap_results:        Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status:                   Mapped[str] = mapped_column(String(24), nullable=False)
    artifact_hash:            Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at:               Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class ResearchCalibrationRun(Base):
    """Immutable OOS calibration manifest and fitted calibrator metadata."""

    __tablename__ = "research_calibration_runs"

    id:                          Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    protocol_version:            Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_version_id:            Mapped[int] = mapped_column(
        Integer, ForeignKey("research_model_versions.id"), nullable=False, index=True
    )
    cutoff:                      Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    prediction_outcome_manifest: Mapped[list] = mapped_column(JSON, nullable=False)
    calibrator_version:          Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_hash:               Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    metrics:                     Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at:                  Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class ResearchPromotionEvent(Base):
    """Append-only human model assignment decision and supporting evidence."""

    __tablename__ = "research_promotion_events"

    id:                    Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id:              Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    asset:                 Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    horizon:               Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    from_model_version_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("research_model_versions.id"), nullable=True
    )
    to_model_version_id:   Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("research_model_versions.id"), nullable=True
    )
    decision:              Mapped[str] = mapped_column(String(24), nullable=False)
    reason:                Mapped[str] = mapped_column(Text, nullable=False)
    evidence_run_id:       Mapped[int] = mapped_column(
        Integer, ForeignKey("research_evaluation_runs.id"), nullable=False
    )
    approved_by:           Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at:            Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    rollback_of_event_id:  Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at:            Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class AIToolAudit(Base):
    """Append-only metadata for a typed, permission-checked AI tool invocation.

    Tool outputs, prompts, secrets, and raw ORM objects are deliberately not persisted.
    """

    __tablename__ = "ai_tool_audits"

    id:             Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id:     Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider:       Mapped[str] = mapped_column(String(32), nullable=False)
    tool_name:      Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    validated_args: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_status:  Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    duration_ms:    Mapped[int] = mapped_column(Integer, nullable=False)
    actor_role:     Mapped[str] = mapped_column(String(24), nullable=False)
    error_type:     Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at:     Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class AssistantPreferenceEvent(Base):
    """Append-only preference history for the local Agnes profile.

    Preferences are stored as structured, non-secret values. Keeping events instead of
    mutating one row makes every change inspectable and allows a prior version to be
    restored without giving the assistant arbitrary configuration access.
    """

    __tablename__ = "assistant_preference_events"
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_assistant_preference_version"),
    )

    id:             Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id:     Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version:        Mapped[int] = mapped_column(Integer, nullable=False)
    preferences:    Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    changed_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    actor_role:     Mapped[str] = mapped_column(String(24), nullable=False)
    session_id:     Mapped[str] = mapped_column(String(64), nullable=False)
    created_at:     Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


class AIResearchTelemetry(Base):
    """Privacy-minimized routing telemetry for Agnes external research fallback."""

    __tablename__ = "ai_research_telemetry"

    id:             Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id:     Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider:       Mapped[str] = mapped_column(String(32), nullable=False)
    event_type:     Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    query_hash:     Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result_status:  Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    details:        Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at:     Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=_NOW)


# ══════════════════════════════════════════════════════════════════════════════
# AI LAYER — optional narratives plus audited, permission-checked tool metadata
# ══════════════════════════════════════════════════════════════════════════════

class AINarrative(Base):
    """
    AI-generated explanation for a bias result.
    AI output is clearly separated from the quantitative framework result.
    Format: DATA → FRAMEWORK RESULT → AI INTERPRETATION
    """
    __tablename__ = "ai_narratives"

    id:               Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    bias_result_id:   Mapped[int]               = mapped_column(Integer, ForeignKey("bias_results.id"), nullable=False, unique=True)

    # Plugin info
    provider:         Mapped[str]               = mapped_column(String(32),  nullable=False)  # openai|gemini|claude|ollama
    model:            Mapped[str]               = mapped_column(String(64),  nullable=False)

    # Structured output sections
    framework_result: Mapped[Optional[str]]      = mapped_column(Text, nullable=True)   # Quantitative result (verbatim)
    explanation:      Mapped[Optional[str]]      = mapped_column(Text, nullable=True)   # AI interpretation
    drivers:          Mapped[Optional[str]]      = mapped_column(Text, nullable=True)
    contradictions:   Mapped[Optional[str]]      = mapped_column(Text, nullable=True)
    risks:            Mapped[Optional[str]]      = mapped_column(Text, nullable=True)
    watch_next:       Mapped[Optional[str]]      = mapped_column(Text, nullable=True)
    full_report:      Mapped[Optional[str]]      = mapped_column(Text, nullable=True)

    # Cost tracking
    prompt_tokens:     Mapped[Optional[int]]     = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]]     = mapped_column(Integer, nullable=True)
    cost_usd:          Mapped[Optional[float]]   = mapped_column(Float,   nullable=True)

    created_at:       Mapped[datetime.datetime]  = mapped_column(DateTime, default=_NOW)
    bias_result:      Mapped["BiasResult"]       = relationship("BiasResult", back_populates="ai_narrative")


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST LAYER — forward return tracking per bias decision
# ══════════════════════════════════════════════════════════════════════════════

class BacktestResult(Base):
    """
    Links a historical bias result to its realized forward returns.
    Enables evaluation of: hit rate, avg return, drawdown, regime accuracy.
    """
    __tablename__ = "backtest_results"

    id:               Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    bias_result_id:   Mapped[int]               = mapped_column(Integer, ForeignKey("bias_results.id"), nullable=False)

    # Forward returns (%)
    fwd_return_1w:    Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    fwd_return_4w:    Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    fwd_return_13w:   Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    fwd_return_26w:   Mapped[Optional[float]]   = mapped_column(Float, nullable=True)

    # Directional accuracy
    correct_1w:       Mapped[Optional[bool]]    = mapped_column(Boolean, nullable=True)
    correct_4w:       Mapped[Optional[bool]]    = mapped_column(Boolean, nullable=True)
    correct_13w:      Mapped[Optional[bool]]    = mapped_column(Boolean, nullable=True)
    correct_26w:      Mapped[Optional[bool]]    = mapped_column(Boolean, nullable=True)

    # Max drawdown during hold period
    max_dd_4w:        Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    max_dd_13w:       Mapped[Optional[float]]   = mapped_column(Float, nullable=True)

    computed_at:      Mapped[datetime.datetime] = mapped_column(DateTime, default=_NOW)
    bias_result:      Mapped["BiasResult"]      = relationship("BiasResult", back_populates="backtest_results")


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY — kept for backward compatibility
# ══════════════════════════════════════════════════════════════════════════════

class ProcessedMetric(Base):
    """Legacy processed metrics table — superseded by DerivedMetric."""
    __tablename__ = "legacy_processed_data"
    __table_args__ = (
        UniqueConstraint("indicator", "date", "timeframe", name="uq_legacy_processed_indicator_date_tf"),
    )

    id:             Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    indicator:      Mapped[str]               = mapped_column(String(128), nullable=False, index=True)
    date:           Mapped[datetime.datetime] = mapped_column(DateTime,    nullable=False, index=True)
    timeframe:      Mapped[str]               = mapped_column(String(16),  nullable=False)

    value:          Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    value_1w_chg:   Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    value_4w_chg:   Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    value_13w_chg:  Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    value_26w_chg:  Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    value_52w_chg:  Mapped[Optional[float]]   = mapped_column(Float, nullable=True)

    ma_21:          Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    ma_50:          Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    ma_200:         Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    zscore_1y:      Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    percentile_1y:  Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    created_at:     Mapped[datetime.datetime] = mapped_column(DateTime, default=_NOW)


class IngestionLog(Base):
    """Legacy run-level ingestion tracking."""
    __tablename__ = "ingestion_logs"

    id:              Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id:          Mapped[str]               = mapped_column(String(64), nullable=False, index=True)
    plugin:          Mapped[str]               = mapped_column(String(64), nullable=False)
    timeframe:       Mapped[str]               = mapped_column(String(16), nullable=False)
    status:          Mapped[str]               = mapped_column(String(16), nullable=False)
    records_fetched: Mapped[int]               = mapped_column(Integer, default=0)
    records_stored:  Mapped[int]               = mapped_column(Integer, default=0)
    error_message:   Mapped[Optional[str]]      = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[Optional[float]]  = mapped_column(Float, nullable=True)
    started_at:      Mapped[datetime.datetime] = mapped_column(DateTime, default=_NOW)
    completed_at:    Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
