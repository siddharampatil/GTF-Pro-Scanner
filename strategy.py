import math
import time
import pandas as pd
import yfinance as yf

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

# ==========================================
# SAFE FLOAT
# ==========================================

def safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except:
        return default

# ==========================================
# DOWNLOAD DATA (OPTIMIZED)
# ==========================================

def download_stock(symbol, interval="1d", period="2y"):  # Increased to 2y for stable 200 EMA warmup
    for _ in range(3):
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

            # Handle MultiIndex columns safely by flattening them
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] for col in df.columns]

            df = df.dropna()

            if len(df) >= 200 or interval == "1wk":
                return df

        except Exception as e:
            print(f"{symbol}: {e}")

        time.sleep(1)

    return None

# ==========================================
# GLOBAL MARKET TREND (CACHED ONCE)
# ==========================================

def get_market_trend():
    """Download market index once to prevent nested loop API throttling."""
    try:
        nifty = download_stock("^NSEI")
        if nifty is None:
            return "🟢 Bullish"

        close = nifty["Close"]
        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()

        is_bullish = close.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1]
        return "🟢 Bullish" if is_bullish else "🔴 Bearish"
    except:
        return "🟢 Bullish"

# Initialize market condition globally once before running your loop
MARKET_CONDITION = get_market_trend()

# ==========================================
# MAIN SCANNER
# ==========================================

def scan_stock(symbol):
    try:
        df = download_stock(symbol)

        if df is None or len(df) < 200:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        # ==============================
        # INDICATORS
        # ==============================

        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()
        ema200 = EMAIndicator(close, window=200).ema_indicator()

        rsi = RSIIndicator(close, window=14).rsi()

        macd = MACD(close)
        macd_line = macd.macd()
        macd_signal = macd.macd_signal()

        adx = ADXIndicator(high=high, low=low, close=close, window=14).adx()
        atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

        avg_volume = volume.rolling(20).mean()

        # ==============================
        # LATEST VALUES
        # ==============================

        buy = safe_float(close.iloc[-1])
        if buy <= 0:
            return None

        rsi_value = round(safe_float(rsi.iloc[-1]), 2)
        adx_value = round(safe_float(adx.iloc[-1]), 2)
        atr_value = round(safe_float(atr.iloc[-1]), 2)

        if atr_value <= 0:
            atr_value = round(buy * 0.02, 2)

        if avg_volume.iloc[-1] > 0:
            rvol = round(safe_float(volume.iloc[-1]) / safe_float(avg_volume.iloc[-1]), 2)
        else:
            rvol = 1.0

        # ==============================
        # UPGRADED SCORE ENGINE
        # ==============================

        score = 0
        reasons = []

        # Price above EMA20
        if buy > ema20.iloc[-1]:
            score += 10
            reasons.append("✅ Price above EMA20")

        # EMA Trend
        if ema20.iloc[-1] > ema50.iloc[-1]:
            score += 10
            reasons.append("✅ EMA20 above EMA50")

        if ema50.iloc[-1] > ema200.iloc[-1]:
            score += 10
            reasons.append("✅ EMA50 above EMA200")

        # RSI
        if 55 <= rsi_value <= 68:
            score += 15
            reasons.append(f"✅ RSI Bullish ({rsi_value})")

        # Avoid buying overextended stocks
        if rsi_value > 75:
            score -= 15
            reasons.append("⚠ RSI Overbought")
            
        # MACD
        if macd_line.iloc[-1] > macd_signal.iloc[-1]:
            score += 10
            reasons.append("✅ MACD Bullish")

        # ADX
        if adx_value >= 30:
            score += 15
            reasons.append(f"✅ Strong Trend ({adx_value})")
        elif adx_value >= 25:
            score += 10
            reasons.append(f"✅ Good Trend ({adx_value})")

        # Relative Volume
        if rvol >= 2:
            score += 15
            reasons.append(f"✅ High Relative Volume ({rvol}x)")
        elif rvol >= 1.5:
            score += 10
            reasons.append(f"✅ Relative Volume ({rvol}x)")

        # Weekly Trend Confirmation
        try:
            weekly_close = close.resample('W').last()
            if len(weekly_close) >= 50:
                w_ema20 = EMAIndicator(weekly_close, window=20).ema_indicator()
                w_ema50 = EMAIndicator(weekly_close, window=50).ema_indicator()
                if weekly_close.iloc[-1] > w_ema20.iloc[-1] > w_ema50.iloc[-1]:
                    score += 15
                    reasons.append("✅ Weekly Trend Bullish")
        except:
            pass

        # 20-Day Breakout (Fixed Indentation)
        if buy > high.iloc[-21:-1].max() and rvol >= 1.5:
            score += 15
            reasons.append("✅ 20-Day Breakout")

        # 200-Day High Breakout (Fixed Lookback Slice & Indentation)
        if buy >= high.iloc[-201:-1].max():
            score += 10
            reasons.append("🚀 200-Day High Breakout")

        # Limit score to 100 before establishing category levels
        score = max(0, min(score, 100))

        # ==============================
        # TREND & CONFIDENCE
        # ==============================

        if score >= 85:
            trend = "🟢 Super Bullish"
            confidence = "💎 Institutional"
        elif score >= 75:
            trend = "🟢 Strong Bullish"
            confidence = "🔥 Excellent"
        elif score >= 60:
            trend = "🟢 Bullish"
            confidence = "✅ High"
        elif score >= 45:
            trend = "🟡 Moderate"
            confidence = "⚠ Medium"
        else:
            trend = "🔴 Weak"
            confidence = "❌ Low"

        # Minimum score filter threshold
        if score < 45:
            return None

        # ==============================
        # RISK MANAGEMENT
        # ==============================

        sl = round(buy - (1.5 * atr_value), 2)
        if sl >= buy:
            sl = round(buy * 0.98, 2)

        risk = round(buy - sl, 2)
        if risk <= 0:
            risk = round(buy * 0.02, 2)

        t1 = round(buy + risk, 2)
        t2 = round(buy + (2 * risk), 2)
        t3 = round(buy + (3 * risk), 2)

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
            "rsi": rsi_value,
            "rvol": rvol,
            "adx": adx_value,
            "atr": atr_value
        }

    except Exception as e:
        print(f"{symbol}: {e}")
        return None
