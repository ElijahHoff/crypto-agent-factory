"""Application settings loaded from environment / .env file."""

from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM ---
    anthropic_api_key: str = Field(..., description="Anthropic API key")
    anthropic_model: str = Field("claude-sonnet-4-20250514", description="Model to use")

    # --- Database ---
    database_url: str = Field(
        "sqlite+aiosqlite:///./agent_factory.db",
        description="Async DB connection string",
    )
    redis_url: str = Field("redis://localhost:6379/0")

    # --- Exchange ---
    exchange_id: str = Field("binance")
    exchange_api_key: str = Field("")
    exchange_secret: str = Field("")

    # --- Backtesting defaults ---
    default_commission_bps: float = Field(10.0)
    default_slippage_bps: float = Field(5.0)
    default_funding_rate_bps: float = Field(1.0)

    # --- Risk limits ---
    max_leverage: float = Field(3.0)
    max_drawdown_pct: float = Field(15.0)
    max_daily_loss_pct: float = Field(3.0)
    max_position_size_pct: float = Field(10.0)

    # --- Pipeline ---
    experiment_dir: Path = Field(Path("./experiments"))
    log_level: str = Field("INFO")


settings = Settings()  # type: ignore[call-arg]
