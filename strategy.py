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
            print(f"{symbol}: Not enough data")
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

        if 55 <= rsi.iloc[-1] <= 70:
            score += 20

        if volume.iloc[-1] > avg_volume.iloc[-1]:
            score += 15

        if close.iloc[-1] >= close.iloc[-20:].max():
            score += 15

        return {
            "symbol": symbol.replace(".NS", ""),
            "price": round(float(close.iloc[-1]), 2),
            "rsi": round(float(rsi.iloc[-1]), 2),
            "score": score,
        }

    except Exception as e:
        print(f"Error in {symbol}: {e}")
        return None