# GTF PRO SCANNER V11
# Dual-mode paper scanner
# Bullish Nifty: Swing BUY candidates
# Bearish Nifty: Intraday SHORT candidates
# No broker orders are placed.

import os
import json
import requests

from datetime import datetime
from zoneinfo import ZoneInfo

from strategy_v11 import market_regime, scan_stock_v11
from stock_list import get_stock_list


IST = ZoneInfo("Asia/Kolkata")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

MAX_STOCKS = 755
MAX_ALERTS = 10

SIGNALS_FILE = "signals_v11.json"


def send_telegram(message):
    """Send a Telegram message when credentials are configured."""

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing; printing message instead.")
        print(message)
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
            },
            timeout=20,
        )

        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            print(f"Telegram API error: {result}")
            return False

        return True

    except Exception as exc:
        print(f"Telegram send error: {exc}")
        return False


def save_signals(regime, signals):
    """Save the current paper-screening results."""

    data = {
        "version": "V11",
        "timestamp": datetime.now(IST).isoformat(),
        "market_regime": regime,
        "signals": signals,
        "paper_only": True,
    }

    try:
        with open(SIGNALS_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

        print(f"Saved {len(signals)} results to {SIGNALS_FILE}")

    except Exception as exc:
        print(f"Unable to save signals: {exc}")


def format_message(regime, signals):
    """Create a readable Telegram screening report."""

    now = datetime.now(IST).strftime("%d-%m-%Y %H:%M IST")

    lines = [
        "📊 GTF PRO SCANNER V11",
        f"🕒 {now}",
        f"📈 NIFTY REGIME: {regime}",
        "🧪 PAPER SCREENING ONLY",
        "",
    ]

    if regime == "BULLISH":
        lines.append("🟢 MODE: SWING BUY CANDIDATES")
    elif regime == "BEARISH":
        lines.append("🔴 MODE: INTRADAY SHORT CANDIDATES")
        lines.append(
            "⚠️ These are daily-chart candidates, not confirmed "
            "intraday entries. Do not enter without intraday confirmation."
        )

    lines.append("")

    if not signals:
        lines.append("No qualifying candidates found.")
        lines.append("No trade is a valid result.")
    else:
        for number, signal in enumerate(signals, start=1):
            lines.extend([
                f"{number}. {signal['symbol']}",
                f"Mode: {signal['mode']}",
                f"Reference entry: ₹{signal['reference_entry']:.2f}",
                f"Stop loss: ₹{signal['stop_loss']:.2f}",
                f"Target: ₹{signal['target']:.2f}",
                f"Quantity estimate: {signal['quantity']}",
                f"Planned risk: ₹{signal['planned_risk']:.2f}",
                f"Reward/risk: {signal['reward_risk']:.1f}:1",
                f"Reference candle: {signal['market_price_date']}",
                "Status: PAPER ONLY",
                "",
            ])

    lines.extend([
        "⚠️ Not financial advice.",
        "No broker orders have been placed.",
    ])

    return "\n".join(lines)


def main():
    print("=" * 45)
    print("GTF PRO SCANNER V11 STARTED")
    print("=" * 45)

    regime = market_regime()

    if regime not in ("BULLISH", "BEARISH"):
        print(f"No scan: market regime is {regime}.")
        save_signals(regime, [])
        send_telegram(format_message(regime, []))
        return

    mode = "SWING_BUY" if regime == "BULLISH" else "INTRADAY_SHORT"

    try:
        stocks = get_stock_list()
    except Exception as exc:
        print(f"Stock-list error: {exc}")
        send_telegram(
            "GTF PRO SCANNER V11\n"
            "Unable to load the NSE stock list.\n"
            "No trade signals generated."
        )
        return

    if not stocks:
        print("No stocks loaded; stopping safely.")
        send_telegram(
            "GTF PRO SCANNER V11\n"
            "No NSE stocks loaded.\n"
            "No trade signals generated."
        )
        return

    stocks = stocks[:MAX_STOCKS]
    print(f"Market mode: {mode}")
    print(f"Stocks to scan: {len(stocks)}")

    results = []

    for index, symbol in enumerate(stocks, start=1):
        try:
            signal = scan_stock_v11(symbol, mode)

            if signal:
                results.append(signal)
                print(
                    f"MATCH {symbol}: "
                    f"score not assigned; "
                    f"entry ₹{signal['reference_entry']}"
                )

        except Exception as exc:
            print(f"Scan error {symbol}: {exc}")

        if index % 50 == 0:
            print(f"Progress: {index}/{len(stocks)}")

    # Sort by the strongest trend proxy: ADX is added in a future refinement.
    results = results[:MAX_ALERTS]

    save_signals(regime, results)

    message = format_message(regime, results)
    send_telegram(message)

    print("=" * 45)
    print(f"V11 COMPLETE | Regime={regime}")
    print(f"Candidates={len(results)}")
    print("PAPER ONLY — NO ORDERS PLACED")
    print("=" * 45)


if __name__ == "__main__":
    main()
