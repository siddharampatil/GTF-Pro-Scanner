import os
import json
import time
import requests

from datetime import datetime, timezone, timedelta

from strategy import scan_stock
from stock_list import get_stock_list


# ==========================================
# GTF PRO SCANNER V10
# MAXIMUM 5 SWING-TRADE SIGNALS
# ==========================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

TELEGRAM_URL = (
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
)

IST = timezone(timedelta(hours=5, minutes=30))

SIGNALS_FILE = "signals.json"

MAX_SIGNALS = 5
MIN_SCORE = 80

ACTIVE_STATUSES = {
    "WAITING_ENTRY",
    "OPEN"
}


def now_ist():
    return datetime.now(IST)


def timestamp():
    return now_ist().isoformat()


def load_signals():
    """Load existing signals without discarding history."""

    if not os.path.exists(SIGNALS_FILE):
        return []

    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            if isinstance(data.get("signals"), list):
                return data["signals"]

        print("WARNING: Unexpected signals.json format.")
        return []

    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: Could not load signals: {exc}")
        raise


def save_signals(signals):
    """Write signals safely to disk."""

    temp_file = SIGNALS_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(signals, f, indent=2, ensure_ascii=False)

    os.replace(temp_file, SIGNALS_FILE)


def send_telegram(message):
    """Send a Telegram message if credentials exist."""

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

        result = response.json()

        if not result.get("ok"):
            print("Telegram API rejected the message.")
            return False

        return True

    except Exception as exc:
        print(f"Telegram error: {exc}")
        return False


def get_active_symbols(signals):
    """Prevent duplicate active signals for a stock."""

    active = set()

    for signal in signals:
        if not isinstance(signal, dict):
            continue

        status = str(signal.get("status", "")).upper()
        symbol = str(signal.get("symbol", "")).upper()

        if status in ACTIVE_STATUSES and symbol:
            active.add(symbol.replace(".NS", ""))

    return active


def build_signal(candidate):
    """Create a single-target paper-trading signal."""

    created = timestamp()

    return {
        "signal_id": (
            f"{candidate['symbol']}_"
            f"{now_ist().strftime('%Y%m%d_%H%M%S')}"
        ),

        "symbol": candidate["symbol"],
        "direction": "BUY",
        "setup": candidate["setup"],

        "status": "WAITING_ENTRY",

        "created_at": created,
        "signal_candle_date": candidate.get(
            "signal_candle_date", ""
        ),

        "buy": candidate["buy"],
        "sl": candidate["sl"],
        "target": candidate["target"],

        "score": candidate["score"],
        "rvol": candidate["rvol"],
        "rsi": candidate["rsi"],
        "adx": candidate["adx"],
        "atr": candidate["atr"],

        "risk_per_share": candidate["risk_per_share"],
        "reward_per_share": candidate["reward_per_share"],
        "reward_risk": candidate["reward_risk"],

        "entry_price": None,
        "exit_price": None,
        "exit_reason": None
    }


