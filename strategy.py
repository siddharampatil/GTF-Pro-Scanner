import yfinance as yf
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator


def market_is_bullish():
    try:
        nifty = yf.download(
            "^NSEI",
            period="6mo",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        close = nifty["Close"].squeeze()

        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()

        return close.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1]

    except:
        return True


def scan_stock(symbol):
    try:

        market_bullish = market_is_bullish()

        df = yf.download(
            symbol,
            period="1y",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        if len(df) < 200:
            return None

        close = df["Close"].squeeze()
        volume = df["Volume"].squeeze()

        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()
        ema200 = EMAIndicator(close, window=200).ema_indicator()

        rsi = RSIIndicator(close, window=14).rsi()

        macd = MACD(close)
        macd_line = macd.macd()
        signal_line = macd.macd_signal()

        avg_volume = volume.rolling(20).mean()

        score = 0
        reasons = []

        if close.iloc[-1] > ema20.iloc[-1]:
            score += 20
            reasons.append("✅ Price above EMA20")

        if ema20.iloc[-1] > ema50.iloc[-1]:
            score += 20
            reasons.append("✅ EMA20 above EMA50")

        if ema50.iloc[-1] > ema200.iloc[-1]:
            score += 20
            reasons.append("✅ EMA50 above EMA200")

        if 50 <= rsi.iloc[-1] <= 70:
            score += 20
            reasons.append(f"✅ RSI Bullish ({round(float(rsi.iloc[-1]),2)})")

        if volume.iloc[-1] > avg_volume.iloc[-1]:
            score += 10
            reasons.append("✅ Volume above 20-Day Average")

        if macd_line.iloc[-1] > signal_line.iloc[-1]:
            score += 10
            reasons.append("✅ MACD Bullish Crossover")

        if score >= 90:
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

        buy = round(float(close.iloc[-1]), 2)

        last5_low = round(float(close.iloc[-5:].min()), 2)
        percent_sl = round(buy * 0.98, 2)

        sl = min(last5_low, percent_sl)

        if sl >= buy:
            sl = percent_sl

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
            "rsi": round(float(rsi.iloc[-1]), 2),
        }

    except Exception as e:
        print(f"{symbol}: {e}")
        return None