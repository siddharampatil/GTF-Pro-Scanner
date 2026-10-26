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
        return json.load(f)


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
            json={"chat_id": CHAT_ID, "text": message},
            timeout=20
        )

        response.raise_for_status()
        return response.json().get("ok", False)

    except Exception as exc:
        print(f"Telegram error: {exc}")
        return False


def get_latest_candle(symbol):
    """Fetch recent five-minute candles from Yahoo Finance."""

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

        if not all(col in df.columns for col in required):
            print(f"{symbol}: required candle fields missing.")
            return None

        df = df[required].dropna()

        if df.empty:
            return None

        candle = df.iloc[-1]
        candle_time = pd.Timestamp(df.index[-1])

        if candle_time.tzinfo is None:
            candle_time = candle_time.tz_localize("Asia/Kolkata")
        else:
            candle_time = candle_time.tz_convert("Asia/Kolkata")

        age_minutes = (
            now_ist() - candle_time.to_pydatetime()
        ).total_seconds() / 60

        if age_minutes < -5:
            print(f"{symbol}: future candle; skipping.")
            return None

        if age_minutes > MAX_DATA_AGE_MINUTES:
            print(
                f"{symbol}: stale candle "
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
    """Close a simulated V10 paper trade."""

    entry = float(signal["entry_price"])

    if entry <= 0:
        return None

    exit_price = float(exit_price)

    pnl_percent = ((exit_price - entry) / entry) * 100

    signal["status"] = "CLOSED"
    signal["exit_reason"] = reason
    signal["exit_price"] = round(exit_price, 2)
    signal["closed_at"] = now_ist().isoformat()
    signal["pnl_percent"] = round(pnl_percent, 2)

    record = {
        "signal_id": signal.get("signal_id"),
        "strategy_version": "V10",
        "symbol": signal["symbol"],
        "status": "CLOSED",
        "entry_price": round(entry, 2),
        "exit_price": round(exit_price, 2),
        "exit_reason": reason,
        "pnl_percent": round(pnl_percent, 2),
        "closed_at": signal["closed_at"]
    }

    message = (
        "📊 GTF PRO V10 PAPER TRADE CLOSED\n\n"
        f"Stock: {signal['symbol']}\n"
        f"Reason: {reason}\n"
        f"Entry: ₹{entry:.2f}\n"
        f"Exit: ₹{exit_price:.2f}\n"
        f"Paper P/L: {pnl_percent:+.2f}%\n\n"
        "Simulated result only; no broker order was placed."
    )

    return record, message


def main():
    print("=" * 45)
    print("GTF PRO SCANNER V10 MONITOR")
    print(now_ist().strftime("%d-%m-%Y %H:%M:%S IST"))
    print("=" * 45)

    signals = load_json(SIGNALS_FILE, [])
    history = load_json(HISTORY_FILE, [])

    if not isinstance(signals, list):
        raise ValueError(
            "signals.json must be a JSON list. "
            "No records have been changed."
        )

    if not isinstance(history, list):
        raise ValueError(
            "trade_history.json must be a JSON list. "
            "No records have been changed."
        )

    # Keep existing history and identify recorded trade IDs.
    existing_ids = {
        str(item.get("signal_id"))
        for item in history
        if isinstance(item, dict)
        and item.get("signal_id") is not None
    }

    changed = False
    notifications = []
    new_history = []

    for signal in signals:
        if not isinstance(signal, dict):
            continue

        # Never alter legacy V8/V9 records.
        if signal.get("strategy_version") != "V10":
            continue

        status = str(signal.get("status", "")).upper()

        if status not in ACTIVE_STATUSES:
            continue

        symbol = str(signal.get("symbol", "")).strip()

        try:
            buy = float(signal["buy"])
            sl = float(signal["sl"])
            target = float(signal["target"])
        except (KeyError, TypeError, ValueError):
            print(f"{symbol}: invalid V10 fields; skipping.")
            continue

        if not symbol or not (0 < sl < buy < target):
            print(f"{symbol}: invalid trade levels; skipping.")
            continue

        # Expire a pending entry after five days.
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
                        "Entry was not triggered within five days.\n"
                        "No paper trade was opened."
                    )

                    continue

            except (KeyError, ValueError, TypeError):
                print(f"{symbol}: invalid creation time; skipping.")
                continue

        candle = get_latest_candle(symbol)

        if candle is None:
            continue

        high = candle["high"]
        low = candle["low"]
        open_price = candle["open"]

        # ----------------------------------
        # WAITING FOR ENTRY
        # ----------------------------------
        if status == "WAITING_ENTRY":
            if high < buy:
                continue

            # Do not assume an entry if the candle
            # opened above the target.
            if open_price >= target:
                signal["status"] = "EXPIRED"
                signal["exit_reason"] = "ENTRY_GAP_ABOVE_TARGET"
                signal["closed_at"] = now_ist().isoformat()
                changed = True

                notifications.append(
                    "⚠️ GTF PRO V10 SIGNAL SKIPPED\n\n"
                    f"Stock: {symbol}\n"
                    "Price opened at or above the target.\n"
                    "No paper entry was recorded."
                )
                continue

            # If price gaps above the entry, use the open.
            entry = max(buy, open_price)

            # Reject a gap entry if reward/risk falls below 2.
            risk = entry - sl
            reward = target - entry

            if risk <= 0 or reward / risk < 2.0:
                signal["status"] = "EXPIRED"
                signal["exit_reason"] = "GAP_RISK_REWARD_FAILED"
                signal["closed_at"] = now_ist().isoformat()
                changed = True

                notifications.append(
                    "⚠️ GTF PRO V10 ENTRY SKIPPED\n\n"
                    f"Stock: {symbol}\n"
                    "Gap-up reduced the planned reward/risk.\n"
                    "No paper entry was recorded."
                )
                continue

            # Do not enter if price already touched the
            # stop during the same candle.
            if low <= sl:
                signal["status"] = "EXPIRED"
                signal["exit_reason"] = "AMBIGUOUS_ENTRY_CANDLE"
                signal["closed_at"] = now_ist().isoformat()
                changed = True
                continue

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

            # Avoid assuming target/stop order within the
            # entry candle. Check outcomes on a later candle.
            continue

        # ----------------------------------
        # OPEN PAPER TRADE
        # ----------------------------------
        if status == "OPEN":
            entry = float(signal.get("entry_price") or 0)

            if entry <= 0:
                print(f"{symbol}: invalid entry price; skipping.")
                continue

            # Skip the candle used to enter.
            entered_at = signal.get("entered_at")

            if entered_at and candle["time"] <= entered_at:
                continue

            # Conservative ordering if both levels touched.
            if low <= sl:
                result = close_trade(signal, "STOP_LOSS", sl)

            elif high >= target:
                result = close_trade(signal, "TARGET_HIT", target)

            else:
                continue

            if result:
                record, message = result
                signal_id = str(record.get("signal_id") or "")

                if signal_id and signal_id in existing_ids:
                    print(
                        f"{symbol}: history already contains "
                        f"{signal_id}; avoiding duplicate."
                    )
                else:
                    new_history.append(record)

                    if signal_id:
                        existing_ids.add(signal_id)

                notifications.append(message)
                changed = True

    # Save records without deleting old V8/V9 data.
    if changed:
        save_json(SIGNALS_FILE, signals)

    if new_history:
        history.extend(new_history)
        save_json(HISTORY_FILE, history)

    for message in notifications:
        send_telegram(message)

    open_count = sum(
        1 for s in signals
        if isinstance(s, dict)
        and s.get("strategy_version") == "V10"
        and s.get("status") == "OPEN"
    )

    waiting_count = sum(
        1 for s in signals
        if isinstance(s, dict)
        and s.get("strategy_version") == "V10"
        and s.get("status") == "WAITING_ENTRY"
    )

    closed_count = sum(
        1 for s in signals
        if isinstance(s, dict)
        and s.get("strategy_version") == "V10"
        and s.get("status") == "CLOSED"
    )

    print(f"V10 open paper trades: {open_count}")
    print(f"V10 waiting for entry: {waiting_count}")
    print(f"V10 closed signals: {closed_count}")
    print(f"New history records: {len(new_history)}")
    print("Monitor finished.")


if __name__ == "__main__":
    main()