"""
Market Bias Platform — Application Configuration
Loads settings from .env file using Pydantic Settings.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Project root ──────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API Keys
    fred_api_key: str = Field(default="", description="FRED API key")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_base_url: str = Field(default="", description="Optional custom base URL for OpenAI-compatible APIs")
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    agnes_api_key: str = Field(default="", description="Agnes AI API key")
    agnes_base_url: str = Field(
        default="https://apihub.agnes-ai.com/v1",
        description="Agnes OpenAI-compatible API base URL",
    )
    anthropic_api_key: str = Field(default="", description="Anthropic Claude API key")
    flashalpha_api_key: str = Field(default="", description="FlashAlpha API key")
    alpaca_api_key_id: str = Field(default="", description="Alpaca Trading API key ID")
    alpaca_api_secret_key: str = Field(default="", description="Alpaca Trading API secret")
    alpaca_trading_base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        description="Alpaca Trading API base URL used for option contract metadata",
    )
    alpaca_data_base_url: str = Field(
        default="https://data.alpaca.markets",
        description="Alpaca Market Data API base URL",
    )
    fmp_api_key: str = Field(default="", description="FMP API key")
    alphavantage_api_key: str = Field(default="", description="AlphaVantage API key")
    manus_api_key: str = Field(default="", description="Manus API key")

    # AI configuration
    ai_provider: Literal["openai", "gemini", "agnes", "claude", "local", "none", "manus"] = Field(
        default="none"
    )
    ai_model: str = Field(default="agnes-2.5-flash")
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.1")

    # Database
    database_url: str = Field(default=f"sqlite:///{ROOT_DIR / 'data' / 'market_bias.db'}")

    # App settings
    app_title: str = Field(default="Market Bias Platform")
    app_admin_password: str = Field(
        default="",
        description="Password that unlocks admin-only controls",
    )
    assistant_ai_enabled: bool = Field(
        default=True,
        description="Allow the support assistant to use the configured AI provider for open questions",
    )
    log_level: str = Field(default="INFO")
    data_freshness_hours: int = Field(default=48)

    # Unified probabilistic bias model.  The model is deliberately retrained
    # less often than the raw-data pipeline because its target horizon is four
    # weeks and daily coefficient churn is mostly noise.
    predictive_bias_refresh_days: int = Field(default=3, ge=1, le=14)
    predictive_bias_min_train_weeks: int = Field(default=78, ge=52)
    predictive_bias_horizon_weeks: int = Field(default=4, ge=1, le=13)

    # Backtest windows (weeks)
    backtest_windows: str = Field(default="1,4,13")

    # Breadth universe
    breadth_universe: str = Field(default="sp500")

    @property
    def backtest_window_list(self) -> list[int]:
        return [int(w.strip()) for w in self.backtest_windows.split(",")]

    @property
    def data_dir(self) -> Path:
        d = ROOT_DIR / "data"
        d.mkdir(exist_ok=True)
        return d

    @property
    def has_fred(self) -> bool:
        return bool(self.fred_api_key and self.fred_api_key != "your_fred_api_key_here")

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key != "your_openai_api_key_here")

    @property
    def has_alpaca(self) -> bool:
        placeholders = {"your_alpaca_api_key_id_here", "your_alpaca_api_secret_key_here"}
        return bool(
            self.alpaca_api_key_id
            and self.alpaca_api_secret_key
            and self.alpaca_api_key_id not in placeholders
            and self.alpaca_api_secret_key not in placeholders
        )

    @property
    def has_ai(self) -> bool:
        if self.ai_provider == "openai":
            return self.has_openai
        if self.ai_provider == "gemini":
            return bool(self.gemini_api_key)
        if self.ai_provider == "agnes":
            return bool(self.agnes_api_key)
        if self.ai_provider == "claude":
            return bool(self.anthropic_api_key)
        if self.ai_provider == "manus":
            return bool(self.manus_api_key)
        if self.ai_provider == "local":
            return True  # Ollama doesn't need an API key
        return False


# Singleton
settings = Settings()
