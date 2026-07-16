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

    if result is not None:
        results.append(result)

# Highest score first
results = sorted(
    results,
    key=lambda x: (x["score"], x["rvol"]),
    reverse=True
)

top_results = results[:10]

if top_results:

    top_pick = top_results[0]

    message = (
        "🚀 GTF PRO SCANNER V5 🚀\n\n"
        f"🏆 TOP PICK : {top_pick['symbol']}\n"
        f"⭐ Score : {top_pick['score']}/130\n\n"
    )

    for s in top_results:

        message += (
            f"📈 {s['symbol']}\n"
            f"📊 Market : {s['market']}\n"
            f"{s['trend']}\n"
            f"{s['confidence']}\n"
            f"⭐ Score : {s['score']}/130\n\n"

            f"💰 Buy : ₹{s['buy']}\n"
            f"🛑 SL : ₹{s['sl']}\n"

            f"🎯 T1 : ₹{s['t1']}\n"
            f"🎯 T2 : ₹{s['t2']}\n"
            f"🎯 T3 : ₹{s['t3']}\n\n"

            f"📊 RSI : {s['rsi']}\n"
            f"📈 ADX : {s['adx']}\n"
            f"🚀 RVOL : {s['rvol']}x\n"
            f"📏 ATR : {s['atr']}\n\n"

            f"📌 Reasons:\n{s['reason']}\n"
            f"{'─'*35}\n