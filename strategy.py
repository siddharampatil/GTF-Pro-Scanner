# ==========================================
# GTF PRO SCANNER V10
# NSE CASH SWING TRADING
# ==========================================

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from ta.trend import (
    EMAIndicator,
    MACD,
    ADXIndicator,
)
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


IST = ZoneInfo("Asia/Kolkata")

MIN_DATA = 220
MIN_SCORE = 80
MIN_ADX = 22
MIN_RVOL = 1.30
MIN_RSI = 52
MAX_RSI = 68
MIN_REWARD_RISK = 2.0
MAX_EXTENSION_ATR = 2.0

_MARKET_BULLISH = None


# ==========================================
# DOWNLOAD DATA
# ==========================================

def download_data(symbol, period="2y"):
    """Download and validate daily stock/index data."""

    try:
        ticker = symbol.strip().upper()

        if not ticker.startswith("^") and not ticker.endswith(".NS"):
            ticker += ".NS"

        df = yf.download(
            ticker,
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=20,
        )

        if df is None or df.empty:
            print(f"DATA UNAVAILABLE: {ticker}")
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]

        if not all(col in df.columns for col in required):
            print(f"INVALID COLUMNS: {ticker}")
            return None

        df = df[required].copy()

        for col in required:
            df[col] = pd.to_numeric(
                df[col], errors="coerce"
            )

        df = df.dropna(subset=required)
        df = df.sort_index()

        if len(df) < MIN_DATA:
            print(
                f"INSUFFICIENT DATA: {ticker}, "
                f"rows={len(df)}"
            )
            return None

        return df

    except Exception as exc:
        print(f"DOWNLOAD ERROR {symbol}: {exc}")
        return None


# ==========================================
# FIND LAST COMPLETED DAILY CANDLE
# ==========================================

def latest_completed_position(df):
    """Avoid using today's unfinished daily candle."""

    if df is None or df.empty:
        return None

    today = datetime.now(IST).date()
    last_date = pd.Timestamp(df.index[-1]).date()

    if last_date >= today:
        if len(df) < 2:
            return None

        return len(df) - 2

    return len(df) - 1


# ==========================================
# NIFTY MARKET FILTER
# ==========================================

def market_is_bullish():
    """Require Nifty close > EMA20 > EMA50."""

    global _MARKET_BULLISH

    if _MARKET_BULLISH is not None:
        return _MARKET_BULLISH

    df = download_data("^NSEI")

    if df is None:
        print("MARKET DIAGNOSTIC: Nifty data unavailable")
        _MARKET_BULLISH = False
        return False

    pos = latest_completed_position(df)

    if pos is None or pos < 50:
        print("MARKET DIAGNOSTIC: No valid completed candle")
        _MARKET_BULLISH = False
        return False

    close_series = df["Close"]

    ema20_series = EMAIndicator(
        close_series, window=20
    ).ema_indicator()

    ema50_series = EMAIndicator(
        close_series, window=50
    ).ema_indicator()

    close = float(close_series.iloc[pos])
    ema20 = float(ema20_series.iloc[pos])
    ema50 = float(ema50_series.iloc[pos])

    print("========== NIFTY DIAGNOSTIC ==========")
    print("Candle date:", df.index[pos])
    print(f"Nifty close: {close:.2f}")
    print(f"EMA 20: {ema20:.2f}")
    print(f"EMA 50: {ema50:.2f}")
    print("Close > EMA20:", close > ema20)
    print("EMA20 > EMA50:", ema20 > ema50)

    _MARKET_BULLISH = close > ema20 > ema50

    print(
        "MARKET FILTER:",
        "BULLISH" if _MARKET_BULLISH else "NOT BULLISH"
    )
    print("======================================")

    return _MARKET_BULLISH


# ==========================================
# V10 STOCK SCANNER
# ==========================================

