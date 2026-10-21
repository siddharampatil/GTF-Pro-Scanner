import os
import json
import requests
import yfinance as yf
import pandas as pd

from datetime import datetime, timezone, timedelta

# ==========================================
# GTF PRO SCANNER V9 - PAPER MONITOR
# ==========================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"

IST = timezone(timedelta(hours=5, minutes=30))

# Never chase an entry more than 0.5% above
# the planned reference price.
MAX_ENTRY_CHASE_PCT = 0.5

# Expire an untriggered signal after 5 days.
MAX_WAIT_DAYS = 5


def now_ist():
    return datetime.now(IST).isoformat(timespec="seconds")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, type(default)):
            return data

        print(f"Invalid JSON structure: {path}")
        return default

    except FileNotFoundError:
        return default

    except Exception as e:
        print(f"Could not read {path}: {e}")
        raise


def save_json(path, data):
    tmp = path + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    os.replace(tmp, path)


def send_message(message):
    response = requests.post(
        URL,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=25
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError("Telegram message failed")


def get_price_data(symbol):
    """
    Obtain recent intraday market data.
    These prices are observations, not confirmed fills.
    """

    try:
        ticker = symbol.strip().upper()

        if not ticker.endswith(".NS"):
            ticker += ".NS"

        df = yf.download(
            ticker,
            period="5d",
            interval="5m",
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=20
        )

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if "Close" not in df.columns:
            return None

        df = df.dropna(subset=["Close"])

        if df.empty:
            return None

        # Reject clearly stale intraday data.
        latest_time = pd.Timestamp(df.index[-1])

        if latest_time.tzinfo is None:
            latest_time = latest_time.tz_localize("UTC")

        latest_time = latest_time.tz_convert(IST)

        age_minutes = (
            datetime.now(IST) - latest_time.to_pydatetime()
        ).total_seconds() / 60

        if age_minutes > 45:
            print(
                f"Stale data for {symbol}: "
                f"{age_minutes:.0f} minutes old"
            )
            return None

        latest = df.iloc[-1]

        return {
            "price": float(latest["Close"]),
            "high": float(latest["High"]),
            "low": float(latest["Low"]),
            "time": latest_time.isoformat()
        }

    except Exception as e:
        print(f"Price error {symbol}: {e}")
        return None


def trade_key(signal):
    return signal.get(
        "signal_id",
        f"{signal.get('symbol')}_{signal.get('created_at')}"
    )


def record_history(history, signal):
    key = trade_key(signal)

    for old in history:
        if trade_key(old) == key:
            old.update(signal)
            return

    history.append(signal.copy())


def close_paper_trade(signal, current, reason):
    """
    Record a simulated exit trigger.

    Trigger prices are not guaranteed real-world fills.
    """

    if reason == "STOP_LOSS":
        trigger_price = float(signal["sl"])
        result = "LOSS"

    else:
        trigger_price = float(signal["t3"])
        result = "WIN"

    entry = float(signal["entry_price"])

    signal["status"] = (
        "STOPPED" if reason == "STOP_LOSS"
        else "TARGET3"
    )

    signal["result"] = result
    signal["exit_time"] = now_ist()

    # Store the trigger separately from the observed price.
    signal["exit_price"] = round(trigger_price, 2)
    signal["observed_exit_price"] = round(current, 2)
    signal["exit_reason"] = reason

    signal["pnl_points"] = round(
        trigger_price - entry, 2
    )

    signal["pnl_pct"] = round(
        ((trigger_price - entry) / entry) * 100, 2
    )

    signal["paper_trade"] = True


def main():
    print("=" * 45)
    print("GTF PRO V9 PAPER MONITOR")
    print("Time:", now_ist())
    print("=" * 45)

    signals = load_json(SIGNALS_FILE, [])
    history = load_json(HISTORY_FILE, [])

    changed = False

    for signal in signals:

        status = signal.get("status")

        if status not in ("WAITING_ENTRY", "OPEN"):
            continue

        symbol = signal.get("symbol")

        if not symbol:
            continue

        data = get_price_data(symbol)

        if data is None:
            print(f"Skipping {symbol}: price unavailable")
            continue

        current = data["price"]

        buy = float(signal["buy"])
        sl = float(signal["sl"])
        t1 = float(signal["t1"])
        t2 = float(signal["t2"])
        t3 = float(signal["t3"])

        print(
            f"{symbol}: ₹{current:.2f} | "
            f"Status: {status}"
        )

        # --------------------------
        # WAITING FOR PAPER ENTRY
        # --------------------------

        if status == "WAITING_ENTRY":

            created = signal.get("created_at")

            if created:
                try:
                    created_dt = datetime.fromisoformat(
                        created
                    )

                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(
                            tzinfo=IST
                        )

                    age_days = (
                        datetime.now(IST) - created_dt
                    ).total_seconds() / 86400

                    if age_days > MAX_WAIT_DAYS:
                        signal["status"] = "EXPIRED"
                        signal["exit_time"] = now_ist()
                        signal["exit_reason"] = (
                            "ENTRY_NOT_TRIGGERED"
                        )

                        changed = True

                        send_message(
                            f"⌛ V9 SIGNAL EXPIRED\n"
                            f"Symbol: {symbol}\n"
                            f"No paper entry was recorded.\n"
                            f"Reference: ₹{buy:.2f}"
                        )

                        continue

                except Exception as e:
                    print(
                        f"Signal date error {symbol}: {e}"
                    )

            if current < buy:
                continue

            max_entry = buy * (
                1 + MAX_ENTRY_CHASE_PCT / 100
            )

            if current > max_entry:
                signal["status"] = "EXPIRED"
                signal["exit_time"] = now_ist()
                signal["exit_reason"] = "ENTRY_GAP"

                changed = True

                send_message(
                    f"⚠️ V9 ENTRY SKIPPED\n"
                    f"Symbol: {symbol}\n"
                    f"Reference: ₹{buy:.2f}\n"
                    f"Observed: ₹{current:.2f}\n"
                    f"Reason: Price moved too far.\n"
                    f"No paper entry recorded."
                )

                continue

            # This is a paper entry, not a real purchase.
            signal["status"] = "OPEN"
            signal["entry_price"] = round(current, 2)
            signal["entry_time"] = now_ist()
            signal["entry_alert"] = True
            signal["paper_trade"] = True
            signal["observed_price_time"] = data["time"]

            changed = True

            send_message(
                f"🧪 V9 PAPER ENTRY\n"
                f"Symbol: {symbol}\n"
                f"Observed entry: ₹{current:.2f}\n"
                f"Stop-loss trigger: ₹{sl:.2f}\n"
                f"T1: ₹{t1:.2f}\n"
                f"T2: ₹{t2:.2f}\n"
                f"T3: ₹{t3:.2f}\n"
                f"Price time: {data['time']}\n"
                f"⚠️ Simulated only; no Zerodha order."
            )

        # --------------------------
        # MONITOR PAPER POSITION
        # --------------------------

        if signal.get("status") != "OPEN":
            continue

        entry = float(signal["entry_price"])

        # If both levels fall inside the same observed
        # candle, price order is unknown. Treat stop-loss
        # first to avoid optimistic simulation.
        hit_sl = data["low"] <= sl
        hit_t3 = data["high"] >= t3

        if hit_sl:
            close_paper_trade(
                signal, current, "STOP_LOSS"
            )

            record_history(history, signal)
            changed = True

            send_message(
                f"🛑 V9 PAPER STOP TRIGGERED\n"
                f"Symbol: {symbol}\n"
                f"Trigger: ₹{sl:.2f}\n"
                f"Observed price: ₹{current:.2f}\n"
                f"Modeled P&L: {signal['pnl_pct']:.2f}%\n"
                f"⚠️ Not an actual execution."
            )

            continue

        # Record target milestones only once.
        for level, price_key, time_key in [
            (1, "t1", "t1_time"),
            (2, "t2", "t2_time"),
            (3, "t3", "t3_time")
        ]:
            flag = f"t{level}_hit"
            target = float(signal[price_key])

            if (
                not signal.get(flag, False)
                and data["high"] >= target
            ):
                signal[flag] = True
                signal[time_key] = now_ist()
                changed = True

                send_message(
                    f"🎯 V9 PAPER TARGET {level}\n"
                    f"Symbol: {symbol}\n"
                    f"Target: ₹{target:.2f}\n"
                    f"Observed price: ₹{current:.2f}\n"
                    f"⚠️ Target touch is not a confirmed fill."
                )

        if hit_t3:
            close_paper_trade(
                signal, current, "TARGET3"
            )

            record_history(history, signal)
            changed = True

            send_message(
                f"✅ V9 PAPER TRADE CLOSED\n"
                f"Symbol: {symbol}\n"
                f"Modeled exit trigger: ₹{t3:.2f}\n"
                f"Observed price: ₹{current:.2f}\n"
                f"Modeled P&L: {signal['pnl_pct']:.2f}%\n"
                f"⚠️ Simulated result, not actual profit."
            )

    if changed:
        save_json(SIGNALS_FILE, signals)
        save_json(HISTORY_FILE, history)

    print("=" * 45)
    print("V9 PAPER MONITOR FINISHED")
    print("Signals:", len(signals))
    print("History records:", len(history))
    print("=" * 45)


if __name__ == "__main__":
    main()