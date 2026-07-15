import math
import yfinance as yf

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


# ==========================================
# MARKET TREND FILTER
# ==========================================

def market_is_bullish():
    try:
        nifty = yf.download(
            "^NSEI",
            period="6mo",
            interval="1d",
            auto_adjust=True,
            progress=False
        )

        if nifty.empty:
            return True

        close = nifty["Close"].squeeze()

        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()

        return (
            close.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1]
        )

    except Exception:
        return True


# ==========================================
# SAFE FLOAT
# ==========================================

def safe_float(value, default=0.0):
    try:
        value = float(value)

        if math.isnan(value):
            return default

        return value

    except Exception:
        return default


# ==========================================
# MAIN SCANNER
# ==========================================

def scan_stock(symbol):

     try:
    market_bullish = market_is_bullish()
except:
    market_bullish = True

        df = yf.download(
    symbol,
    period="6mo",
    interval="1d",
    auto_adjust=True,
    progress=False,
    threads=False,
    timeout=30
)

        if df.empty or len(df) < 60:
            return None

        close = df["Close"].squeeze()
        high = df["High"].squeeze()
        low = df["Low"].squeeze()
        volume = df["Volume"].squeeze()

        # EMA
        ema20 = EMAIndicator(
            close,
            window=20
        ).ema_indicator().bfill()

        ema50 = EMAIndicator(
            close,
            window=50
        ).ema_indicator().bfill()

        ema200 = EMAIndicator(
            close,
            window=200
        ).ema_indicator().bfill()

        # RSI
        rsi = RSIIndicator(
            close,
            window=14
        ).rsi().fillna(50)

        # MACD
        macd = MACD(close)

        macd_line = macd.macd().fillna(0)
        signal_line = macd.macd_signal().fillna(0)
        # ADX
        adx = ADXIndicator(
            high=high,
            low=low,
            close=close,
            window=14
        ).adx().fillna(0)

        # ATR
        atr = AverageTrueRange(
            high=high,
            low=low,
            close=close,
            window=14
        ).average_true_range().fillna(0)

        # Relative Volume
        avg_volume = volume.rolling(20).mean()

        if avg_volume.iloc[-1] > 0:
            rvol = round(
                safe_float(volume.iloc[-1]) /
                safe_float(avg_volume.iloc[-1]),
                2
            )
        else:
            rvol = 1.0

        buy = round(
            safe_float(close.iloc[-1]),
            2
        )

        if buy <= 0:
            return None

        atr_value = safe_float(atr.iloc[-1])

        if atr_value <= 0:
            atr_value = buy * 0.02

        adx_value = round(
            safe_float(adx.iloc[-1]),
            1
        )

        rsi_value = round(
            safe_float(rsi.iloc[-1]),
            2
        )

        score = 0
        reasons = []

        # ============================
        # EMA Trend
        # ============================

        if buy > ema20.iloc[-1]:
            score += 20
            reasons.append("✅ Price above EMA20")

        if ema20.iloc[-1] > ema50.iloc[-1]:
            score += 20
            reasons.append("✅ EMA20 above EMA50")

        if ema50.iloc[-1] > ema200.iloc[-1]:
            score += 20
            reasons.append("✅ EMA50 above EMA200")

        # ============================
        # RSI
        # ============================

        if 55 <= rsi_value <= 70:
            score += 20
            reasons.append(
                f"✅ RSI Bullish ({rsi_value})"
            )

        # ============================
        # Relative Volume
        # ============================

        if rvol >= 2:
            score += 15
            reasons.append(
                f"✅ High Relative Volume ({rvol}x)"
            )

        elif rvol >= 1.5:
            score += 10
            reasons.append(
                f"✅ Relative Volume ({rvol}x)"
            )

        elif rvol >= 1.2:
            score += 5
            reasons.append(
                f"✅ Relative Volume ({rvol}x)"
            )

        # ============================
        # MACD
        # ============================

        if macd_line.iloc[-1] > signal_line.iloc[-1]:
            score += 10
            reasons.append(
                "✅ MACD Bullish"
            )

        # ============================
        # Breakout
        # ============================

        breakout = buy > high.iloc[-21:-1].max()

        if breakout:
            score += 10
            reasons.append(
                "✅ 20-Day Breakout"
            )

        # ============================
        # ADX
        # ============================

        if adx_value >= 30:
            score += 15
            reasons.append(
                f"✅ Strong Trend ({adx_value})"
            )

        elif adx_value >= 25:
            score += 10
            reasons.append(
                f"✅ Good Trend ({adx_value})"
            )
        # ============================
        # Rating
        # ============================

        if score >= 120:
            trend = "🟢 Super Bullish"
            confidence = "💎 Institutional"

        elif score >= 100:
            trend = "🟢 Strong Bullish"
            confidence = "🔥 Excellent"

        elif score >= 90:
            trend = "🟢 Strong Bullish"
            confidence = "🔥 Very High"

        elif score >= 80:
            trend = "🟢 Bullish"
            confidence = "✅ High"

        elif score >= 60:
            trend = "🟡 Moderate"
            confidence = "⚠ Medium"

        else:
            trend = "🔴 Weak"
            confidence = "❌ Low"

        # Filter weak setups
        if score < 40:
            return None

        # ============================
        # Risk Management
        # ============================

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
            "market": "🟢 Bullish" if market_bullish else "🔴 Bearish",
            "reason": "\n".join(reasons),
            "buy": buy,
            "sl": sl,
            "t1": t1,
            "t2": t2,
            "t3": t3,
            "rsi": rsi_value,
            "rvol": rvol,
            "adx": adx_value,
            "atr": round(atr_value, 2)
        }

    except Exception as e:
        print(f"{symbol}: {e}")
        return None