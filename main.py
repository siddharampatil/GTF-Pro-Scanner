import os
import requests

from strategy import scan_stock
from nse_stocks import STOCKS

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

results = []

for stock in STOCKS:
    result = scan_stock(stock)
    if result:
        results.append(
            f"✅ {result['symbol']}\n"
            f"Price: ₹{result['price']}\n"
            f"RSI: {result['rsi']}"
        )

if results:
    message = "📈 GTF Scanner Alerts\n\n" + "\n\n".join(results)
else:
    message = "📊 GTF Scanner\n\nNo stocks matched the strategy."

requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print(message)