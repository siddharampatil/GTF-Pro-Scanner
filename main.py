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
    if result:
        results.append(result)

# Sort by highest score
results = sorted(results, key=lambda x: x["score"], reverse=True)

# Keep only Top 10
top_results = results[:10]

if top_results:
    message = "🔥 GTF PRO SCANNER - TOP 10 STOCKS 🔥\n\n"

    for stock in top_results:
        message += (
            f"📈 {stock['symbol']}\n"
            f"💰 Price: ₹{stock['price']}\n"
            f"📊 RSI: {stock['rsi']}\n"
            f"⭐ Score: {stock['score']}/100\n\n"
        )
else:
    message = "No stocks found."

requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print(message)