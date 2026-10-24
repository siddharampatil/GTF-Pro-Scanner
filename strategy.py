import warnings
import pandas as pd
import yfinance as yf

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

warnings.filterwarnings("ignore")

# ==========================================
# GTF PRO SCANNER V10
# SWING TRADING STRATEGY
# ==========================================

MIN_DATA = 220

MIN_SCORE = 80
MIN_ADX = 22
MIN_RVOL = 1.30

MIN_RSI = 52
MAX_RSI = 68

MIN_REWARD_RISK = 2.0

MAX_EXTENSION_ATR = 2.0

# Cache the market trend so we do not download
# Nifty data separately for every stock.
_MARKET_BULLISH = None


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
            timeout=20
        )

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]

        if not all(col in df.columns for col in required):
            return None

        df = df[required].copy()

        for col in required:
            df[col] = pd.to_numeric(
                df[col], errors="coerce"
            )

        df = df.dropna(subset=required)
        df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()

        if len(df) < MIN_DATA:
            return None

        if (df["Close"] <= 0).any():
            return None

        return df

    except Exception as exc:
        print(f"DATA ERROR {symbol}: {exc}")
        return None


def market_is_bullish():
    """
    Trade only when Nifty shows a bullish daily trend.
    Fail closed when market data is unavailable.
    """

    global _MARKET_BULLISH

    if _MARKET_BULLISH is not None:
        return _MARKET_BULLISH

    df = download_data("^NSEI")

    if df is None:
        print("MARKET FILTER: Nifty data unavailable")
        _MARKET_BULLISH = False
        return False

    # Use the last completed daily candle.
    candle = df.iloc[-2]

    close = float(candle["Close"])

    ema20 = float(
        EMAIndicator(df["Close"], window=20)
        .ema_indicator().iloc[-2]
    )

    ema50 = float(
        EMAIndicator(df["Close"], window=50)
        .ema_indicator().iloc[-2]
    )

    _MARKET_BULLISH = (
        close > ema20 > ema50
    )

    print(
        "MARKET FILTER:",
        "BULLISH" if _MARKET_BULLISH else "NOT BULLISH"
    )

    return _MARKET_BULLISH


