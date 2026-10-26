import os
import json
import time
import requests

from datetime import datetime, timezone, timedelta

from strategy import scan_stock
from stock_list import get_stock_list


# ==========================================
# GTF PRO SCANNER V10
# NSE CASH SWING TRADING
# MAXIMUM 5 NEW SIGNALS PER SCAN
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
MIN_REWARD_RISK = 2.0

ACTIVE_STATUSES = {
    "WAITING_ENTRY",
    "OPEN"
}


def now_ist():
    return datetime.now(IST)


def timestamp():
    return now_ist().isoformat()


# ==========================================
# LOAD AND SAVE SIGNALS
# ==========================================

def load_signals():
    """Load existing signals without deleting records."""

    if not os.path.exists(SIGNALS_FILE):
        return []

    with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if isinstance(data.get("signals"), list):
            return data["signals"]

    raise ValueError(
        "Unexpected signals.json format. "
        "File was not overwritten."
    )


def save_signals(signals):
    """Save signals using a temporary file."""

    temp_file = SIGNALS_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            signals,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(temp_file, SIGNALS_FILE)


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):
    """Send a Telegram message."""

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
            print(f"Telegram rejected message: {result}")
            return False

        return True

    except Exception as exc:
        print(f"Telegram error: {exc}")
        return False


# ==========================================
# ACTIVE V10 SIGNALS
# ==========================================

def get_active_symbols(signals):
    """
    Only valid V10 active signals block duplicates.
    Old V8/V9 records remain untouched.
    """

    active = set()

    for signal in signals:
        if not isinstance(signal, dict):
            continue

        if signal.get("strategy_version") != "V10":
            continue

        status = str(
            signal.get("status", "")
        ).upper()

        symbol = str(
            signal.get("symbol", "")
        ).strip().upper()

        if status not in ACTIVE_STATUSES or not symbol:
            continue

        try:
            buy = float(signal["buy"])
            sl = float(signal["sl"])
            target = float(signal["target"])
        except (KeyError, TypeError, ValueError):
            continue

        if sl < buy < target:
            active.add(symbol.replace(".NS", ""))

    return active


# ==========================================
# CREATE V10 SIGNAL
# ==========================================

def build_signal(candidate):
    """Build one single-target paper-trade signal."""

    created = timestamp()

    symbol = str(candidate["symbol"]).strip().upper()

    return {
        "strategy_version": "V10",

        "signal_id": (
            f"{symbol}_"
            f"{now_ist().strftime('%Y%m%d_%H%M%S')}"
        ),

        "symbol": symbol,
        "direction": "BUY",
        "setup": candidate.get("setup", "V10_SWING"),

        "status": "WAITING_ENTRY",

        "created_at": created,

        "signal_candle_date": candidate.get(
            "signal_candle_date", ""
        ),

        "buy": round(float(candidate["buy"]), 2),
        "sl": round(float(candidate["sl"]), 2),
        "target": round(float(candidate["target"]), 2),

        "score": int(candidate["score"]),

        "rvol": round(float(candidate["rvol"]), 2),
        "rsi": round(float(candidate["rsi"]), 2),
        "adx": round(float(candidate["adx"]), 2),
        "atr": round(float(candidate["atr"]), 2),

        "risk_per_share": round(
            float(candidate["risk_per_share"]), 2
        ),

        "reward_per_share": round(
            float(candidate["reward_per_share"]), 2
        ),

        "reward_risk": round(
            float(candidate["reward_risk"]), 2
        ),

        "entry_price": None,
        "entered_at": None,

        "exit_price": None,
        "exit_reason": None,
        "closed_at": None,
        "pnl_percent": None
    }


# ==========================================
# TELEGRAM SCAN REPORT
# ==========================================

def format_report(scanned, qualified, new_signals):

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
            "or existing V10 signals blocked duplicates.",
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
            "Holding plan: Swing trade, 2-10 sessions",
            "━━━━━━━━━━━━━━━━━━"
        ])

    lines.extend([
        "",
        "⚠️ IMPORTANT",
        "• Paper-test before risking real money.",
        "• Score is NOT win probability.",
        "• No accuracy percentage is guaranteed.",
        "• Entry trigger is not a guaranteed fill.",
        "• Check live price and liquidity before entry.",
        "• Calculate quantity from your risk limit.",
        "• This scanner does not place broker orders."
    ])

    return "\n".join(lines)


# ==========================================
# MAIN SCANNER
# ==========================================

def main():

    print("=" * 45)
    print("GTF PRO SCANNER V10")
    print(now_ist().strftime("%d-%m-%Y %H:%M:%S IST"))
    print("Starting NSE swing scan...")
    print("=" * 45)

    signals = load_signals()

    active_symbols = get_active_symbols(signals)

    # Load stock list.
    try:
        stocks = list(
            dict.fromkeys(get_stock_list())
        )

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

    # Scan stocks.
    for symbol in stocks:

        scanned += 1

        try:
            clean_symbol = (
                str(symbol)
                .strip()
                .upper()
                .replace(".NS", "")
            )

            if not clean_symbol:
                continue

            # Skip duplicate V10 active signals.
            if clean_symbol in active_symbols:
                continue

            result = scan_stock(symbol)

            if not result:
                continue

            # Validate score and reward/risk.
            score = int(result.get("score", 0))

            reward_risk = float(
                result.get("reward_risk", 0)
            )

            if score < MIN_SCORE:
                continue

            if reward_risk < MIN_REWARD_RISK:
                continue

            required_fields = [
                "symbol",
                "setup",
                "buy",
                "sl",
                "target",
                "score",
                "rvol",
                "rsi",
                "adx",
                "atr",
                "risk_per_share",
                "reward_per_share",
                "reward_risk"
            ]

            if not all(
                key in result for key in required_fields
            ):
                print(
                    f"Skipping {symbol}: "
                    "missing required V10 fields."
                )
                continue

            buy = float(result["buy"])
            sl = float(result["sl"])
            target = float(result["target"])

            # Validate trade levels.
            if not (0 < sl < buy < target):
                print(
                    f"Skipping {symbol}: invalid price levels."
                )
                continue

            if buy - sl <= 0:
                continue

            actual_rr = (target - buy) / (buy - sl)

            if actual_rr < MIN_REWARD_RISK:
                print(
                    f"Skipping {symbol}: "
                    "reward/risk below minimum."
                )
                continue

            candidates.append(result)

        except Exception as exc:

            print(f"Error scanning {symbol}: {exc}")

        # Reduce request frequency.
        time.sleep(0.15)

    # Rank candidates by score, then relative volume.
    candidates.sort(
        key=lambda item: (
            int(item.get("score", 0)),
            float(item.get("rvol", 0))
        ),
        reverse=True
    )

    # Maximum five new signals per scan.
    selected = candidates[:MAX_SIGNALS]

    new_signals = []

    for candidate in selected:

        signal = build_signal(candidate)

        # Protect against duplicate symbols in this run.
        clean_symbol = signal["symbol"].replace(".NS", "")

        if clean_symbol in active_symbols:
            continue

        signals.append(signal)
        new_signals.append(signal)

        active_symbols.add(clean_symbol)

    # Save existing and new records together.
    save_signals(signals)

    # Report results.
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