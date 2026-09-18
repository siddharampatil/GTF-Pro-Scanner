import os
import json
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST).isoformat(timespec="seconds")


def load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def send(text):
    r = requests.post(
        URL,
        data={"chat_id": CHAT_ID, "text": text},
        timeout=25,
    )
    r.raise_for_status()


def current_price(symbol):
    df = yf.download(
        symbol,
        period="2d",
        interval="5m",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return None

    if hasattr(df["Close"], "columns"):
        close = df["Close"].iloc[:, 0]
    else:
        close = df["Close"]

    close = close.dropna()
    if close.empty:
        return None
    return round(float(close.iloc[-1]), 2)


signals = load(SIGNALS_FILE, [])
history = load(HISTORY_FILE, [])
updated = False

for signal in signals:
    status = signal.get("status")
    if status not in ("WAITING_ENTRY", "OPEN"):
        continue

    symbol = signal["symbol"]
    try:
        current = current_price(symbol)
        if current is None:
            continue

        buy = float(signal["buy"])
        sl = float(signal["sl"])
        t1 = float(signal["t1"])
        t2 = float(signal["t2"])
        t3 = float(signal["t3"])

        # Entry is confirmed only when price reaches the scanner buy level.
        if status == "WAITING_ENTRY":
            if current < buy:
                continue

            entry = current
            signal["status"] = "OPEN"
            signal["entry_alert"] = True
            signal["entry_price"] = entry
            signal["entry_time"] = now_ist()
            updated = True

            send(
                "🚀 BUY SIGNAL — V8\n\n"
                f"{symbol}\n\n"
                f"🎯 Entry : ₹{entry:.2f}\n"
                f"📌 Scanner Buy : ₹{buy:.2f}\n"
                f"🛑 SL : ₹{sl:.2f}\n"
                f"🎯 T1 : ₹{t1:.2f}\n"
                f"🎯 T2 : ₹{t2:.2f}\n"
                f"🎯 T3 : ₹{t3:.2f}"
            )

        # IMPORTANT: all P&L calculations use the actual confirmed entry.
        entry = float(signal.get("entry_price") or buy)

        # SL is checked before targets to avoid reporting an impossible
        # target hit and SL hit in the same polling cycle.
        if current <= sl:
            signal["status"] = "STOPPED"
            signal["result"] = "LOSS"
            signal["exit_price"] = sl
            signal["exit_time"] = now_ist()
            signal["pnl_points"] = round(sl - entry, 2)
            signal["pnl_pct"] = round((sl - entry) / entry * 100, 2)
            history.append(dict(signal))
            updated = True

            send(
                "🛑 STOP LOSS HIT — TRADE CLOSED\n\n"
                f"{symbol}\n\n"
                f"📌 Entry : ₹{entry:.2f}\n"
                f"📍 Current : ₹{current:.2f}\n"
                f"🛑 SL : ₹{sl:.2f}\n"
                f"📉 P&L : {signal['pnl_pct']:.2f}%"
            )
            continue

        # Targets are milestones. T1/T2 do NOT close the trade.
        if current >= t1 and not signal.get("t1_hit", False):
            signal["t1_hit"] = True
            signal["t1_time"] = now_ist()
            updated = True
            send(
                "🎯 TARGET 1 HIT\n\n"
                f"{symbol}\n\n"
                f"📌 Entry : ₹{entry:.2f}\n"
                f"📍 Current : ₹{current:.2f}\n"
                f"🎯 T1 : ₹{t1:.2f}\n"
                f"📈 Unrealised P&L vs entry : {(current-entry)/entry*100:.2f}%"
            )

        if current >= t2 and not signal.get("t2_hit", False):
            signal["t2_hit"] = True
            signal["t2_time"] = now_ist()
            updated = True
            send(
                "🎯 TARGET 2 HIT\n\n"
                f"{symbol}\n\n"
                f"📌 Entry : ₹{entry:.2f}\n"
                f"📍 Current : ₹{current:.2f}\n"
                f"🎯 T2 : ₹{t2:.2f}\n"
                f"📈 Unrealised P&L vs entry : {(current-entry)/entry*100:.2f}%"
            )

        if current >= t3 and not signal.get("t3_hit", False):
            signal["t3_hit"] = True
            signal["t3_time"] = now_ist()
            signal["status"] = "TARGET3"
            signal["result"] = "WIN"
            signal["exit_price"] = t3
            signal["exit_time"] = now_ist()
            signal["pnl_points"] = round(t3 - entry, 2)
            signal["pnl_pct"] = round((t3 - entry) / entry * 100, 2)
            history.append(dict(signal))
            updated = True

            send(
                "🏆 TARGET 3 HIT — TRADE CLOSED\n\n"
                f"{symbol}\n\n"
                f"📌 Entry : ₹{entry:.2f}\n"
                f"📍 Current : ₹{current:.2f}\n"
                f"🏁 Exit : ₹{t3:.2f}\n"
                f"📈 P&L : {signal['pnl_pct']:.2f}%"
            )

    except Exception as e:
        print(f"❌ Monitor error {symbol}: {e}")

if updated:
    save(SIGNALS_FILE, signals)
    save(HISTORY_FILE, history)

print("✅ V8 monitor completed")
