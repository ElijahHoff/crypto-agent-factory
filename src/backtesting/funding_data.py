"""
Funding Rate Data Fetcher v0.4 — Fetch funding rate history from exchanges.

Uses ccxt to get funding rate data for strategies that need it.
"""

import pandas as pd
from datetime import datetime, timezone, timedelta
from loguru import logger

try:
    import ccxt
    HAS_CCXT = True
except ImportError:
    HAS_CCXT = False


EXCHANGE_MAP = {
    "binance": "binanceusdm",
    "bybit": "bybit",
    "okx": "okx",
}


def fetch_funding_rates(
    symbol: str = "BTC/USDT:USDT",
    exchange_id: str = "binance",
    since: datetime | None = None,
    limit: int = 1000,
) -> pd.DataFrame | None:
    """
    Fetch historical funding rates.

    Returns DataFrame with columns: [timestamp, funding_rate, symbol]
    """
    if not HAS_CCXT:
        logger.warning("ccxt not installed — funding rates unavailable")
        return None

    exchange_class = EXCHANGE_MAP.get(exchange_id, exchange_id)
    try:
        exchange = getattr(ccxt, exchange_class)({"enableRateLimit": True})
    except AttributeError:
        logger.error(f"Exchange {exchange_class} not available in ccxt")
        return None

    # Normalize symbol for futures
    if ":USDT" not in symbol and "USDT" in symbol:
        symbol = symbol + ":USDT"

    since_ts = int(since.timestamp() * 1000) if since else None

    try:
        logger.info(f"Fetching funding rates: {symbol} from {exchange_id}")

        if hasattr(exchange, 'fetch_funding_rate_history'):
            rates = exchange.fetch_funding_rate_history(
                symbol=symbol,
                since=since_ts,
                limit=limit,
            )
        else:
            logger.warning(f"{exchange_id} doesn't support fetch_funding_rate_history")
            return None

        if not rates:
            logger.warning("No funding rate data returned")
            return None

        df = pd.DataFrame(rates)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
        if "fundingRate" in df.columns:
            df.rename(columns={"fundingRate": "funding_rate"}, inplace=True)

        logger.info(f"Got {len(df)} funding rate records")
        return df[["funding_rate"]].copy() if "funding_rate" in df.columns else df

    except Exception as e:
        logger.warning(f"Funding rate fetch failed: {e}")
        return None


def fetch_multi_exchange_funding(
    symbol: str = "BTC/USDT",
    exchanges: list | None = None,
    since: datetime | None = None,
) -> dict:
    """
    Fetch funding rates from multiple exchanges.

    Returns dict of {exchange_id: DataFrame}
    """
    if exchanges is None:
        exchanges = ["binance", "bybit", "okx"]

    results = {}
    for ex in exchanges:
        df = fetch_funding_rates(symbol=symbol, exchange_id=ex, since=since)
        if df is not None and len(df) > 0:
            results[ex] = df

    logger.info(f"Funding rates fetched from {len(results)}/{len(exchanges)} exchanges")
    return results


def compute_funding_features(funding_data: dict) -> pd.DataFrame | None:
    """
    Compute cross-exchange funding features.

    Takes multi-exchange funding dict and returns feature DataFrame.
    """
    if len(funding_data) < 2:
        logger.warning("Need ≥2 exchanges for cross-exchange features")
        return None

    # Align all exchanges to common index
    aligned = {}
    for ex, df in funding_data.items():
        if "funding_rate" in df.columns:
            aligned[ex] = df["funding_rate"].resample("8h").last()

    if len(aligned) < 2:
        return None

    combined = pd.DataFrame(aligned)
    combined = combined.dropna(how="all").ffill()

    features = pd.DataFrame(index=combined.index)
    features["funding_median"] = combined.median(axis=1)
    features["funding_std"] = combined.std(axis=1)
    features["funding_range"] = combined.max(axis=1) - combined.min(axis=1)

    # Z-score of max divergent exchange
    for col in combined.columns:
        z = (combined[col] - features["funding_median"]) / features["funding_std"].replace(0, 1e-10)
        features[f"zscore_{col}"] = z

    features["max_divergence_zscore"] = features[[c for c in features.columns if "zscore_" in c]].abs().max(axis=1)

    # Trends
    features["funding_trend_8h"] = features["funding_median"].diff(1)
    features["divergence_trend"] = features["max_divergence_zscore"].diff(1)

    # Correlation
    if len(combined.columns) >= 2:
        features["cross_exchange_corr"] = combined.rolling(21).corr().groupby(level=0).mean().mean(axis=1)

    logger.info(f"Computed {len(features.columns)} funding features over {len(features)} periods")
    return features
