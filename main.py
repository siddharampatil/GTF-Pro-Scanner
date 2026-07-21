import os
import json
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

    if (
        result is not None
        and result["score"] >= 85
        and result["rvol"] >= 1.5
    ):
        results.append(result)

# Highest score first
results = sorted(
    results,
    key=lambda x: (x["score"], x["rvol"]),
    reverse=True
)

top_results = results[:10]
signals = []

for s in top_results:
    signals.append({
        "symbol": s["symbol"] + ".NS",
        "buy": s["buy"],
        "sl": s["sl"],
        "t1": s["t1"],
        "t2": s["t2"],
        "t3": s["t3"],
        "status": "OPEN"
    })

with open("signals.json", "w") as f:
    json.dump(signals, f, indent=4)
qualified = len(results)
scanned = len(stocks)

if top_results:

    top = top_results[0]

    message = (
        "🚀 GTF PRO SCANNER V6 🚀\n\n"
        f"📊 Stocks Scanned : {scanned}\n"
        f"✅ Qualified : {qualified}\n\n"

        f"🏆 TOP PICK : {top['symbol']}\n"
        f"⭐ Score : {top['score']}/100\n\n"

        f"💰 Buy : ₹{top['buy']}\n"
        f"🛑 Stop Loss : ₹{top['sl']}\n"
        f"🎯 T1 : ₹{top['t1']}\n"
        f"🎯 T2 : ₹{top['t2']}\n"
        f"🎯 T3 : ₹{top['t3']}\n\n"

        f"📊 RSI : {top['rsi']}\n"
        f"📈 ADX : {top['adx']}\n"
        f"🚀 RVOL : {top['rvol']}x\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📈 TOP 10 STOCKS\n\n"
    )

    rank = 1

    for s in top_results:

        message += (
            f"{rank}. {s['symbol']}\n"
            f"⭐ {s['score']}/100\n"
            f"💰 ₹{s['buy']}\n\n"
        )

        rank += 1

else:

    message = (
        "🚀 GTF PRO SCANNER V6\n\n"
        "❌ No quality stocks found today."
    )

MAX_LEN = 4000

for i in range(0, len(message), MAX_LEN):

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message[i:i+MAX_LEN]
        }
    )

    print("Telegram Status:", response.status_code)
    print(response.text)