def format_report(scanned, qualified, new_signals):
    """Create the V10 Telegram report."""

    lines = [
        "🔥 GTF PRO SCANNER V10",
        "Swing Trading | NSE Cash",
        "",
        f"Time: {now_ist().strftime('%d-%m-%Y %H:%M IST')}",
        f"Stocks scanned: {scanned}",
        f"Qualified candidates: {qualified}",
        f"New signals: {len(new_signals)}",
        "",
        "━━━━━━━━━━━━━━━━━━"
    ]

    if not new_signals:
        lines.extend([
            "",
            "NO NEW TRADE SIGNALS",
            "",
            "No setup passed the selection rules,",
            "or existing active signals blocked",
           "duplicate entries.",
            "",
            "No trade is also a valid outcome."
        ])

    for index, signal in enumerate(new_signals, start=1):
        lines.extend([
            "",
            f"📌 SIGNAL {index}: {signal['symbol']}",
            f"Setup: {signal['setup']}",
            f"Quality score: {signal['score']}/100",
            "",
            f"Entry trigger: ₹{signal['buy']:.2f}",
            f"Stop-loss: ₹{signal['sl']:.2f}",
            f"ONE target: ₹{signal['target']:.2f}",
            "",
            f"Planned reward:risk = 1:{signal['reward_risk']:.2f}",
            f"Relative volume: {signal['rvol']:.2f}x",
            f"RSI: {signal['rsi']:.1f}",
            f"ADX: {signal['adx']:.1f}",
            "",
            "Status: WAITING FOR ENTRY",
            "Instrument: NSE cash equity",
            "Holding plan: Swing trade, 2–10 sessions",
            "━━━━━━━━━━━━━━━━━━"
        ])

    lines.extend([
        "",
        "⚠️ IMPORTANT",
        "• Paper-test before risking real money.",
        "• Score is NOT win probability.",
        "• 98–99% accuracy is not guaranteed.",
        "• Entry is a trigger, not a guaranteed fill.",
        "• Verify live price and liquidity before entry.",
        "• Calculate quantity from your risk limit.",
        "• This scanner does not place broker orders."
    ])

    return "\n".join(lines)


def main():
    print("=" * 45)
    print("GTF PRO SCANNER V10")
    print("Starting NSE swing scan...")
    print("=" * 45)

    signals = load_signals()
    active_symbols = get_active_symbols(signals)

    try:
        stocks = list(dict.fromkeys(get_stock_list()))
    except Exception as exc:
        message = (
            "⚠️ GTF PRO SCANNER V10\n\n"
            f"Could not load NSE stock list:\n{exc}"
        )
        print(message)
        send_telegram(message)
        raise

    if not stocks:
        raise RuntimeError("NSE stock list is empty.")

    candidates = []
    scanned = 0

    for symbol in stocks:
        scanned += 1

        try:
            clean_symbol = (
                str(symbol).strip().upper().replace(".NS", "")
            )

            if not clean_symbol:
                continue

            # Do not generate a second active signal
            # for a stock that already has one.
            if clean_symbol in active_symbols:
                continue

            result = scan_stock(symbol)

            if not result:
                continue

            score = int(result.get("score", 0))
            reward_risk = float(
                result.get("reward_risk", 0)
            )

            if score < MIN_SCORE:
                continue

            if reward_risk < 2.0:
                continue

            required = [
                "symbol",
                "buy",
                "sl",
                "target",
                "rvol",
                "rsi",
                "adx",
                "atr",
                "risk_per_share",
                "reward_per_share"
            ]

            if not all(key in result for key in required):
                print(
                    f"Skipping {symbol}: missing V10 fields."
                )
                continue

            buy = float(result["buy"])
            sl = float(result["sl"])
            target = float(result["target"])

            if not (sl < buy < target):
                print(
                    f"Skipping {symbol}: invalid price levels."
                )
                continue

            candidates.append(result)

        except Exception as exc:
            print(f"Error scanning {symbol}: {exc}")

        # Avoid hammering the data provider.
        time.sleep(0.15)

    # Highest scores first; volume is a tie-breaker.
    candidates.sort(
        key=lambda item: (
            int(item.get("score", 0)),
            float(item.get("rvol", 0))
        ),
        reverse=True
    )

    # At most five new calls in this scan.
    selected = candidates[:MAX_SIGNALS]

    new_signals = []

    for candidate in selected:
        signal = build_signal(candidate)
        signals.append(signal)
        new_signals.append(signal)

        # Prevent duplicates within this same run.
        active_symbols.add(signal["symbol"])

    save_signals(signals)

    report = format_report(
        scanned=scanned,
        qualified=len(candidates),
        new_signals=new_signals
    )

    print(report)
    send_telegram(report)

    print("=" * 45)
    print(f"Stocks scanned: {scanned}")
    print(f"Qualified candidates: {len(candidates)}")
    print(f"New signals: {len(new_signals)}")
    print("=" * 45)


if __name__ == "__main__":
    main()