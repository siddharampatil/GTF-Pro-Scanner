import json
import os
import requests
import yfinance as yf

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

URL = f"https://telegram.org{BOT_TOKEN}/sendMessage"


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

for signal in signals:

    if signal["status"] != "OPEN":
        continue

    try:

        df = yf.download(
            signal["symbol"],
            period="2d",
            interval="5m",
            progress=False,
            auto_adjust=True
        )

        if df.empty:
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

        # BUY ALERT
        if not signal.get("entry_alert", False):

            if current >= signal["buy"]:

                send_message(
                    f"🚀 BUY SIGNAL\n\n"
                    f"{signal['symbol']}\n\n"
                    f"Buy Price : ₹{signal['buy']}\n"
                    f"Current : ₹{current}\n\n"
                    f"🎯 T1 : ₹{signal['t1']}\n"
                    f"🎯 T2 : ₹{signal['t2']}\n"
                    f"🎯 T3 : ₹{signal['t3']}\n"
                    f"🛑 SL : ₹{signal['sl']}"
                )

                signal["entry_alert"] = True
                updated = True

        # Stop Loss
        if current <= signal["sl"]:

            send_message(
                f"🛑 STOP LOSS HIT\n\n"
                f"{signal['symbol']}\n\n"
                f"Buy : ₹{signal['buy']}\n"
                f"Current : ₹{current}\n"
                f"SL : ₹{signal['sl']}"
            )

            signal["status"] = "STOPLOSS"
            updated = True
            continue

        # Target 3
        if current >= signal["t3"]:

            send_message(
                f"🎯 TARGET 3 HIT\n\n"
                f"{signal['symbol']}\n\n"
                f"Current : ₹{current}"
            )

            signal["status"] = "TARGET3"
            updated = True
            continue

        # Target 2
        if current >= signal["t2"]:

            send_message(
                f"🎯 TARGET 2 HIT\n\n"
                f"{signal['symbol']}\n\n"
                f"Current : ₹{current}"
            )

            signal["status"] = "TARGET2"
            updated = True
            continue

        # Target 1
        if current >= signal["t1"]:

            send_message(
                f"🎯 TARGET 1 HIT\n\n"
                f"{signal['symbol']}\n\n"
                f"Current : ₹{current}"
            )

            signal["status"] = "TARGET1"
            updated = True

    except Exception as e:
        print(signal["symbol"], e)

if updated:

    with open("signals.json", "w") as f:
        json.dump(signals, f, indent=4)

print("Monitoring completed.")
