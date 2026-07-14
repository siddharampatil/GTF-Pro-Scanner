import yfinance as yf
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

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
        high = df["High"].squeeze()
        low = df["Low"].squeeze()
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

        if close.iloc[-1] >= high.iloc[-20:].max():
            score += 15

        buy = round(float(close.iloc[-1]), 2)
        sl = round(float(low.iloc[-5:].min()), 2)
        target1 = round(buy * 1.03, 2)
        target2 = round(buy * 1.05, 2)
        target3 = round(buy * 1.08, 2)

        return {
            "symbol": symbol.replace(".NS", ""),
            "price": buy,
            "rsi": round(float(rsi.iloc[-1]), 2),
            "score": score,
            "buy": buy,
            "sl": sl,
            "t1": target1,
            "t2": target2,
            "t3": target3,
        }

    except Exception:
        return None