import json
import os
import requests
import yfinance as yf

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def send_message(text):

    response = requests.post(
        URL,
        data={
            "chat_id": CHAT_ID,
            "text": text
        }
    )

    print("Telegram Status:", response.status_code)
    print("Telegram Response:", response.text)


with open("signals.json", "r") as f:
    signals = json.load(f)

updated = False

print(f"Monitoring {len(signals)} signals...")

for signal in signals:

    if signal["status"] != "OPEN":
        continue

    try:

        df = yf.download(
            signal["symbol"],
            period="2d",
            interval="5m",
            progress=False,
            auto_adjust=True,
            threads=False
        )

        if df.empty:
            print(f"{signal['symbol']} : No Data")
            continue

        current = round(float(df["Close"].iloc[-1].item()), 2)

        print(
            f"{signal['symbol']} | "
            f"Current={current} | "
            f"Buy={signal['buy']} | "
            f"T1={signal['t1']} | "
            f"T2={signal['t2']} | "
            f"T3={signal['t3']} | "
            f"SL={signal['sl']}"
        )
        # ==============================
        # BUY ALERT
        # ==============================
        if not signal.get("entry_alert", False):

            if current >= signal["buy"]:

                send_message(
                    f"🚀 BUY SIGNAL\n\n"
                    f"📈 {signal['symbol']}\n\n"
                    f"💰 Buy : ₹{signal['buy']}\n"
                    f"📍 Current : ₹{current}\n\n"
                    f"🛑 Stop Loss : ₹{signal['sl']}\n"
                    f"🎯 Target 1 : ₹{signal['t1']}\n"
                    f"🎯 Target 2 : ₹{signal['t2']}\n"
                    f"🎯 Target 3 : ₹{signal['t3']}"
                )

                signal["entry_alert"] = True
                updated = True

        # ==============================
        # STOP LOSS
        # ==============================
        if current <= signal["sl"]:

            send_message(
                f"🛑 STOP LOSS HIT\n\n"
                f"📈 {signal['symbol']}\n\n"
                f"💰 Buy : ₹{signal['buy']}\n"
                f"📍 Current : ₹{current}\n"
                f"🛑 Stop Loss : ₹{signal['sl']}"
            )

            signal["status"] = "STOPLOSS"
            updated = True
            continue

        # ==============================
        # TARGET 1
        # ==============================
        if current >= signal["t1"] and signal["status"] == "OPEN":

            send_message(
                f"🎯 TARGET 1 HIT\n\n"
                f"📈 {signal['symbol']}\n\n"
                f"📍 Current : ₹{current}"
            )

            signal["status"] = "TARGET1"
            updated = True
            continue
        # ==============================
        # TARGET 2
        # ==============================
        if current >= signal["t2"] and signal["status"] == "TARGET1":

            send_message(
                f"🎯 TARGET 2 HIT\n\n"
                f"📈 {signal['symbol']}\n\n"
                f"📍 Current : ₹{current}"
            )

            signal["status"] = "TARGET2"
            updated = True
            continue

        # ==============================
        # TARGET 3
        # ==============================
       