def scan_stock(symbol):
    """
    Find a potential bullish swing-trading setup.

    Returns a dictionary for a qualifying stock,
    otherwise returns None.
    """

    try:
        if not market_is_bullish():
            return None

        df = download_data(symbol)

        if df is None:
            return None

        close_series = df["Close"]
        high_series = df["High"]
        low_series = df["Low"]
        volume_series = df["Volume"]

        # Indicators are calculated using daily candles.
        df["EMA20"] = EMAIndicator(
            close_series, window=20
        ).ema_indicator()

        df["EMA50"] = EMAIndicator(
            close_series, window=50
        ).ema_indicator()

        df["EMA200"] = EMAIndicator(
            close_series, window=200
        ).ema_indicator()

        df["RSI"] = RSIIndicator(
            close_series, window=14
        ).rsi()

        macd = MACD(close_series)

        df["MACD"] = macd.macd()
        df["MACD_SIGNAL"] = macd.macd_signal()

        adx = ADXIndicator(
            high_series,
            low_series,
            close_series,
            window=14
        )

        df["ADX"] = adx.adx()
        df["PLUS_DI"] = adx.adx_pos()
        df["MINUS_DI"] = adx.adx_neg()

        atr = AverageTrueRange(
            high_series,
            low_series,
            close_series,
            window=14
        )

        df["ATR"] = atr.average_true_range()

        df["AVG_VOLUME20"] = (
            volume_series.rolling(20).mean()
        )

        # The newest daily candle can be incomplete.
        # Use the previous completed candle for signals.
        candle = df.iloc[-2]

        # Historical reference period excludes the
        # signal candle and the newest possibly partial day.
        prior = df.iloc[-22:-2]

        if len(prior) < 20:
            return None

        required_values = [
            candle["Close"],
            candle["High"],
            candle["Low"],
            candle["EMA20"],
            candle["EMA50"],
            candle["EMA200"],
            candle["RSI"],
            candle["ADX"],
            candle["PLUS_DI"],
            candle["MINUS_DI"],
            candle["MACD"],
            candle["MACD_SIGNAL"],
            candle["ATR"],
            candle["AVG_VOLUME20"]
        ]

        if pd.isna(required_values).any():
            return None

        close = float(candle["Close"])
        high = float(candle["High"])

        ema20 = float(candle["EMA20"])
        ema50 = float(candle["EMA50"])
        ema200 = float(candle["EMA200"])

        rsi = float(candle["RSI"])
        adx_value = float(candle["ADX"])

        plus_di = float(candle["PLUS_DI"])
        minus_di = float(candle["MINUS_DI"])

        macd_value = float(candle["MACD"])
        macd_signal = float(candle["MACD_SIGNAL"])

        atr_value = float(candle["ATR"])

        avg_volume = float(candle["AVG_VOLUME20"])
        volume = float(candle["Volume"])

        if atr_value <= 0 or avg_volume <= 0:
            return None

        # Relative volume.
        rvol = volume / avg_volume

        # Breakout level from the previous 20 completed
        # sessions, excluding the signal candle.
        prior_high = float(prior["High"].max())

        # ------------------------------------------
        # STRICT ENTRY FILTERS
        # ------------------------------------------

        # 1. Strong bullish stock trend.
        trend_ok = (
            close > ema20
            and ema20 > ema50
            and ema50 > ema200
        )

        # 2. Avoid excessively extended stocks.
        extension_atr = (close - ema20) / atr_value

        extension_ok = (
            0 <= extension_atr <= MAX_EXTENSION_ATR
        )

        # 3. Momentum must be positive but controlled.
        rsi_ok = MIN_RSI <= rsi <= MAX_RSI

        # 4. Trend must have adequate strength.
        adx_ok = (
            adx_value >= MIN_ADX
            and plus_di > minus_di
        )

        # 5. Volume must be above average.
        volume_ok = rvol >= MIN_RVOL

        # 6. MACD must confirm positive momentum.
        macd_ok = macd_value > macd_signal

        # 7. Completed candle must break above
        # the previous 20-session high.
        breakout_ok = close > prior_high

        if not all([
            trend_ok,
            extension_ok,
            rsi_ok,
            adx_ok,
            volume_ok,
            macd_ok,
            breakout_ok
        ]):
            return None

        # ------------------------------------------
        # ENTRY, STOP-LOSS AND ONE TARGET
        # ------------------------------------------

        # Entry trigger is slightly above the breakout
        # candle high. This is a planned trigger, not
        # a guaranteed execution price.
        buy = high + (0.05 * atr_value)

        # Recent support: previous completed candles.
        swing_low = float(
            df["Low"].iloc[-12:-2].min()
        )

        # Use the tighter of support-based and ATR-based
        # stops while keeping the stop below the entry.
        sl = max(
            swing_low,
            buy - (1.5 * atr_value)
        )

        risk = buy - sl

        if risk <= 0:
            return None

        # Reject stops that are too tight or too wide.
        risk_atr = risk / atr_value

        if not 0.5 <= risk_atr <= 2.0:
            return None

        # Exactly one target: minimum 1:2 planned R:R.
        target = buy + (MIN_REWARD_RISK * risk)

        reward_risk = (target - buy) / risk

        if reward_risk < MIN_REWARD_RISK:
            return None

        # ------------------------------------------
        # SETUP QUALITY SCORE
        # This is NOT a probability of winning.
        # ------------------------------------------

        score = 0

        # Trend quality: 25 points.
        score += 25

        # Confirmed breakout: 20 points.
        score += 20

        # RSI momentum: 10 points.
        score += 10

        # Trend strength: 10 points.
        if adx_value >= 30:
            score += 10
        else:
            score += 7

        # Relative volume: 15 points.
        if rvol >= 2.0:
            score += 15
        else:
            score += 10

        # MACD confirmation: 10 points.
        score += 10

        # Controlled distance from EMA20: 10 points.
        if extension_atr <= 1.0:
            score += 10
        else:
            score += 7

        if score < MIN_SCORE:
            return None

        clean_symbol = symbol.upper().replace(".NS", "")

        return {
            "symbol": clean_symbol,
            "direction": "BUY",
            "setup": "20-DAY BREAKOUT",
            "score": int(score),

            "buy": round(buy, 2),
            "sl": round(sl, 2),
            "target": round(target, 2),

            "risk_per_share": round(risk, 2),
            "reward_per_share": round(target - buy, 2),
            "reward_risk": round(reward_risk, 2),

            "rvol": round(rvol, 2),
            "rsi": round(rsi, 2),
            "adx": round(adx_value, 2),
            "atr": round(atr_value, 2),

            "signal_candle_date": str(
                df.index[-2].date()
            )
        }

    except Exception as exc:
        print(f"SCAN ERROR {symbol}: {exc}")
        return None