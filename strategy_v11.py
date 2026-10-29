import pandas as pd
import numpy as np


# GTF PRO SCANNER V11
# Swing BUY candidates and intraday SHORT candidates
# Paper trading only.


def analyze_stock(df, market_mode="BULLISH"):
    """
    Analyze OHLCV data and return a paper-trading candidate.

    df must contain Open, High, Low, Close and Volume.
    market_mode must be BULLISH or BEARISH.
    """

    if df is None or len(df) < 220:
        return None

    required = ["Open", "High", "Low", "Close", "Volume"]

    if not all(col in df.columns for col in required):
        return None

    df = df.copy()

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required)

    if len(df) < 220:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    if (close <= 0).any():
        return None

    # Trend indicators
    df["EMA20"] = close.ewm(span=20, adjust=False).mean()
    df["EMA50"] = close.ewm(span=50, adjust=False).mean()
    df["EMA200"] = close.ewm(span=200, adjust=False).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    # Average true range
    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    df["ATR"] = true_range.rolling(14).mean()

    # Volume confirmation
    df["AVG_VOLUME"] = volume.rolling(20).mean()

    # Use completed daily candles only.
    candle = df.iloc[-2]
    previous = df.iloc[-3]

    entry = float(candle["Close"])
    atr = float(candle["ATR"])
    rsi = float(candle["RSI"])

    if not np.isfinite([entry, atr, rsi]).all():
        return None

    if entry <= 0 or atr <= 0:
        return None

    if entry > 0 and atr / entry > 0.08:
        return None

    # Fail closed if required indicators are unavailable.
    if candle[["EMA20", "EMA50", "EMA200", "AVG_VOLUME"]].isna().any():
        return None

    if candle["AVG_VOLUME"] <= 0:
        return None

    relative_volume = (
        float(candle["Volume"]) / float(candle["AVG_VOLUME"])
    )

    if relative_volume < 1.30:
        return None

    # Bullish market: swing BUY setup
    if market_mode.upper() == "BULLISH":

        trend_ok = (
            candle["Close"] > candle["EMA20"]
            and candle["EMA20"] > candle["EMA50"]
            and candle["EMA50"] > candle["EMA200"]
        )

        momentum_ok = 52 <= rsi <= 68

        breakout_ok = (
            candle["Close"] > previous["High"]
        )

        if not (trend_ok and momentum_ok and breakout_ok):
            return None

        stop_loss = entry - (1.5 * atr)
        target = entry + (3.0 * atr)

        return {
            "mode": "SWING_BUY",
            "entry": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target": round(target, 2),
            "risk_per_share": round(entry - stop_loss, 2),
            "reward_risk": 2.0,
            "rsi": round(rsi, 2),
            "relative_volume": round(relative_volume, 2),
            "status": "PAPER_ONLY",
        }

    # Bearish market: intraday SHORT candidate.
    # Daily data alone cannot validate an intraday entry.
    if market_mode.upper() == "BEARISH":

        trend_ok = (
            candle["Close"] < candle["EMA20"]
            and candle["EMA20"] < candle["EMA50"]
        )

        momentum_ok = 32 <= rsi <= 48

        breakdown_ok = (
            candle["Close"] < previous["Low"]
        )

        if not (trend_ok and momentum_ok and breakdown_ok):
            return None

        return {
            "mode": "INTRADAY_SHORT_CANDIDATE",
            "reference_price": round(entry, 2),
            "status": "WAIT_FOR_INTRADAY_CONFIRMATION",
            "message": (
                "Daily setup only. Confirm with live intraday data "
                "before paper entry; close any paper position the same day."
            ),
        }

    # Sideways or unknown regime: no trade.
    return None