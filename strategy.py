import time
import pandas as pd
import yfinance as yf
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

def safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default

def download_stock(symbol, interval="1d", period="2y"):
    for attempt in range(3):
        try:
            df = yf.download(
                tickers=symbol,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False
            )
            if df is None or df.empty:
                time.sleep(1)
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            if len(df) >= 200 or interval == "1wk":
                return df
        except Exception as e:
            print(f"{symbol}: {e}")
        time.sleep(1)
    return None

def get_market_trend():
    try:
        nifty = download_stock("^NSEI")
        if nifty is None:
            return "🟡 Unknown"
        c = nifty["Close"]
        e20 = EMAIndicator(c, 20).ema_indicator()
        e50 = EMAIndicator(c, 50).ema_indicator()
        if c.iloc[-1] > e20.iloc[-1] > e50.iloc[-1]:
            return "🟢 Bullish"
        if c.iloc[-1] < e20.iloc[-1] < e50.iloc[-1]:
            return "🔴 Bearish"
        return "🟡 Neutral"
    except Exception:
        return "🟡 Unknown"

MARKET_CONDITION = get_market_trend()

def identify_demand_zone(close, high, low, lookback=100):
    # Lightweight confirmation only: recent strong bullish candle followed by hold.
    try:
        body = (close - close.shift(1)).abs()
        avg_body = body.rolling(20).mean()
        for i in range(len(close)-2, max(20, len(close)-lookback), -1):
            if close.iloc[i] > close.iloc[i-1] and body.iloc[i] > avg_body.iloc[i] * 1.5:
                zl = float(low.iloc[i-1])
                zh = float(max(close.iloc[i-1], close.iloc[i-1]))
                return zl, zh
    except Exception:
        pass
    return None

def scan_stock(symbol):
    try:
        df = download_stock(symbol)
        if df is None or len(df) < 200:
            return None

        close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]
        ema20 = EMAIndicator(close, 20).ema_indicator()
        ema50 = EMAIndicator(close, 50).ema_indicator()
        ema200 = EMAIndicator(close, 200).ema_indicator()
        rsi = RSIIndicator(close, 14).rsi()
        macd = MACD(close)
        macd_line, macd_signal = macd.macd(), macd.macd_signal()
        adx = ADXIndicator(high, low, close, 14).adx()
        atr = AverageTrueRange(high, low, close, 14).average_true_range()
        avg_vol = volume.rolling(20).mean()

        buy = safe_float(close.iloc[-1])
        rsi_v = safe_float(rsi.iloc[-1])
        adx_v = safe_float(adx.iloc[-1])
        atr_v = safe_float(atr.iloc[-1])
        rvol = safe_float(volume.iloc[-1]) / safe_float(avg_vol.iloc[-1], 1.0)

        if buy <= 0 or atr_v <= 0:
            return None

        # Hard quality filters: avoid the weak-trend/overextended cases seen in V6.
        if rsi_v > 72:
            return None
        if adx_v < 18:
            return None
        if MARKET_CONDITION == "🔴 Bearish":
            return None

        score = 0
        reasons = []

        if buy > ema20.iloc[-1]:
            score += 10; reasons.append("✅ Price above EMA20")
        if ema20.iloc[-1] > ema50.iloc[-1]:
            score += 10; reasons.append("✅ EMA20 above EMA50")
        if ema50.iloc[-1] > ema200.iloc[-1]:
            score += 10; reasons.append("✅ EMA50 above EMA200")

        if 55 <= rsi_v <= 68:
            score += 15; reasons.append(f"✅ RSI preferred ({rsi_v:.2f})")
        elif 68 < rsi_v <= 72:
            score += 5; reasons.append(f"⚠ RSI extended ({rsi_v:.2f})")

        if macd_line.iloc[-1] > macd_signal.iloc[-1]:
            score += 10; reasons.append("✅ MACD bullish")

        if adx_v >= 30:
            score += 15; reasons.append(f"✅ Strong ADX ({adx_v:.2f})")
        elif adx_v >= 25:
            score += 10; reasons.append(f"✅ Good ADX ({adx_v:.2f})")
        else:
            score += 5; reasons.append(f"⚠ Moderate ADX ({adx_v:.2f})")

        if rvol >= 3:
            score += 15; reasons.append(f"✅ High RVOL ({rvol:.2f}x)")
        elif rvol >= 1.5:
            score += 10; reasons.append(f"✅ RVOL ({rvol:.2f}x)")

        try:
            weekly = close.resample("W").last()
            if len(weekly) >= 50:
                we20 = EMAIndicator(weekly, 20).ema_indicator()
                we50 = EMAIndicator(weekly, 50).ema_indicator()
                if weekly.iloc[-1] > we20.iloc[-1] > we50.iloc[-1]:
                    score += 10; reasons.append("✅ Weekly trend bullish")
        except Exception:
            pass

        prior20 = high.iloc[-21:-1].max()
        if buy > prior20 and rvol >= 1.5:
            score += 15; reasons.append("🚀 20-day breakout")

        if buy >= high.iloc[-201:-1].max():
            score += 5; reasons.append("🚀 200-day high")

        # Demand zone is confirmation, not a forced requirement.
        zone = identify_demand_zone(close, high, low)
        if zone:
            zl, zh = zone
            if buy >= zl and buy <= zh * 1.02:
                score += 5; reasons.append("🏦 Near demand zone")

        score = max(0, min(score, 100))
        if score < 80:
            return None

        if score >= 90:
            trend, confidence = "🟢 Super Bullish", "💎 Institutional"
        elif score >= 85:
            trend, confidence = "🟢 Strong Bullish", "🔥 Excellent"
        else:
            trend, confidence = "🟢 Bullish", "✅ High"

        # ATR risk with a 1.5x multiple.
        sl = round(buy - 1.5 * atr_v, 2)
        if sl <= 0 or sl >= buy:
            return None
        risk = round(buy - sl, 2)
        t1, t2, t3 = round(buy+risk,2), round(buy+2*risk,2), round(buy+3*risk,2)

        return {
            "symbol": symbol.replace(".NS", ""),
            "score": score,
            "trend": trend,
            "confidence": confidence,
            "market": MARKET_CONDITION,
            "reason": "\n".join(reasons),
            "buy": round(buy, 2),
            "sl": sl,
            "t1": t1,
            "t2": t2,
            "t3": t3,
            "rsi": round(rsi_v, 2),
            "rvol": round(rvol, 2),
            "adx": round(adx_v, 2),
            "atr": round(atr_v, 2)
        }
    except Exception as e:
        print(f"{symbol}: {e}")
        return None
