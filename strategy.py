# GTF PRO SCANNER V11
# Bullish market: NSE cash swing BUY
# Bearish market: NSE cash intraday SHORT
# PAPER SIGNALS ONLY

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator

IST = ZoneInfo("Asia/Kolkata")

CAPITAL = 5000.0
RISK_PER_TRADE = 50.0
DAILY_LOSS_LIMIT = 100.0
MIN_REWARD_RISK = 2.0
MIN_ADX = 22.0
MIN_RVOL = 1.30

def download_data(symbol, period="1y", interval="1d"):
    """Download and validate OHLCV data."""
    try:
        ticker = symbol.upper().strip()
        if not ticker.startswith("^") and not ticker.endswith(".NS"):
            ticker += ".NS"

        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=20,
        )

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in required):
            return None

        df = df[required].copy()
        df = df.apply(pd.to_numeric, errors="coerce")
        df.dropna(inplace=True)
        return df if len(df) >= 60 else None

    except Exception as exc:
        print(f"DATA ERROR {symbol}: {exc}")
        return None


def market_regime():
    """
    Uses the last completed daily candle.
    Returns BULLISH, BEARISH, MIXED, or DATA_UNAVAILABLE.
    """
    df = download_data("^NSEI", period="2y")

    if df is None or len(df) < 55:
        print("MARKET: DATA_UNAVAILABLE")
        return "DATA_UNAVAILABLE"

    # Exclude today's potentially incomplete candle.
    today = datetime.now(IST).date()
    last_date = pd.Timestamp(df.index[-1]).date()
    pos = len(df) - 2 if last_date >= today else len(df) - 1

    if pos < 50:
        return "DATA_UNAVAILABLE"

    close = df["Close"].iloc[:pos + 1]
    ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    price = float(close.iloc[-1])

    print(f"NIFTY close={price:.2f}, EMA20={ema20:.2f}, EMA50={ema50:.2f}")

    if price > ema20 > ema50:
        regime = "BULLISH"
    elif price < ema20 < ema50:
        regime = "BEARISH"
    else:
        regime = "MIXED"

    print(f"MARKET REGIME: {regime}")
    return regime


def scan_stock_v11(symbol, mode):
    """
    Daily-candle screening only.
    This function does not create an intraday short entry.
    Intraday shorts require a separate live intraday confirmation module.
    """
    if mode not in ("SWING_BUY", "INTRADAY_SHORT"):
        return None

    df = download_data(symbol, period="1y", interval="1d")

    if df is None or len(df) < 220:
        return None

    today = datetime.now(IST).date()
    last_date = pd.Timestamp(df.index[-1]).date()
    pos = len(df) - 2 if last_date >= today else len(df) - 1

    if pos < 200:
        return None

    df = df.iloc[:pos + 1].copy()

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    ema20 = EMAIndicator(close, window=20).ema_indicator()
    ema50 = EMAIndicator(close, window=50).ema_indicator()
    ema200 = EMAIndicator(close, window=200).ema_indicator()
    rsi = RSIIndicator(close, window=14).rsi()

    adx_obj = ADXIndicator(high, low, close, window=14)
    adx = adx_obj.adx()
    plus_di = adx_obj.adx_pos()
    minus_di = adx_obj.adx_neg()

    avg_volume = volume.rolling(20).mean()

    price = float(close.iloc[-1])
    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    rsi_now = float(rsi.iloc[-1])
    adx_now = float(adx.iloc[-1])
    vol_avg = float(avg_volume.iloc[-1])

    if pd.isna(vol_avg) or vol_avg <= 0:
        return None

    rvol = float(volume.iloc[-1]) / vol_avg
    if adx_now < MIN_ADX or rvol < MIN_RVOL:
        return None

    if mode == "SWING_BUY":
        if not (price > e20 > e50 > e200):
            return None
        if not (52 <= rsi_now <= 68):
            return None
        if price <= float(high.iloc[-21:-1].max()):
            return None

        entry = float(high.iloc[-1]) + 0.05 * float(
            (high - low).rolling(14).mean().iloc[-1]
        )
        stop = min(float(low.iloc[-10:].min()), entry * 0.99)

    else:
        # Candidate for further intraday confirmation only.
        if not (price < e20 < e50 < e200):
            return None
        if not (32 <= rsi_now <= 48):
            return None
        if float(minus_di.iloc[-1]) <= float(plus_di.iloc[-1]):
            return None
        if price >= float(low.iloc[-21:-1].min()):
            return None

        # This is a daily reference level, NOT an executable intraday entry.
        entry = price
        stop = max(float(high.iloc[-10:].max()), entry * 1.01)

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return None

    qty_by_risk = int(RISK_PER_TRADE // risk_per_share)
    qty_by_capital = int(CAPITAL // entry)
    quantity = min(qty_by_risk, qty_by_capital)

    if quantity < 1:
        return None

    target = (
        entry + MIN_REWARD_RISK * risk_per_share
        if mode == "SWING_BUY"
        else entry - MIN_REWARD_RISK * risk_per_share
    )

    return {
        "symbol": symbol.replace(".NS", ""),
        "mode": mode,
        "reference_entry": round(entry, 2),
        "stop_loss": round(stop, 2),
        "target": round(target, 2),
        "quantity": quantity,
        "planned_risk": round(quantity * risk_per_share, 2),
        "reward_risk": MIN_REWARD_RISK,
        "market_price_date": str(df.index[-1]),
        "status": "PAPER_ONLY",
    }


