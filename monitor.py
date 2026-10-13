
import os
import json
import time
import requests
import yfinance as yf
import pandas as pd
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
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except Exception as e:
        print(f"⚠️ Could not load {path}: {e}")
        return default


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def send(text):
    try:
        r = requests.post(
            URL,
            data={"chat_id": CHAT_ID, "text": text},
            timeout=25,
        )
        r.raise_for_status()
        result = r.json()
        if not result.get("ok"):
            print(f"⚠️ Telegram rejected message: {result}")
    except Exception as e:
        # Telegram failure must not prevent saving trade results.
        print(f"⚠️ Telegram send failed: {e}")


def yf_symbol(symbol):
    """Convert scanner symbols to Yahoo Finance NSE symbols."""
    symbol = str(symbol).strip().upper()

    if symbol.startswith("^") or "." in symbol or "=" in symbol:
        return symbol

    return symbol + ".NS"


def current_price(symbol):
    ticker = yf_symbol(symbol)

    try:
        df = yf.download(
            ticker,
            period="5d",
            interval="5m",
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=20,
        )

        if df is None or df.empty:
            print(f"⚠️ No price data for {ticker}")
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"]

        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]

        close = pd.to_numeric(close, errors="coerce").dropna()

        if close.empty:
            return None

        price = float(close.iloc[-1])

        if price <= 0:
            return None

        print(f"📊 {ticker}: latest available price ₹{price:.2f}")
        return round(price, 2)

    except Exception as e:
        print(f"❌ Price download failed for {ticker}: {e}")
        return None


def trade_key(signal):
    # Prefer a persistent unique ID if your scanner creates one.
    return str(
        signal.get("signal_id")
        or (
            signal.get("symbol", ""),
            signal.get("created_at", signal.get("signal_time", "")),
            signal.get("buy", ""),
        )
    )


signals = load(SIGNALS_FILE, [])
history = load(HISTORY_FILE, [])

if not isinstance(signals, list) or not isinstance(history, list):
    raise RuntimeError("signals.json and trade_history.json must contain JSON lists.")

closed_keys = {
    trade_key(item)
    for item in history
    if isinstance(item, dict)
}

print(f"🚀 V8 monitor started: {len(signals)} signals, {len(history)} history records")

for signal in signals:
    if not isinstance(signal, dict):
        continue

    status = signal.get("status")

    if status not in ("WAITING_ENTRY", "OPEN"):
        continue

    symbol = signal.get("symbol", "")

    if not symbol:
        print("⚠️ Skipping signal with missing symbol")
        continue

    try:
        buy = float(signal["buy"])
        sl = float(signal["sl"])
        t1 = float(signal["t1"])
        t2 = float(signal["t2"])
        t3 = float(signal["t3"])

        if not (0 < sl < buy < t1 <= t2 <= t3):
            print(f"⚠️ Invalid price levels for {symbol}; skipping")
            continue

        current = current_price(symbol)

        if current is None:
            print(f"⏳ {symbol}: price unavailable; no status change")
            continue

        # Confirm entry only after price reaches the scanner entry level.
        if status == "WAITING_ENTRY":
            if current < buy:
                print(f"⏳ {symbol}: waiting for entry ₹{buy:.2f}")
                continue

            signal["status"] = "OPEN"
            signal["entry_price"] = current
            signal["entry_time"] = now_ist()
            signal["entry_alert"] = True
            status = "OPEN"

            # Persist entry before attempting Telegram delivery.
            save(SIGNALS_FILE, signals)

            send(
                "🚀 BUY ENTRY CONFIRMED — V8\n\n"
                f"{symbol}\n"
                f"Entry: ₹{current:.2f}\n"
                f"Stop Loss: ₹{sl:.2f}\n"
                f"T1: ₹{t1:.2f}\n"
                f"T2: ₹{t2:.2f}\n"
                f"T3: ₹{t3:.2f}"
            )

        entry = float(signal.get("entry_price") or buy)

        # Use the actual confirmed entry for P&L.
        if entry <= 0:
            print(f"⚠️ Invalid entry for {symbol}")
            continue

        outcome = None
        exit_price = None

        # Existing policy: stop-loss closes as LOSS;
        # T3 closes as WIN. T1/T2 are milestones only.
        if current <= sl:
            outcome = "LOSS"
            exit_price = sl

        elif current >= t3:
            outcome = "WIN"
            exit_price = t3

        if outcome:
            signal["status"] = "STOPPED" if outcome == "LOSS" else "TARGET3"
            signal["result"] = outcome
            signal["exit_price"] = exit_price
            signal["exit_time"] = now_ist()
            signal["pnl_points"] = round(exit_price - entry, 2)
            signal["pnl_pct"] = round(
                (exit_price - entry) / entry * 100, 2
            )

            if outcome == "WIN":
                signal["t3_hit"] = True
                signal.setdefault("t3_time", now_ist())

            key = trade_key(signal)

            if key not in closed_keys:
                history.append(dict(signal))
                closed_keys.add(key)

            # Save both files BEFORE sending the notification.
            save(SIGNALS_FILE, signals)
            save(HISTORY_FILE, history)

            if outcome == "LOSS":
                send(
                    "🛑 LOSS — STOP LOSS HIT\n\n"
                    f"{symbol}\n"
                    f"Entry: ₹{entry:.2f}\n"
                    f"Exit: ₹{exit_price:.2f}\n"
                    f"Latest price: ₹{current:.2f}\n"
                    f"P&L: {signal['pnl_pct']:.2f}%"
                )
            else:
                send(
                    "🏆 WIN — TARGET 3 HIT\n\n"
                    f"{symbol}\n"
                    f"Entry: ₹{entry:.2f}\n"
                    f"Exit: ₹{exit_price:.2f}\n"
                    f"Latest price: ₹{current:.2f}\n"
                    f"P&L: {signal['pnl_pct']:.2f}%"
                )

            print(f"✅ {symbol} closed: {outcome} ({signal['pnl_pct']:.2f}%)")
            continue

        # Record target milestones only once.
        changed = False

        for target, field, time_field in [
            (t1, "t1_hit", "t1_time"),
            (t2, "t2_hit", "t2_time"),
        ]:
            if current >= target and not signal.get(field, False):
                signal[field] = True
                signal[time_field] = now_ist()
                changed = True

                send(
                    f"🎯 {field.upper().replace('_HIT', '')} HIT\n\n"
                    f"{symbol}\n"
                    f"Entry: ₹{entry:.2f}\n"
                    f"Latest price: ₹{current:.2f}\n"
                    f"Target: ₹{target:.2f}\n"
                    f"Unrealised P&L: {(current-entry)/entry*100:.2f}%"
                )

        if changed:
            save(SIGNALS_FILE, signals)

    except Exception as e:
        print(f"❌ Monitor error for {symbol}: {e}")

# Always save the final state.
save(SIGNALS_FILE, signals)
save(HISTORY_FILE, history)

print(
    f"✅ Monitor completed | "
    f"Open: {sum(1 for s in signals if isinstance(s, dict) and s.get('status') == 'OPEN')} | "
    f"Closed history: {len(history)}"
)
