import os
import requests

from strategy import scan_stock
from stock_list import get_stock_list

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

stocks = get_stock_list()

results = []

for stock in stocks:
    result = scan_stock(stock)

    # Only include stocks with Score 50 or higher
    if result and result["score"] >= 50:
        results.append(result)

# Sort by highest score
results = sorted(results, key=lambda x: x["score"], reverse=True)

# Show only Top 10
top_results = results[:10]

if top_results:
    message = "🔥 GTF PRO SCANNER - TOP STOCKS 🔥\n\n"

    for s in top_results:
        message += (
            f"📈 {s['symbol']}\n"
            f"⭐ Score: {s['score']}/100\n"
            f"💰 Buy: ₹{s['buy']}\n"
            f"🛑 Stop Loss: ₹{s['sl']}\n"
            f"🎯 Target 1: ₹{s['t1']}\n"
            f"🎯 Target 2: ₹{s['t2']}\n"
            f"🎯 Target 3: ₹{s['t3']}\n"
            f"📊 RSI: {s['rsi']}\n\n"
        )
else:
    message = "❌ No High Confidence Stocks Found Today."

requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print(message)