def scan_stock(symbol):
    """Return a candidate only when every V10 rule passes."""

    if not market_is_bullish():
        return None

    df = download_data(symbol)

    if df is None:
        return None

    pos = latest_completed_position(df)

    if pos is None or pos < MIN_DATA - 1:
        print(f"SKIP {symbol}: insufficient completed candles")
        return None

    # Use only candles up to the last completed session.
    data = df.iloc[:pos + 1].copy()

    close = data["Close"]
    high = data["High"]
    low = data["Low"]
    volume = data["Volume"]

    # Trend indicators
    ema20 = EMAIndicator(close, window=20).ema_indicator()
    ema50 = EMAIndicator(close, window=50).ema_indicator()
    ema200 = EMAIndicator(close, window=200).ema_indicator()

    # Momentum indicators
    rsi = RSIIndicator(close, window=14).rsi()

    macd_obj = MACD(
        close,
        window_fast=12,
        window_slow=26,
        window_sign=9,
    )

    macd_line = macd_obj.macd()
    macd_signal = macd_obj.macd_signal()

    adx_obj = ADXIndicator(
        high,
        low,
        close,
        window=14,
    )

    adx = adx_obj.adx()
    plus_di = adx_obj.adx_pos()
    minus_di = adx_obj.adx_neg()

    atr_series = AverageTrueRange(
        high,
        low,
        close,
        window=14,
    ).average_true_range()

    avg_volume = volume.rolling(20).mean()

    values = [
        close.iloc[-1],
        ema20.iloc[-1],
        ema50.iloc[-1],
        ema200.iloc[-1],
        rsi.iloc[-1],
        macd_line.iloc[-1],
        macd_signal.iloc[-1],
        adx.iloc[-1],
        plus_di.iloc[-1],
        minus_di.iloc[-1],
        atr_series.iloc[-1],
        avg_volume.iloc[-1],
    ]

    if any(pd.isna(value) for value in values):
        print(f"SKIP {symbol}: indicator data unavailable")
        return None

    price = float(close.iloc[-1])
    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    rsi_value = float(rsi.iloc[-1])
    adx_value = float(adx.iloc[-1])
    atr = float(atr_series.iloc[-1])
    average_vol = float(avg_volume.iloc[-1])

    if atr <= 0 or average_vol <= 0:
        return None

    rvol = float(volume.iloc[-1]) / average_vol
    extension = (price - e20) / atr

    # Keep existing strict V10 entry conditions.
    checks = {
        "trend": price > e20 > e50 > e200,
        "extension": 0 <= extension <= MAX_EXTENSION_ATR,
        "RSI": MIN_RSI <= rsi_value <= MAX_RSI,
        "ADX": (
            adx_value >= MIN_ADX
            and float(plus_di.iloc[-1])
            > float(minus_di.iloc[-1])
        ),
        "relative volume": rvol >= MIN_RVOL,
        "MACD": (
            float(macd_line.iloc[-1])
            > float(macd_signal.iloc[-1])
        ),
    }

    # Break above the preceding 20 completed sessions.
    if len(data) < 22:
        return None

    previous_high = float(
        high.iloc[-21:-1].max()
    )

    checks["20-day breakout"] = price > previous_high

    failed = [
        name for name, passed in checks.items()
        if not passed
    ]

    if failed:
        print(
            f"REJECT {symbol}: "
            + ", ".join(failed)
        )
        return None

    # Entry above signal candle high.
    signal_high = float(high.iloc[-1])
    buy = signal_high + 0.05 * atr

    # Stop based on recent support and ATR.
    recent_low = float(low.iloc[-10:].min())
    sl = max(recent_low, buy - 1.5 * atr)

    risk = buy - sl

    if risk <= 0:
        print(f"REJECT {symbol}: invalid stop-loss")
        return None

    risk_atr = risk / atr

    if not 0.5 <= risk_atr <= 2.0:
        print(f"REJECT {symbol}: risk outside allowed ATR range")
        return None

    target = buy + MIN_REWARD_RISK * risk
    reward = target - buy
    reward_risk = reward / risk

    if reward_risk < MIN_REWARD_RISK:
        return None

    # Quality score out of 100.
    score = 0

    score += 15  # Trend
    score += 10  # Price extension
    score += 15  # RSI
    score += 15  # ADX and directional trend
    score += 15  # Relative volume
    score += 10  # MACD
    score += 20  # Breakout

    if score < MIN_SCORE:
        print(f"REJECT {symbol}: score {score}")
        return None

    result = {
        "symbol": symbol.replace(".NS", ""),
        "setup": "V10_SWING",
        "buy": round(buy, 2),
        "sl": round(sl, 2),
        "target": round(target, 2),
        "score": score,
        "rvol": round(rvol, 2),
        "rsi": round(rsi_value, 2),
        "adx": round(adx_value, 2),
        "atr": round(atr, 2),
        "risk_per_share": round(risk, 2),
        "reward_per_share": round(reward, 2),
        "reward_risk": round(reward_risk, 2),
        "signal_candle_date": str(data.index[-1]),
    }

    print(
        f"QUALIFIED: {result['symbol']} | "
        f"Score={score} | "
        f"RVOL={rvol:.2f} | "
        f"RR={reward_risk:.2f}"
    )

    return result