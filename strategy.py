import yfinance as yf
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


def scan_stock(symbol):
    try:
        df = yf.download(
            symbol,
            period="2y",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        if len(df) < 200:
            return None

        close = df["Close"].squeeze()
        high = df["High"].squeeze()
        low = df["Low"].squeeze()
        volume = df["Volume"].squeeze()

        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()
        ema200 = EMAIndicator(close, window=200).ema_indicator()

        rsi = RSIIndicator(close, window=14).rsi()

        macd = MACD(close)
        macd_line = macd.macd()
        signal_line = macd.macd_signal()

        atr = AverageTrueRange(
            high,
            low,
            close,
            window=14
        ).average_true_range()

        avg_volume = volume.rolling(20).mean()

        score = 0

        if close.iloc[-1] > ema20.iloc[-1]:
            score += 15

        if ema20.iloc[-1] > ema50.iloc[-1]:
            score += 15

        if ema50.iloc[-1] > ema200.iloc[-1]:
            score += 20

        if 55 <= rsi.iloc[-1] <= 70:
            score += 15

        if volume.iloc[-1] > avg_volume.iloc[-1]:
            score += 15

        if macd_line.iloc[-1] > signal_line.iloc[-1]:
            score += 10

        if close.iloc[-1] >= high.iloc[-20:].max():
            score += 10

        buy = round(float(close.iloc[-1]), 2)

        atr_value = float(atr.iloc[-1])

        stop_loss = round(buy - (1.5 * atr_value), 2)

        risk = buy - stop_loss

        target1 = round(buy + risk, 2)
        target2 = round(buy + (2 * risk), 2)
        target3 = round(buy + (3 * risk), 2)

        return {
            "symbol": symbol.replace(".NS", ""),
            "score": score,
            "buy": buy,
            "sl": stop_loss,
            "t1": target1,
            "t2": target2,
            "t3": target3,
            "rsi": round(float(rsi.iloc[-1]), 2),
        }

    except Exception as e:
        print(f"{symbol}: {e}")
        return None