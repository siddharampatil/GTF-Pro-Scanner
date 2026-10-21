import os
import json
import requests
from datetime import datetime, timezone, timedelta

from strategy import scan_stock
from stock_list import get_stock_list

# ==========================================
# GTF PRO SCANNER V9
# SAFER SIGNAL SELECTION
# ==========================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"

IST = timezone(timedelta(hours=5, minutes=30))

MIN_SCORE = 85
MIN_RVOL = 1.5
TOP_N = 10

# ==========================================
# UTILITIES
# ==========================================

def now_ist():
    return datetime.now(IST).isoformat(timespec="seconds")


def normalize_symbol(symbol):
    symbol = str(symbol).strip().upper()

    if not symbol.endswith(".NS") and not symbol.startswith("^"):
        symbol += ".NS"

    return symbol


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, type(default)):
            return data

        print(f"WARNING: Invalid format in {path}")
        return default

    except FileNotFoundError:
        return default

    except Exception as e:
        print(f"WARNING: Cannot read {path}: {e}")
        return default


def save_json(path, data):
    tmp = path + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    os.replace(tmp, path)


def send_message(message):
    # Keep Telegram messages below its message limit.
    chunks = []

    while len(message) > 3900:
        split_at = message.rfind("\n", 0, 3900)

        if split_at <= 0:
            split_at = 3900

        chunks.append(message[:split_at])
        message = message[split_at:].lstrip("\n")

    if message:
        chunks.append(message)

    for chunk in chunks:
        response = requests.post(
            URL,
            data={
                "chat_id": CHAT_ID,
                "text": chunk
            },
            timeout=25
        )

        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):
            raise RuntimeError(
                f"Telegram rejected message: {result}"
            )


def fmt(value):
    return f"{float(value):,.2f}"


# ==========================================
# MAIN SCANNER
# ==========================================

def main():

    print("=" * 45)
    print("GTF PRO SCANNER V9 STARTED")
    print("Time:", now_ist())
    print("=" * 45)

    stocks = get_stock_list()

    if not stocks:
        raise RuntimeError(
            "Stock list is empty. Scanner stopped."
        )

    results = []

    print(f"Total stocks to scan: {len(stocks)}")

    for index, stock in enumerate(stocks, 1):

        try:
            result = scan_stock(stock)

            if not result:
                continue

            score = float(result.get("score", 0))
            rvol = float(result.get("rvol", 0))

            if score < MIN_SCORE:
                continue

            if rvol < MIN_RVOL:
                continue

            result["symbol"] = normalize_symbol(
                result["symbol"]
            )

            results.append(result)

        except Exception as e:
            print(f"ERROR {stock}: {e}")

        if index % 50 == 0:
            print(f"Progress: {index}/{len(stocks)}")

    results.sort(
        key=lambda x: (
            float(x.get("score", 0)),
            float(x.get("adx", 0)),
            float(x.get("rvol", 0))
        ),
        reverse=True
    )

    top_results = results[:TOP_N]

    # Load existing records.
    # Never discard closed signals or trade history.
    signals = load_json(SIGNALS_FILE, [])
    history = load_json(HISTORY_FILE, [])

    # Prevent duplicate active signals for a stock.
    active = {}

    for signal in signals:

        if signal.get("status") in (
            "WAITING_ENTRY",
            "OPEN"
        ):
            symbol = signal.get("symbol")

            if symbol:
                active[symbol] = signal

    new_signals = []
    created_signals = []

    for item in top_results:

        symbol = normalize_symbol(item["symbol"])

        # Keep the existing active trade instead of
        # creating another signal for the same stock.
        if symbol in active:
            continue

        buy = float(item["buy"])
        sl = float(item["sl"])
        t1 = float(item["t1"])
        t2 = float(item["t2"])
        t3 = float(item["t3"])

        risk = buy - sl

        if buy <= 0 or risk <= 0:
            print(f"Rejected invalid risk levels: {symbol}")
            continue

        reward_risk = (t1 - buy) / risk

        if reward_risk < 2.0:
            print(f"Rejected reward/risk: {symbol}")
            continue

        signal = {
            "signal_id": (
                f"{symbol}_"
                f"{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}"
            ),
            "symbol": symbol,
            "created_at": now_ist(),

            "buy": round(buy, 2),
            "sl": round(sl, 2),
            "t1": round(t1, 2),
            "t2": round(t2, 2),
            "t3": round(t3, 2),

            "score": int(item.get("score", 0)),
            "rsi": round(float(item.get("rsi", 0)), 2),
            "adx": round(float(item.get("adx", 0)), 2),
            "rvol": round(float(item.get("rvol", 0)), 2),
            "atr": round(float(item.get("atr", 0)), 2),

            "reward_risk": round(reward_risk, 2),
            "setup": item.get(
                "setup", "CONFIRMED_BREAKOUT"
            ),

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
            "pnl_points": None
        }

        new_signals.append(signal)
        created_signals.append(signal)

        # Prevent duplicate signals within this run.
        active[symbol] = signal

    # Preserve ALL existing records, including closed
    # signals, and append newly created signals.
    updated_signals = signals + new_signals

    # Save before sending Telegram notifications.
    save_json(SIGNALS_FILE, updated_signals)

    scanned = len(stocks)
    qualified = len(results)

    lines = [
        "🔥 GTF PRO SCANNER V9",
        "",
        f"Time: {now_ist()}",
        f"Stocks scanned: {scanned}",
        f"Qualified setups: {qualified}",
        f"New signals: {len(created_signals)}",
        "",
        "⚠️ PAPER-TEST THESE SIGNALS FIRST",
        "Score is not a win probability.",
        "Entry is based on a completed daily candle.",
        ""
    ]

    if created_signals:

        lines.append("📊 NEW QUALIFIED SETUPS")
        lines.append("")

        for number, signal in enumerate(
            created_signals, 1
        ):

            lines.extend([
                f"{number}. {signal['symbol']}",
                f"Setup: {signal['setup']}",
                f"Score: {signal['score']}/100",
                f"Reference entry: ₹{fmt(signal['buy'])}",
                f"Stop-loss: ₹{fmt(signal['sl'])}",
                f"Target 1: ₹{fmt(signal['t1'])}",
                f"Target 2: ₹{fmt(signal['t2'])}",
                f"Target 3: ₹{fmt(signal['t3'])}",
                f"Reward/risk: 1:{signal['reward_risk']:.2f}",
                f"RSI: {signal['rsi']}",
                f"ADX: {signal['adx']}",
                f"Relative volume: {signal['rvol']}x",
                "Status: WAITING FOR ENTRY",
                ""
            ])

    else:

        lines.extend([
            "No new setups passed all V9 filters.",
            "No trade is also a valid outcome.",
            ""
        ])

    lines.extend([
        "Risk reminder:",
        "Verify the live price before entering.",
        "Calculate position size from your stop-loss.",
        "A stop-loss cannot guarantee an exact exit.",
        "This scanner does not place broker orders."
    ])

    message = "\n".join(lines)

    send_message(message)

    print("=" * 45)
    print("V9 SCAN COMPLETED")
    print("Scanned:", scanned)
    print("Qualified:", qualified)
    print("New signals:", len(created_signals))
    print("Signals saved:", len(updated_signals))
    print("Trade-history records:", len(history))
    print("Telegram notification sent.")
    print("=" * 45)


if __name__ == "__main__":
    main()