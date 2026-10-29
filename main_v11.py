import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd
import yfinance as yf

from strategy_v11 import analyze_stock
from stock_list import get_stock_list


# =====================================================
# GTF PRO SCANNER V11
# Bullish: Swing BUY candidates
# Bearish: Intraday SHORT candidates for paper trading
# Sideways/uncertain: No trade
# =====================================================

VERSION = "GTF PRO SCANNER V11"

IST = timezone(timedelta(hours=5, minutes=30))

SIGNALS_FILE = "signals_v11.json"

MIN_DATA = 220
MAX_STOCKS = 800
TOP_N = 10

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def now_ist():
    return datetime.now(IST).strftime("%d-%m-%Y %H:%M IST")


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning(
            "Telegram secrets missing. Message not sent."
        )
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

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
            logging.error("Telegram rejected the message.")
            return False

        return True

    except Exception as exc:
        logging.error("Telegram error: %s", exc)
        return False


def load_stock_symbols():
    symbols = get_stock_list()

    if not symbols:
        raise RuntimeError(
            "Stock list is empty. Scanner stopped."
        )

    cleaned = []

    for symbol in symbols:
        symbol = str(symbol).strip().upper()

        if not symbol:
            continue

        if not symbol.endswith(".NS"):
            symbol = symbol + ".NS"

        if symbol not in cleaned:
            cleaned.append(symbol)

    if not cleaned:
        raise RuntimeError(
            "No valid NSE symbols found."
        )

    return cleaned[:MAX_STOCKS]


def download_daily_data(symbol, period="2y"):
    try:
        df = yf.download(
            symbol,
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=20,
        )

        if df is None or df.empty:
            return None

        # Handle yfinance MultiIndex columns.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.loc[:, ~df.columns.duplicated()]

        required = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]

        if not all(
            column in df.columns
            for column in required
        ):
            logging.warning(
                "%s: Required OHLCV columns missing.",
                symbol,
            )
            return None

        df = df[required].copy()

        for column in required:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

        df = df.dropna()

        if len(df) < MIN_DATA:
            return None

        return df

    except Exception as exc:
        logging.warning(
            "%s: Data download failed: %s",
            symbol,
            exc,
        )
        return None


def get_market_mode():
    """
    Classify the Nifty market using completed daily candles.

    BULLISH:
        Nifty close > EMA20 > EMA50

    BEARISH:
        Nifty close < EMA20 < EMA50

    Otherwise:
        SIDEWAYS / NO TRADE
    """

    df = download_daily_data("^NSEI")

    if df is None or len(df) < MIN_DATA:
        return "NO_TRADE", None

    close = df["Close"]

    ema20 = close.ewm(
        span=20,
        adjust=False,
    ).mean()

    ema50 = close.ewm(
        span=50,
        adjust=False,
    ).mean()

    # Use the last completed daily candle.
    index = -2

    price = float(close.iloc[index])
    fast = float(ema20.iloc[index])
    slow = float(ema50.iloc[index])

    if price > fast > slow:
        return "BULLISH", price

    if price < fast < slow:
        return "BEARISH", price

    return "NO_TRADE", price


def scan_stocks(symbols, market_mode):
    results = []

    total = len(symbols)

    for number, symbol in enumerate(
        symbols,
        start=1,
    ):
        logging.info(
            "Scanning %s/%s: %s",
            number,
            total,
            symbol,
        )

        df = download_daily_data(symbol)

        if df is None:
            continue

        try:
            result = analyze_stock(
                df,
                market_mode=market_mode,
            )

            if result is None:
                continue

            record = {
                "symbol": symbol,
                "time": now_ist(),
                "market_mode": market_mode,
                **result,
            }

            results.append(record)

        except Exception as exc:
            logging.warning(
                "%s: Strategy error: %s",
                symbol,
                exc,
            )

        # Avoid making requests too rapidly.
        time.sleep(0.15)

    return results


def save_signals(data):
    with open(
        SIGNALS_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )


