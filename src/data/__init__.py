"""Market data fetching via ccxt with quality checks."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import ccxt
import numpy as np
import pandas as pd
from loguru import logger

from src.config import settings


class MarketDataFetcher:
    """Fetch and validate OHLCV + auxiliary market data from exchanges."""

    CACHE_DIR = Path("data/cache")

    def __init__(self, exchange_id: str | None = None) -> None:
        self.exchange_id = exchange_id or settings.exchange_id
        self._exchange: ccxt.Exchange | None = None

    @property
    def exchange(self) -> ccxt.Exchange:
        if self._exchange is None:
            cls = getattr(ccxt, self.exchange_id)
            self._exchange = cls({
                "apiKey": settings.exchange_api_key or None,
                "secret": settings.exchange_secret or None,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            })
        return self._exchange

    # ── OHLCV ────────────────────────────────────────────────────────────

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: datetime | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles and return a clean DataFrame."""
        since_ts = int(since.timestamp() * 1000) if since else None
        logger.info(f"Fetching {symbol} {timeframe} OHLCV (limit={limit})...")

        raw = self.exchange.fetch_ohlcv(symbol, timeframe, since=since_ts, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp").sort_index()

        # Basic quality checks
        self._check_ohlcv_quality(df, symbol)
        return df

    def fetch_ohlcv_full(
        self,
        symbol: str,
        timeframe: str = "1h",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch full OHLCV history by paginating."""
        all_frames: list[pd.DataFrame] = []
        since = start or datetime(2020, 1, 1)
        end = end or datetime.utcnow()
        limit = 1000

        while since < end:
            df = self.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if df.empty:
                break
            all_frames.append(df)
            since = df.index[-1].to_pydatetime() + timedelta(milliseconds=1)
            logger.debug(f"  ...fetched up to {since}")

        if not all_frames:
            return pd.DataFrame()

        result = pd.concat(all_frames).sort_index()
        result = result[~result.index.duplicated(keep="first")]
        return result

    # ── Funding Rates ────────────────────────────────────────────────────

    def fetch_funding_rates(self, symbol: str, since: datetime | None = None) -> pd.DataFrame:
        """Fetch historical funding rates (exchange-dependent)."""
        if not hasattr(self.exchange, "fetch_funding_rate_history"):
            logger.warning(f"{self.exchange_id} does not support funding rate history")
            return pd.DataFrame()

        since_ts = int(since.timestamp() * 1000) if since else None
        raw = self.exchange.fetch_funding_rate_history(symbol, since=since_ts, limit=1000)

        rows = []
        for entry in raw:
            rows.append({
                "timestamp": pd.to_datetime(entry["timestamp"], unit="ms", utc=True),
                "funding_rate": entry.get("fundingRate", 0.0),
                "symbol": symbol,
            })
        return pd.DataFrame(rows).set_index("timestamp").sort_index() if rows else pd.DataFrame()

    # ── Open Interest ────────────────────────────────────────────────────

    def fetch_open_interest(self, symbol: str) -> dict[str, Any]:
        """Fetch current open interest snapshot."""
        if not hasattr(self.exchange, "fetch_open_interest"):
            return {}
        oi = self.exchange.fetch_open_interest(symbol)
        return {
            "symbol": symbol,
            "open_interest": oi.get("openInterestAmount", 0),
            "open_interest_value": oi.get("openInterestValue", 0),
            "timestamp": oi.get("timestamp"),
        }

    # ── Universe Selection ───────────────────────────────────────────────

    def get_top_symbols(self, quote: str = "USDT", n: int = 30) -> list[str]:
        """Get top-N symbols by 24h volume (survivorship-aware: current snapshot only)."""
        self.exchange.load_markets()
        tickers = self.exchange.fetch_tickers()

        candidates = []
        for sym, t in tickers.items():
            if not sym.endswith(f"/{quote}"):
                continue
            vol = t.get("quoteVolume", 0) or 0
            candidates.append((sym, vol))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in candidates[:n]]

    # ── Quality Checks ───────────────────────────────────────────────────

    @staticmethod
    def _check_ohlcv_quality(df: pd.DataFrame, symbol: str) -> None:
        """Run basic OHLCV quality checks and log warnings."""
        if df.empty:
            logger.warning(f"[{symbol}] Empty OHLCV data!")
            return

        # Duplicate timestamps
        n_dup = df.index.duplicated().sum()
        if n_dup > 0:
            logger.warning(f"[{symbol}] {n_dup} duplicate timestamps found")

        # Missing candles (gaps in regular frequency)
        if len(df) > 1:
            diffs = df.index.to_series().diff().dropna()
            median_diff = diffs.median()
            gaps = diffs[diffs > median_diff * 2]
            if len(gaps) > 0:
                logger.warning(f"[{symbol}] {len(gaps)} gaps detected (>{median_diff * 2})")

        # Zero-volume candles
        n_zero_vol = (df["volume"] == 0).sum()
        if n_zero_vol > 0:
            logger.warning(f"[{symbol}] {n_zero_vol} zero-volume candles")

        # OHLC sanity: high >= max(open, close) and low <= min(open, close)
        bad_hl = ((df["high"] < df["open"]) | (df["high"] < df["close"]) |
                  (df["low"] > df["open"]) | (df["low"] > df["close"]))
        n_bad = bad_hl.sum()
        if n_bad > 0:
            logger.warning(f"[{symbol}] {n_bad} candles with OHLC inconsistencies")

    # ── Caching ──────────────────────────────────────────────────────────

    def save_cache(self, df: pd.DataFrame, key: str) -> Path:
        """Save dataframe to parquet cache."""
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = self.CACHE_DIR / f"{key}.parquet"
        df.to_parquet(path)
        logger.info(f"Cached {len(df)} rows → {path}")
        return path

    def load_cache(self, key: str) -> pd.DataFrame | None:
        path = self.CACHE_DIR / f"{key}.parquet"
        if path.exists():
            logger.info(f"Loading cache: {path}")
            return pd.read_parquet(path)
        return None
