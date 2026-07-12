import os
import requests
import yfinance as yf
import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

stocks = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "LT.NS",
    "BHARTIARTL.NS",
    "ITC.NS",
    "AXISBANK.NS"
]

results = []

for stock in stocks:
    try:
        df = yf.download(stock, period="6mo", interval="1d", progress=False)

        if len(df) < 50:
            continue

        close = df["Close"]

        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()
        rsi = RSIIndicator(close, window=14).rsi()

        last_close = close.iloc[-1]
        last_ema20 = ema20.iloc[-1]
        last_ema50 = ema50.iloc[-1]
        last_rsi = rsi.iloc[-1]

        if last_close > last_ema20 and last_ema20 > last_ema50 and 55 < last_rsi < 70:
            results.append(
                f"✅ {stock.replace('.NS','')}\n"
                f"Price: ₹{last_close:.2f}\n"
                f"RSI: {last_rsi:.1f}"
            )

    except Exception as e:
        print(f"Error scanning {stock}: {e}")
if results:
    message = "📈 GTF Scanner Alerts\n\n" + "\n\n".join(results)
else:
    message = "📊 GTF Scanner\n\nNo stocks matched the strategy today."

requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print(message)