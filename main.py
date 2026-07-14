import os
import requests

from strategy import scan_stock
from stock_list import get_stock_list

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

stocks = get_stock_list()

print(f"Total Stocks: {len(stocks)}")

results = []

for stock in stocks:
    print(f"Scanning {stock}...")

    result = scan_stock(stock)

    print(f"Result: {result}")

    if result:
        results.append(result)

results = sorted(results, key=lambda x: x["score"], reverse=True)

print(f"Matched Stocks: {len(results)}")

if results:
    message = "DEBUG SCANNER\n\n"

    for s in results:
        message += (
            f"{s['symbol']} | Score: {s['score']} | Buy: ₹{s['buy']}\n"
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