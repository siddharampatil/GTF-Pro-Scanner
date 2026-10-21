import warnings
import pandas as pd
import yfinance as yf

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

warnings.filterwarnings("ignore")

# ==========================================
# GTF PRO SCANNER V9 - SAFER TRADE STRATEGY
# ==========================================

MIN_DATA = 220
MIN_ADX = 20
MIN_RVOL = 1.20
MIN_RSI = 52
MAX_RSI = 68
MIN_REWARD_RISK = 2.0

# Cache the market trend to avoid downloading Nifty
# separately for every stock.
_MARKET_BULLISH = None


def download_data(symbol, period="2y"):
    try:
        df = yf.download(
            symbol,
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=20
        )

        if df is None or df.empty:
            return None

        # Handle yfinance MultiIndex columns.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.loc[:, ~df.columns.duplicated()]
        required = ["Open", "High", "Low", "Close", "Volume"]

        if not all(col in df.columns for col in required):
            return None

        df = df[required].copy()

        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna()

        if len(df) < MIN_DATA:
            return None

        return df

    except Exception as e:
        print(f"Download error {symbol}: {e}")
        return None


def market_is_bullish():
    """
    Only allow fresh long signals when Nifty's daily
    trend meets the bullish filter.
    """
    global _MARKET_BULLISH

    if _MARKET_BULLISH is not None:
        return _MARKET_BULLISH

    df = download_data("^NSEI")

    if df is None:
        # Fail closed: do not issue fresh long signals
        # when the market trend cannot be verified.
        _MARKET_BULLISH = False
        print("Market filter unavailable: fresh longs blocked.")
        return False

    close = df["Close"]
    ema20 = EMAIndicator(close, window=20).ema_indicator()
    ema50 = EMAIndicator(close, window=50).ema_indicator()

    last = len(df) - 1

    _MARKET_BULLISH = bool(
        close.iloc[last] > ema20.iloc[last]
        and close.iloc[last] > ema50.iloc[last]
        and ema20.iloc[last] > ema50.iloc[last]
    )

    return _MARKET_BULLISH


def scan_stock(symbol):
    """
    Return a signal dictionary compatible with the
    existing main.py scanner.

    This strategy screens long setups only.
    A signal is not a guarantee of profit.
    """

    try:
        # Do not issue new long signals in a bearish
        # or unverified market.
        if not market_is_bullish():
            return None

        symbol = str(symbol).strip()

        if not symbol.endswith(".NS") and not symbol.startswith("^"):
            symbol += ".NS"

        df = download_data(symbol)

        if df is None:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        # --------------------------
        # Technical indicators
        # --------------------------

        df["EMA20"] = EMAIndicator(
            close, window=20
        ).ema_indicator()

        df["EMA50"] = EMAIndicator(
            close, window=50
        ).ema_indicator()

        df["EMA200"] = EMAIndicator(
            close, window=200
        ).ema_indicator()

        df["RSI"] = RSIIndicator(
            close, window=14
        ).rsi()

        macd_obj = MACD(close)
        df["MACD"] = macd_obj.macd()
        df["MACD_SIGNAL"] = macd_obj.macd_signal()

        df["ADX"] = ADXIndicator(
            high, low, close, window=14
        ).adx()

        df["ATR"] = AverageTrueRange(
            high, low, close, window=14
        ).average_true_range()

        df["VOL_AVG"] = volume.rolling(20).mean()

        df = df.dropna()

        if len(df) < 30:
            return None

        # Use the latest completed daily candle.
        # Do not use today's incomplete candle.
        if len(df) < 3:
            return None

        candle = df.iloc[-2]
        previous = df.iloc[-3]

        entry = float(candle["Close"])
        ema20 = float(candle["EMA20"])
        ema50 = float(candle["EMA50"])
        ema200 = float(candle["EMA200"])
        rsi = float(candle["RSI"])
        adx = float(candle["ADX"])
        atr = float(candle["ATR"])
        macd = float(candle["MACD"])
        macd_signal = float(candle["MACD_SIGNAL"])

        avg_volume = float(candle["VOL_AVG"])
        current_volume = float(candle["Volume"])

        if entry <= 0 or atr <= 0 or avg_volume <= 0:
            return None

        rvol = current_volume / avg_volume

        # --------------------------
        # Trend and quality filters
        # --------------------------

        if not (
            entry > ema20 > ema50 > ema200
        ):
            return None

        if not MIN_RSI <= rsi <= MAX_RSI:
            return None

        if adx < MIN_ADX:
            return None

        if rvol < MIN_RVOL:
            return None

        # Avoid stocks already stretched too far
        # above their 20-day EMA.
        if entry - ema20 > 2.0 * atr:
            return None

        # --------------------------
        # Breakout confirmation
        # --------------------------

        # Compare the latest completed candle against
        # the preceding 20 completed daily highs.
        prior_20_high = float(
            df["High"].iloc[-22:-2].max()
        )

        breakout = entry > prior_20_high

        # Alternative: a breakout retest that holds
        # above the prior resistance area.
        retest = bool(
            float(candle["Low"]) <= prior_20_high
            and entry > prior_20_high
            and entry > float(previous["Close"])
        )

        if not (breakout or retest):
            return None

        # Require positive MACD momentum.
        if macd <= macd_signal:
            return None

        # --------------------------
        # Stop-loss calculation
        # --------------------------

        # Use the recent swing low and ATR together.
        recent_swing_low = float(
            df["Low"].iloc[-7:-1].min()
        )

        atr_stop = entry - (1.5 * atr)

        # The stop is placed below the entry using
        # the tighter of these two protective levels.
        sl = max(recent_swing_low, atr_stop)

        risk = entry - sl

        if risk <= 0:
            return None

        # Reject unusually tight or wide stops.
        if risk < 0.8 * atr:
            return None

        if risk > 2.0 * atr:
            return None

        # --------------------------
        # Targets: minimum 2R
        # --------------------------

        t1 = entry + (2.0 * risk)
        t2 = entry + (3.0 * risk)
        t3 = entry + (4.0 * risk)

        reward_risk = (t1 - entry) / risk

        if reward_risk < MIN_REWARD_RISK:
            return None

        # --------------------------
        # Quality score (not probability)
        # --------------------------

        score = 0

        # Trend strength
        score += 25

        # Momentum
        if 55 <= rsi <= 65:
            score += 15
        else:
            score += 10

        # ADX trend confirmation
        if adx >= 30:
            score += 15
        else:
            score += 10

        # Relative volume
        if rvol >= 1.5:
            score += 15
        else:
            score += 10

        # MACD confirmation
        score += 15

        # Confirmed breakout
        score += 15

        score = min(score, 100)

        result = {
            "symbol": symbol,
            "score": int(score),
            "buy": round(entry, 2),
            "sl": round(sl, 2),
            "t1": round(t1, 2),
            "t2": round(t2, 2),
            "t3": round(t3, 2),
            "rsi": round(rsi, 2),
            "adx": round(adx, 2),
            "rvol": round(rvol, 2),
            "atr": round(atr, 2),
            "reward_risk": round(reward_risk, 2),
            "setup": "CONFIRMED_BREAKOUT"
        }

        print(
            f"V9 QUALIFIED: {symbol} | "
            f"Score={score} | "
            f"Entry={entry:.2f} | "
            f"SL={sl:.2f} | "
            f"R:R={reward_risk:.2f}"
        )

        return result

    except Exception as e:
        print(f"V9 scan error {symbol}: {e}")
        return None