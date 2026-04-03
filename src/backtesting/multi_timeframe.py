"""
Multi-Timeframe Filter v0.9 — 4h trend direction + 1h signal entries.

Standard practice: higher timeframe determines DIRECTION, lower timeframe finds ENTRY.
- 4h EMA(50) > EMA(200) → only LONG signals allowed on 1h
- 4h EMA(50) < EMA(200) → only SHORT signals allowed on 1h
- Flat on 4h → allow both directions on 1h
"""

import numpy as np
import pandas as pd
from loguru import logger

from src.data import MarketDataFetcher


def fetch_higher_timeframe(
    fetcher: MarketDataFetcher,
    symbol: str,
    start,
    end,
    higher_tf: str = "4h",
) -> pd.DataFrame | None:
    """Fetch higher timeframe data for trend determination."""
    try:
        logger.info(f"Fetching {higher_tf} data for trend filter...")
        prices = fetcher.fetch_ohlcv_full(
            symbol=symbol, timeframe=higher_tf, start=start, end=end,
        )
        if prices is not None and len(prices) > 50:
            logger.info(f"Got {len(prices)} {higher_tf} bars for trend filter")
            return prices
        return None
    except Exception as e:
        logger.warning(f"Higher TF fetch failed: {e}")
        return None


def compute_trend_filter(
    higher_tf_prices: pd.DataFrame,
    fast_ema: int = 50,
    slow_ema: int = 200,
) -> pd.Series:
    """
    Compute trend direction from higher timeframe.

    Returns Series: +1 (uptrend), -1 (downtrend), 0 (no clear trend)
    """
    close = higher_tf_prices["close"]

    ema_fast = close.ewm(span=fast_ema).mean()
    ema_slow = close.ewm(span=slow_ema).mean()

    # Trend strength: distance between EMAs as % of price
    spread = (ema_fast - ema_slow) / close
    threshold = 0.01  # 1% minimum spread to confirm trend

    trend = pd.Series(0, index=higher_tf_prices.index)
    trend[spread > threshold] = 1   # uptrend
    trend[spread < -threshold] = -1  # downtrend

    return trend


def apply_trend_filter(
    signals_1h: pd.Series,
    trend_4h: pd.Series,
    prices_1h: pd.DataFrame,
) -> pd.Series:
    """
    Filter 1h signals by 4h trend direction.

    In uptrend: only keep longs (remove shorts)
    In downtrend: only keep shorts (remove longs)
    Neutral: keep all signals
    """
    # Resample 4h trend to 1h (forward-fill)
    trend_resampled = trend_4h.reindex(prices_1h.index, method="ffill").fillna(0).astype(int)

    filtered = signals_1h.copy()

    # Uptrend: remove shorts
    filtered[(trend_resampled == 1) & (signals_1h == -1)] = 0

    # Downtrend: remove longs
    filtered[(trend_resampled == -1) & (signals_1h == 1)] = 0

    # Stats
    removed = (signals_1h != 0).sum() - (filtered != 0).sum()
    total = (signals_1h != 0).sum()
    pct = removed / max(total, 1) * 100

    logger.info(
        f"Trend filter: removed {removed}/{total} signals ({pct:.0f}%), "
        f"uptrend={int((trend_resampled == 1).sum())}h, "
        f"downtrend={int((trend_resampled == -1).sum())}h, "
        f"neutral={int((trend_resampled == 0).sum())}h"
    )

    return filtered


def get_trend_context(higher_tf_prices: pd.DataFrame) -> dict:
    """Get trend info for Claude prompt."""
    if higher_tf_prices is None or len(higher_tf_prices) < 200:
        return {}

    close = higher_tf_prices["close"]
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()

    current_trend = "uptrend" if ema50.iloc[-1] > ema200.iloc[-1] else "downtrend"
    trend_strength = abs(ema50.iloc[-1] - ema200.iloc[-1]) / close.iloc[-1]

    # % time in each regime
    spread = ema50 - ema200
    pct_up = (spread > 0).sum() / len(spread) * 100
    pct_down = (spread < 0).sum() / len(spread) * 100

    # Recent trend changes
    trend_sign = np.sign(spread)
    changes = (trend_sign != trend_sign.shift(1)).sum()

    return {
        "current_4h_trend": current_trend,
        "trend_strength": f"{trend_strength:.2%}",
        "pct_time_uptrend": f"{pct_up:.0f}%",
        "pct_time_downtrend": f"{pct_down:.0f}%",
        "trend_changes_count": int(changes),
        "note": (
            f"4h trend is {current_trend} (strength {trend_strength:.2%}). "
            f"Market spent {pct_up:.0f}% in uptrend, {pct_down:.0f}% in downtrend. "
            f"Trend changed {changes} times over the period. "
            f"{'FOLLOW THE TREND — prefer shorts.' if current_trend == 'downtrend' else 'FOLLOW THE TREND — prefer longs.'}"
        ),
    }
