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
MIN_SCORE = 85
MIN_RVOL = 1.5
TOP_N = 10


def now_ist():
    return datetime.now(IST).isoformat(timespec="seconds")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def send_message(text):
    for start in range(0, len(text), 3900):
        chunk = text[start:start + 3900]
        r = requests.post(
            URL,
            data={"chat_id": CHAT_ID, "text": chunk},
            timeout=25,
        )
        r.raise_for_status()


def f2(x):
    return f"{float(x):.2f}"


stocks = get_stock_list()
results = []

print(f"🚀 GTF PRO V8 scanning {len(stocks)} stocks")

for i, stock in enumerate(stocks, 1):
    try:
        result = scan_stock(stock)
        if result and result.get("score", 0) >= MIN_SCORE and result.get("rvol", 0) >= MIN_RVOL:
            results.append(result)
    except Exception as e:
        print(f"❌ {stock}: {e}")

results.sort(
    key=lambda x: (
        x.get("score", 0),
        x.get("adx", 0),
        x.get("rvol", 0),
    ),
    reverse=True,
)
top_results = results[:TOP_N]

signals = load_json(SIGNALS_FILE, [])
history = load_json(HISTORY_FILE, [])

# Preserve active signals. A new scan must never erase an existing trade.
active = {
    s.get("symbol"): s
    for s in signals
    if s.get("status") in ("WAITING_ENTRY", "OPEN")
}

new_signals = []
selected_symbols = set()

for s in top_results:
    symbol = s["symbol"].replace(".NS", "") + ".NS"
    selected_symbols.add(symbol)

    if symbol in active:
        new_signals.append(active[symbol])
        continue

    new_signals.append({
        "signal_id": f"{symbol}_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}",
        "symbol": symbol,
        "created_at": now_ist(),
        "buy": round(float(s["buy"]), 2),
        "sl": round(float(s["sl"]), 2),
        "t1": round(float(s["t1"]), 2),
        "t2": round(float(s["t2"]), 2),
        "t3": round(float(s["t3"]), 2),
        "score": int(s.get("score", 0)),
        "rsi": round(float(s.get("rsi", 0)), 2),
        "adx": round(float(s.get("adx", 0)), 2),
        "rvol": round(float(s.get("rvol", 0)), 2),
        "atr": round(float(s.get("atr", 0)), 2),
        "status": "WAITING_ENTRY",
        "entry_alert": False,
        "entry_price": None,
        "entry_time": None,
        "t1_hit": False,
        "t1_time": None,
        "t2_hit": False,
        "t2_time": None,
        "t3_hit": False,
        "t3_time": None,
        "exit_price": None,
        "exit_time": None,
        "result": None,
        "pnl_pct": None,
        "pnl_points": None,
    })

# Keep active signals even if they disappear from today's top 10.
for s in signals:
    if s.get("status") in ("WAITING_ENTRY", "OPEN") and s.get("symbol") not in selected_symbols:
        new_signals.append(s)

save_json(SIGNALS_FILE, new_signals)

scanned = len(stocks)
qualified = len(results)

if top_results:
    top = top_results[0]
    message = (
        "🚀 GTF PRO SCANNER V8 🚀\n\n"
        f"📅 {datetime.now(IST).strftime('%d-%m-%Y %H:%M IST')}\n"
        f"📊 Stocks Scanned : {scanned}\n"
        f"✅ Qualified : {qualified}\n\n"
        f"🏆 TOP PICK : {top['symbol']}\n"
        f"⭐ Score : {top['score']}/100\n"
        f"📌 Confidence : {top.get('confidence', 'N/A')}\n\n"
        f"💰 Buy : ₹{f2(top['buy'])}\n"
        f"🛑 Stop Loss : ₹{f2(top['sl'])}\n"
        f"🎯 T1 : ₹{f2(top['t1'])}\n"
        f"🎯 T2 : ₹{f2(top['t2'])}\n"
        f"🎯 T3 : ₹{f2(top['t3'])}\n\n"
        f"📊 RSI : {f2(top.get('rsi', 0))}\n"
        f"📈 ADX : {f2(top.get('adx', 0))}\n"
        f"🚀 RVOL : {f2(top.get('rvol', 0))}x\n"
        f"🌐 Market : {top.get('market', 'N/A')}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📈 TOP 10 STOCKS\n\n"
    )
    for rank, s in enumerate(top_results, 1):
        message += (
            f"{rank}. {s['symbol']} | ⭐ {s['score']}/100\n"
            f"💰 Buy ₹{f2(s['buy'])} | SL ₹{f2(s['sl'])}\n"
            f"🎯 T1 ₹{f2(s['t1'])} | ADX {f2(s.get('adx', 0))} | RVOL {f2(s.get('rvol', 0))}x\n\n"
        )
else:
    message = (
        "🚀 GTF PRO SCANNER V8 🚀\n\n"
        f"📅 {datetime.now(IST).strftime('%d-%m-%Y %H:%M IST')}\n"
        f"📊 Stocks Scanned : {scanned}\n"
        "❌ No quality setups found today.\n"
        "ℹ️ Existing active signals were preserved."
    )

send_message(message)
print("✅ V8 scanner message sent")
