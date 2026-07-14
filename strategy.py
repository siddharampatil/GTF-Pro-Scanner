import yfinance as yf
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

def scan_stock(symbol):
    try:
        df = yf.download(
            symbol,
            period="6mo",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        if len(df) < 60:
            return None

        close = df["Close"].squeeze()
        volume = df["Volume"].squeeze()

        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()
        rsi = RSIIndicator(close, window=14).rsi()

        avg_volume = volume.rolling(20).mean()

        score = 0

        if close.iloc[-1] > ema20.iloc[-1]:
            score += 25

        if ema20.iloc[-1] > ema50.iloc[-1]:
            score += 25

        if 50 <= rsi.iloc[-1] <= 70:
            score += 25

        if volume.iloc[-1] > avg_volume.iloc[-1]:
            score += 25

        return {
            "symbol": symbol.replace(".NS", ""),
            "score": score,
            "buy": round(float(close.iloc[-1]), 2),
            "sl": round(float(close.iloc[-5:].min()), 2),
            "t1": round(float(close.iloc[-1]) * 1.03, 2),
            "t2": round(float(close.iloc[-1]) * 1.05, 2),
            "t3": round(float(close.iloc[-1]) * 1.08, 2),
            "rsi": round(float(rsi.iloc[-1]), 2),
        }

    except Exception as e:
        print(f"{symbol}: {e}")
        return None