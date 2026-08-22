import json
import os
from datetime import datetime, timezone, timedelta
import requests
import yfinance as yf

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"
IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST).isoformat(timespec="seconds")

def send_message(text):
    response = requests.post(
        URL,
        data={"chat_id": CHAT_ID, "text": text},
        timeout=20
    )
    print(response.text)

def load(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)
    import os as _os
    _os.replace(tmp, path)

signals = load(SIGNALS_FILE, [])
history = load(HISTORY_FILE, [])
updated = False

for signal in signals:
    if signal.get("status") not in ("WAITING_ENTRY", "OPEN"):
        continue

    try:
        df = yf.download(
            signal["symbol"],
            period="2d",
            interval="5m",
            auto_adjust=True,
            progress=False,
            threads=False
        )
        if df is None or df.empty:
            continue

        if hasattr(df["Close"], "columns"):
            close_series = df["Close"].iloc[:, 0]
        else:
            close_series = df["Close"]

        current = round(float(close_series.dropna().iloc[-1]), 2)
        buy = float(signal["buy"])

        # ------------------------------------------
        # ENTRY: SL/TARGETS are NOT checked before entry.
        # This fixes false SL hits on signals that never triggered.
        # ------------------------------------------
        if signal.get("status") == "WAITING_ENTRY":
            if current >= buy:
                signal["status"] = "OPEN"
                signal["entry_alert"] = True
                signal["entry_price"] = buy
                signal["entry_time"] = now_ist()
                updated = True

                send_message(
                    f"🚀 BUY SIGNAL\n\n"
                    f"{signal['symbol']}\n\n"
                    f"Buy Price : ₹{buy:.2f}\n"
                    f"Current : ₹{current:.2f}\n\n"
                    f"🎯 T1 : ₹{signal['t1']:.2f}\n"
                    f"🎯 T2 : ₹{signal['t2']:.2f}\n"
                    f"🎯 T3 : ₹{signal['t3']:.2f}\n"
                    f"🛑 SL : ₹{signal['sl']:.2f}"
                )
            else:
                continue

        # ------------------------------------------
        # TARGET MILESTONES: don't close the trade at T1.
        # Track T1/T2/T3 independently.
        # ------------------------------------------
        if current >= signal["t1"] and not signal.get("t1_hit", False):
            signal["t1_hit"] = True
            signal["t1_time"] = now_ist()
            updated = True
            send_message(
                f"🎯 TARGET 1 HIT\n\n{signal['symbol']}\n\n"
                f"Current : ₹{current:.2f}\n"
                f"T1 : ₹{signal['t1']:.2f}"
            )

        if current >= signal["t2"] and not signal.get("t2_hit", False):
            signal["t2_hit"] = True
            signal["t2_time"] = now_ist()
            updated = True
            send_message(
                f"🎯 TARGET 2 HIT\n\n{signal['symbol']}\n\n"
                f"Current : ₹{current:.2f}\n"
                f"T2 : ₹{signal['t2']:.2f}"
            )

        if current >= signal["t3"] and not signal.get("t3_hit", False):
            signal["t3_hit"] = True
            signal["t3_time"] = now_ist()
            signal["status"] = "TARGET3"
            signal["result"] = "WIN"
            signal["exit_price"] = signal["t3"]
            signal["exit_time"] = now_ist()
            signal["pnl_pct"] = round(
                (float(signal["t3"]) - buy) / buy * 100, 2
            )
            history.append(dict(signal))
            updated = True
            send_message(
                f"🏆 TARGET 3 HIT — TRADE CLOSED\n\n"
                f"{signal['symbol']}\n\nCurrent : ₹{current:.2f}\n"
                f"Exit : ₹{signal['t3']:.2f}\n"
                f"📈 P&L : {signal['pnl_pct']}%"
            )
            continue

        # ------------------------------------------
        # STOP LOSS
        # If T1 was already hit and price later falls to SL,
        # classify by actual final exit, but report T1 separately.
        # ------------------------------------------
        if current <= float(signal["sl"]):
            signal["status"] = "STOPLOSS"
            signal["result"] = "LOSS"
            signal["exit_price"] = signal["sl"]
            signal["exit_time"] = now_ist()
            signal["pnl_pct"] = round(
                (float(signal["sl"]) - buy) / buy * 100, 2
            )
            history.append(dict(signal))
            updated = True

            send_message(
                f"🛑 STOP LOSS HIT — TRADE CLOSED\n\n"
                f"{signal['symbol']}\n\n"
                f"Buy : ₹{buy:.2f}\n"
                f"Current : ₹{current:.2f}\n"
                f"SL : ₹{signal['sl']:.2f}\n"
                f"📉 P&L : {signal['pnl_pct']}%\n"
                f"🎯 T1 Hit Earlier : {'YES' if signal.get('t1_hit') else 'NO'}"
            )
            continue

    except Exception as e:
        print(signal.get("symbol"), e)

if updated:
    save(SIGNALS_FILE, signals)
    save(HISTORY_FILE, history)

print("V7 monitoring completed.")