def format_report(
    market_mode,
    nifty_price,
    results,
    scanned,
):
    lines = [
        f"📊 {VERSION}",
        f"🕒 {now_ist()}",
        "",
        f"Market regime: {market_mode}",
        (
            f"Nifty reference: ₹{nifty_price:.2f}"
            if nifty_price is not None
            else "Nifty reference: unavailable"
        ),
        f"Stocks checked: {scanned}",
        f"Candidates: {len(results)}",
        "",
    ]

    if market_mode == "NO_TRADE":
        lines.extend([
            "🛡️ NO TRADE",
            "Market regime is sideways or uncertain.",
            "No new paper-trading entries generated.",
        ])

        return "\n".join(lines)

    if not results:
        lines.extend([
            "No stocks met all V11 filters.",
            "No trade is a valid result.",
        ])

        return "\n".join(lines)

    for number, item in enumerate(
        results[:TOP_N],
        start=1,
    ):
        lines.extend([
            f"{number}. {item['symbol']}",
            f"Setup: {item['mode']}",
        ])

        if item["mode"] == "SWING_BUY":
            lines.extend([
                f"Entry reference: ₹{item['entry']:.2f}",
                f"Stop loss: ₹{item['stop_loss']:.2f}",
                f"Target: ₹{item['target']:.2f}",
                f"Risk/share: ₹{item['risk_per_share']:.2f}",
                f"Reward/risk: {item['reward_risk']:.1f}",
                f"RSI: {item['rsi']:.1f}",
                f"Relative volume: {item['relative_volume']:.2f}x",
                "Status: PAPER ONLY",
            ])

        elif item["mode"] == "INTRADAY_SHORT_CANDIDATE":
            lines.extend([
                f"Reference price: ₹{item['reference_price']:.2f}",
                "Status: WAIT FOR INTRADAY CONFIRMATION",
                (
                    "Daily setup only; no short entry "
                    "is authorized by this signal."
                ),
            ])

        lines.append("")

    lines.extend([
        "⚠️ Research signals only.",
        "No broker orders are placed.",
    ])

    return "\n".join(lines)


def main():
    logging.info("%s starting.", VERSION)

    try:
        symbols = load_stock_symbols()

    except Exception as exc:
        logging.error(
            "Cannot load stock symbols: %s",
            exc,
        )

        send_telegram(
            f"⚠️ {VERSION}\n"
            f"Scanner stopped: stock list unavailable."
        )

        raise

    logging.info(
        "Loaded %s stock symbols.",
        len(symbols),
    )

    market_mode, nifty_price = get_market_mode()

    logging.info(
        "Market mode: %s",
        market_mode,
    )

    results = []

    # Fail closed if market classification is unavailable.
    if market_mode in ("BULLISH", "BEARISH"):
        results = scan_stocks(
            symbols,
            market_mode,
        )

    # Rank the strongest candidates first.
    if market_mode == "BULLISH":
        results.sort(
            key=lambda item: (
                item.get("relative_volume", 0),
                item.get("rsi", 0),
            ),
            reverse=True,
        )

    elif market_mode == "BEARISH":
        results.sort(
            key=lambda item: (
                item.get("relative_volume", 0),
            ),
            reverse=True,
        )

    results = results[:TOP_N]

    output = {
        "version": VERSION,
        "generated_at": now_ist(),
        "market_mode": market_mode,
        "nifty_reference": nifty_price,
        "stocks_loaded": len(symbols),
        "signals": results,
        "paper_only": True,
    }

    save_signals(output)

    report = format_report(
        market_mode,
        nifty_price,
        results,
        len(symbols),
    )

    print("\n" + report)

    telegram_sent = send_telegram(report)

    logging.info(
        "Telegram delivery: %s",
        "success" if telegram_sent else "not delivered",
    )

    logging.info(
        "Saved %s candidates to %s.",
        len(results),
        SIGNALS_FILE,
    )


if __name__ == "__main__":
    main()