import os
import json
import requests
import yfinance as yf
import pandas as pd

from datetime import datetime, timezone, timedelta


# ==========================================
# GTF PRO SCANNER V10
# SINGLE-TARGET PAPER TRADE MONITOR
# ==========================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

TELEGRAM_URL = (
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
)

IST = timezone(timedelta(hours=5, minutes=30))

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"

ACTIVE_STATUSES = {"WAITING_ENTRY", "OPEN"}

MAX_ENTRY_WAIT_DAYS = 5
MAX_DATA_AGE_MINUTES = 45


def now_ist():
    return datetime.now(IST)


def load_json(path, default):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


def save_json(path, data):
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    os.replace(temp_path, path)


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return False

    try:
        response = requests.post(
            TELEGRAM_URL,
            json={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=20
        )

        response.raise_for_status()

        return response.json().get("ok", False)

    except Exception as exc:
        print(f"Telegram error: {exc}")
        return False


def get_latest_candle(symbol):
    """
    Get recent five-minute OHLC candles.

    Yahoo Finance data can be delayed or unavailable.
    No update is made when the latest candle is stale.
    """

    ticker = symbol.upper().strip()

    if not ticker.endswith(".NS"):
        ticker += ".NS"

    try:
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
            print(f"{symbol}: no intraday data.")
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close"]

        if not all(c in df.columns for c in required):
            return None

        df = df[required].dropna()

        if df.empty:
            return None

        # Select the most recent available candle.
        candle = df.iloc[-1]

        candle_time = pd.Timestamp(df.index[-1])

        if candle_time.tzinfo is None:
            # Yahoo intraday timestamps are generally
            # exchange-local. Interpret a naive timestamp
            # as Asia/Kolkata.
            candle_time = candle_time.tz_localize(
                "Asia/Kolkata"
            )
        else:
            candle_time = candle_time.tz_convert(
                "Asia/Kolkata"
            )

        age_minutes = (
            now_ist() - candle_time.to_pydatetime()
        ).total_seconds() / 60

        if age_minutes < -5:
            print(f"{symbol}: future timestamp; skipping.")
            return None

        if age_minutes > MAX_DATA_AGE_MINUTES:
            print(
                f"{symbol}: stale data "
                f"({age_minutes:.0f} minutes); skipping."
            )
            return None

        return {
            "time": candle_time.isoformat(),
            "open": float(candle["Open"]),
            "high": float(candle["High"]),
            "low": float(candle["Low"]),
            "close": float(candle["Close"])
        }

    except Exception as exc:
        print(f"{symbol}: data error: {exc}")
        return None


def close_trade(signal, reason, exit_price):
    """Close a simulated paper trade."""

    entry = float(signal["entry_price"])
    exit_price = float(exit_price)

    if entry <= 0:
        return None

    pnl_percent = ((exit_price - entry) / entry) * 100

    signal["status"] = "CLOSED"
    signal["exit_reason"] = reason
    signal["exit_price"] = round(exit_price, 2)
    signal["closed_at"] = now_ist().isoformat()
    signal["pnl_percent"] = round(pnl_percent, 2)

    message = (
        "📊 GTF PRO V10 PAPER TRADE CLOSED\n\n"
        f"Stock: {signal['symbol']}\n"
        f"Reason: {reason}\n"
        f"Entry: ₹{entry:.2f}\n"
        f"Exit: ₹{exit_price:.2f}\n"
        f"Paper P/L: {pnl_percent:+.2f}%\n\n"
        "This is a simulated result, not a broker trade."
    )

    print(message)

    return {
        "signal_id": signal.get("signal_id"),
        "symbol": signal["symbol"],
        "status": "CLOSED",
        "entry_price": round(entry, 2),
        "exit_price": round(exit_price, 2),
        "exit_reason": reason,
        "pnl_percent": round(pnl_percent, 2),
        "closed_at": signal["closed_at"]
    }, message


def main():
    print("=" * 45)
    print("GTF PRO SCANNER V10 MONITOR")
    print(now_ist().strftime("%d-%m-%Y %H:%M:%S IST"))
    print("=" * 45)

    signals = load_json(SIGNALS_FILE, [])
    history = load_json(HISTORY_FILE, [])

    if not isinstance(signals, list):
        raise ValueError(
            "signals.json must contain a list of signals."
        )

    if not isinstance(history, list):
        history = []

    changed = False
    new_history = []
    notifications = []

    for signal in signals:
        if not isinstance(signal, dict):
            continue

        status = str(
            signal.get("status", "")
        ).upper()

        if status not in ACTIVE_STATUSES:
            continue

        symbol = str(signal.get("symbol", "")).strip()

        # Require valid V10 price fields.
        try:
            buy = float(signal["buy"])
            sl = float(signal["sl"])
            target = float(signal["target"])
        except (KeyError, TypeError, ValueError):
            print(
                f"{symbol}: missing V10 fields; "
                "skipping legacy signal."
            )
            continue

        if not symbol or not (sl < buy < target):
            print(f"{symbol}: invalid levels; skipping.")
            continue

        # Expire a signal that has waited too long to enter.
        if status == "WAITING_ENTRY":
            try:
                created = datetime.fromisoformat(
                    signal["created_at"]
                )

                if created.tzinfo is None:
                    created = created.replace(tzinfo=IST)

                age_days = (
                    now_ist() - created.astimezone(IST)
                ).total_seconds() / 86400

                if age_days > MAX_ENTRY_WAIT_DAYS:
                    signal["status"] = "EXPIRED"
                    signal["exit_reason"] = "ENTRY_NOT_TRIGGERED"
                    signal["closed_at"] = now_ist().isoformat()
                    changed = True

                    notifications.append(
                        "⌛ GTF PRO V10 SIGNAL EXPIRED\n\n"
                        f"Stock: {symbol}\n"
                        "Entry trigger was not reached in time.\n"
                        "No paper trade was opened."
                    )

                    continue

            except (KeyError, ValueError):
                print(
                    f"{symbol}: invalid creation time; "
                    "skipping expiry check."
                )

        candle = get_latest_candle(symbol)

        if candle is None:
            continue

        high = candle["high"]
        low = candle["low"]
        open_price = candle["open"]

        # --------------------------------------
        # WAITING FOR ENTRY
        # --------------------------------------

        if status == "WAITING_ENTRY":
            if high < buy:
                continue

            # Conservative gap handling:
            # if price opens above the trigger, use
            # the opening price as the simulated entry.
            entry = max(buy, open_price)

            signal["entry_price"] = round(entry, 2)
            signal["entered_at"] = candle["time"]
            signal["status"] = "OPEN"

            changed = True

            notifications.append(
                "🟢 GTF PRO V10 PAPER ENTRY\n\n"
                f"Stock: {symbol}\n"
                f"Entry: ₹{entry:.2f}\n"
                f"Stop-loss: ₹{sl:.2f}\n"
                f"ONE target: ₹{target:.2f}\n\n"
                "Paper trade only. No broker order placed."
            )

            status = "OPEN"

        # --------------------------------------
        # OPEN PAPER TRADE
        # --------------------------------------

        if status == "OPEN":
            entry = float(signal["entry_price"])

            # If the stop and target are both touched
            # within the same candle, assume stop-loss
            # first to avoid optimistic backtesting.
            if low <= sl:
                result = close_trade(
                    signal,
                    "STOP_LOSS",
                    sl
                )

                if result:
                    record, message = result
                    new_history.append(record)
                    notifications.append(message)
                    changed = True

                continue

            if high >= target:
                result = close_trade(
                    signal,
                    "TARGET_HIT",
                    target
                )

                if result:
                    record, message = result
                    new_history.append(record)
                    notifications.append(message)
                    changed = True

                continue

    if changed:
        save_json(SIGNALS_FILE, signals)

    if new_history:
        history.extend(new_history)
        save_json(HISTORY_FILE, history)

    for message in notifications:
        send_telegram(message)

    closed_count = sum(
        1 for s in signals
        if isinstance(s, dict)
        and s.get("status") == "CLOSED"
    )

    open_count = sum(
        1 for s in signals
        if isinstance(s, dict)
        and s.get("status") == "OPEN"
    )

    waiting_count = sum(
        1 for s in signals
        if isinstance(s, dict)
        and s.get("status") == "WAITING_ENTRY"
    )

    print(f"Open paper trades: {open_count}")
    print(f"Waiting for entry: {waiting_count}")
    print(f"Closed signals: {closed_count}")
    print(f"New history records: {len(new_history)}")
    print("Monitor finished.")


if __name__ == "__main__":
    main()