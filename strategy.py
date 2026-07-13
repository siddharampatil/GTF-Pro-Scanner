import yfinance as yf
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

def scan_stock(symbol):
    try:
        df = yf.download(symbol, period="6mo", interval="1d", progress=False)

        if len(df) < 50:
            return None

        close = df["Close"]
        high = df["High"]
        volume = df["Volume"]

        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()
        rsi = RSIIndicator(close, window=14).rsi()
        avg_volume = volume.rolling(20).mean()

        breakout = close.iloc[-1] > high.iloc[-20:].max()

        if (
            close.iloc[-1] > ema20.iloc[-1]
            and ema20.iloc[-1] > ema50.iloc[-1]
            and 55 <= rsi.iloc[-1] <= 70
            and volume.iloc[-1] > avg_volume.iloc[-1] * 1.5
            and breakout
        ):
            entry = round(float(close.iloc[-1]), 2)
            sl = round(entry * 0.97, 2)
            target1 = round(entry * 1.03, 2)
            target2 = round(entry * 1.06, 2)

            return {
                "symbol": symbol.replace(".NS", ""),
                "price": entry,
                "rsi": round(float(rsi.iloc[-1]), 2),
                "sl": sl,
                "target1": target1,
                "target2": target2,
            }

    except Exception as e:
        print(f"{symbol}: {e}")

    return None