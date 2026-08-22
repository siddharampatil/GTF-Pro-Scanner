import os
import json
import requests
from datetime import datetime, timezone, timedelta

from strategy import scan_stock
from stock_list import get_stock_list

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"

IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST).isoformat(timespec="seconds")

def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)

def send_message(text):
    for start in range(0, len(text), 3900):
        response = requests.post(
            URL,
            data={"chat_id": CHAT_ID, "text": text[start:start+3900]},
            timeout=20
        )
        print("Telegram:", response.status_code, response.text[:200])

stocks = get_stock_list()
results = []

print(f"Scanning {len(stocks)} stocks...")

for i, stock in enumerate(stocks, start=1):
    print(f"[{i}/{len(stocks)}] Scanning {stock}")
    try:
        result = scan_stock(stock)
        # V7: high-quality candidates only; strategy itself applies its filters.
        if result is not None and result["score"] >= 80:
            results.append(result)
    except Exception as e:
        print(f"❌ Error scanning {stock}: {e}")

results.sort(key=lambda x: (x["score"], x["adx"], x["rvol"]), reverse=True)
top_results = results[:10]

signals = load_json(SIGNALS_FILE, [])
history = load_json(HISTORY_FILE, [])

# Keep only currently OPEN signals in the live book.
# Do not overwrite an existing OPEN signal for the same symbol every morning.
open_by_symbol = {s["symbol"]: s for s in signals if s.get("status") == "OPEN"}

new_signals = []
for s in top_results:
    symbol = s["symbol"] + ".NS"

    if symbol in open_by_symbol:
        new_signals.append(open_by_symbol[symbol])
        continue

    signal = {
        "signal_id": f"{symbol}_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}",
        "symbol": symbol,
        "created_at": now_ist(),
        "buy": s["buy"],
        "sl": s["sl"],
        "t1": s["t1"],
        "t2": s["t2"],
        "t3": s["t3"],
        "score": s["score"],
        "rsi": s["rsi"],
        "adx": s["adx"],
        "rvol": s["rvol"],
        "atr": s["atr"],
        "status": "WAITING_ENTRY",
        "entry_alert": False,
        "entry_price": None,
        "entry_time": None,
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "exit_price": None,
        "exit_time": None,
        "result": None,
        "pnl_pct": None
    }
    new_signals.append(signal)

# Carry forward existing OPEN/WAITING signals not selected today.
# This prevents the scanner from deleting active trades.
existing_active = [
    s for s in signals
    if s.get("status") in ("OPEN", "WAITING_ENTRY")
    and s.get("symbol") not in {x["symbol"] for x in new_signals}
]
new_signals.extend(existing_active)

save_json(SIGNALS_FILE, new_signals)

scanned = len(stocks)
qualified = len(results)

if top_results:
    top = top_results[0]
    message = (
        "🚀 GTF PRO SCANNER V7 🚀\n\n"
        f"📊 Stocks Scanned : {scanned}\n"
        f"✅ Qualified : {qualified}\n\n"
        f"🏆 TOP PICK : {top['symbol']}\n"
        f"⭐ Score : {top['score']}/100\n"
        f"📌 Confidence : {top['confidence']}\n\n"
        f"💰 Buy : ₹{top['buy']}\n"
        f"🛑 Stop Loss : ₹{top['sl']}\n"
        f"🎯 T1 : ₹{top['t1']}\n"
        f"🎯 T2 : ₹{top['t2']}\n"
        f"🎯 T3 : ₹{top['t3']}\n\n"
        f"📊 RSI : {top['rsi']}\n"
        f"📈 ADX : {top['adx']}\n"
        f"🚀 RVOL : {top['rvol']}x\n"
        f"🌐 Market : {top['market']}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📈 TOP 10 STOCKS\n\n"
    )
    for rank, s in enumerate(top_results, 1):
        message += (
            f"{rank}. {s['symbol']}\n"
            f"⭐ {s['score']}/100 | ADX {s['adx']} | RVOL {s['rvol']}x\n"
            f"💰 ₹{s['buy']}\n\n"
        )
else:
    message = (
        "🚀 GTF PRO SCANNER V7 🚀\n\n"
        f"📊 Stocks Scanned : {scanned}\n"
        "❌ No quality setups found today."
    )

send_message(message)
