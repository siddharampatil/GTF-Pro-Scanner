import os
import requests
import yfinance as yf
import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

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