import os
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

message = """
📊 GTF PRO SCANNER

Scanner Status: ✅ Running

Market: NSE
Strategy: EMA + RSI + Volume

No trading setup found at this scan.

Next scan in 15 minutes.
"""

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)