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
            f"""📈 BUY SIGNAL

🏢 Stock: {result['symbol']}
💰 Entry: ₹{result['price']}
🎯 Target 1: ₹{result['target1']}
🎯 Target 2: ₹{result['target2']}
🛑 Stop Loss: ₹{result['sl']}
📊 RSI: {result['rsi']}
"""
        )

if results:
    message = "🔥 GTF PRO SCANNER 🔥\n\n" + "\n------------------------\n".join(results)
else:
    message = "📊 GTF PRO SCANNER\n\nNo stocks matched the strategy today."

requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print(message)