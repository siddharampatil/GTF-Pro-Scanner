import os
import requests

from strategy import scan_stock
from stock_list import get_stock_list

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

stocks = get_stock_list()
results = []

print(f"Scanning {len(stocks)} stocks...")

for stock in stocks:
    result = scan_stock(stock)

    # Only keep quality stocks
    if result and result["score"] >= 70:
        results.append(result)

# Sort by Score then Relative Volume
results = sorted(
    results,
    key=lambda x: (x["score"], x["rvol"]),
    reverse=True
)

top_results = results[:10]

if top_results:

    top_pick = top_results[0]

    message = (
        "🚀 GTF PRO SCANNER V3.0 🚀\n\n"
        f"🏆 TOP PICK : {top_pick['symbol']}\n"
        f"⭐ Score : {top_pick['score']}/125\n\n"
    )

    for s in top_results:

        message += (
            f"📈 {s['symbol']}\n"
            f"📊 Market : {s['market']}\n"
            f"{s['trend']}\n"
            f"{s['confidence']}\n"
            f"⭐ Score : {s['score']}/125\n\n"

            f"💰 Buy : ₹{s['buy']}\n"
            f"🛑 Stop Loss : ₹{s['sl']}\n"

            f"🎯 Target 1 : ₹{s['t1']}\n"
            f"🎯 Target 2 : ₹{s['t2']}\n"
            f"🎯 Target 3 : ₹{s['t3']}\n\n"

            f"📊 RSI : {s['rsi']}\n"
            f"📈 ADX : {s['adx']}\n"
            f"🚀 Relative Volume : {s['rvol']}x\n"
            f"📏 ATR : {s['atr']}\n\n"

            f"📌 Reasons:\n{s['reason']}\n"

            f"{'─'*35}\n\n"
        )

else:
    message = "❌ No quality stocks found today."

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print("Telegram Status:", response.status_code)
print("Telegram Response:", response.text)

print(message)
