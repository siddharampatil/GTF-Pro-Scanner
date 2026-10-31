"""
GTF PRO SCANNER V11.1 — single-file paper-trading system
NSE cash equities only. No broker orders are placed.

BULLISH  -> Daily swing BUY setups
BEARISH  -> Intraday cash-equity SHORT setups
SIDEWAYS -> No new entries
"""

import os
import json
import time
import uuid
import logging
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
import requests
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

IST = ZoneInfo("Asia/Kolkata")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

TELEGRAM_URL = (
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if BOT_TOKEN else ""
)

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"
SCAN_STATE_FILE = "scan_state.json"

STOCKS = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
    "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS",
    "LT.NS", "BHARTIARTL.NS", "ITC.NS", "HINDUNILVR.NS",
    "BAJFINANCE.NS", "MARUTI.NS", "TATAMOTORS.NS", "M&M.NS",
    "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "NTPC.NS",
    "POWERGRID.NS", "ONGC.NS", "COALINDIA.NS", "TATASTEEL.NS",
    "JSWSTEEL.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
    "ADANIPORTS.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS",
    "NESTLEIND.NS", "GRASIM.NS", "CIPLA.NS", "DRREDDY.NS",
    "DIVISLAB.NS", "APOLLOHOSP.NS", "EICHERMOT.NS",
    "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "INDUSINDBK.NS",
    "FEDERALBNK.NS", "BANKBARODA.NS", "PNB.NS",
    "IDFCFIRSTB.NS", "DLF.NS", "BEL.NS", "HAL.NS",
    "TRENT.NS", "ZOMATO.NS"
]

MAX_NEW_SIGNALS = 5

MIN_DAILY_ROWS = 220
MIN_SCORE = 80
MIN_ADX = 22
MIN_RVOL = 1.30
MIN_RSI = 52
MAX_RSI = 68

MIN_RR_SWING = 2.0
MIN_RR_SHORT = 1.5

MAX_ENTRY_AGE_MINUTES = 90
MAX_SWING_ENTRY_AGE_DAYS = 5

SQUARE_OFF_TIME = dtime(15, 20)
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)

DIAGNOSTICS = {
    "daily_download_ok": 0,
    "intraday_download_ok": 0,
    "download_fail": 0
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


def now_ist():
    return datetime.now(IST)


def stamp():
    return now_ist().isoformat(timespec="seconds")


def load_json(path):
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(
            f"{path} must contain a JSON list. "
            "Refusing to overwrite it."
        )

    return data


def save_json(path, data):
    tmp = path + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    os.replace(tmp, path)


def telegram(message):
    if not TELEGRAM_URL or not CHAT_ID:
        logging.info("Telegram not configured.")
        return

    try:
        response = requests.post(
            TELEGRAM_URL,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=15
        )
        response.raise_for_status()

    except Exception as exc:
        logging.warning(
            "Telegram notification failed: %s", exc
        )


def clean_yf_frame(df):
    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [str(c).title() for c in df.columns]

    required = [
        "Open", "High", "Low", "Close", "Volume"
    ]

    if not all(c in df.columns for c in required):
        return None

    df = df[required].copy()

    for c in required:
        df[c] = pd.to_numeric(
            df[c], errors="coerce"
        )

    df = df.dropna()

    return df if not df.empty else None
def download_daily(symbol):
    try:
        df = yf.download(
            symbol, period="2y", interval="1d",
            auto_adjust=True, progress=False,
            threads=False, timeout=20
        )
        df = clean_yf_frame(df)

        if df is None or len(df) < MIN_DAILY_ROWS:
            DIAGNOSTICS["download_fail"] += 1
            return None

        DIAGNOSTICS["daily_download_ok"] += 1
        return df

    except Exception as exc:
        DIAGNOSTICS["download_fail"] += 1
        logging.warning(
            "Daily download failed for %s: %s", symbol, exc
        )
        return None


def download_intraday(symbol):
    try:
        df = yf.download(
            symbol, period="5d", interval="5m",
            auto_adjust=True, progress=False,
            threads=False, timeout=20
        )
        df = clean_yf_frame(df)

        if df is None or len(df) < 60:
            DIAGNOSTICS["download_fail"] += 1
            return None

        # Remove the currently forming 5-minute candle.
        idx = pd.DatetimeIndex(df.index)

        if idx.tz is None:
            idx = idx.tz_localize("UTC")

        idx = idx.tz_convert(IST)
        df.index = idx

        current = now_ist()

        if len(df) and df.index[-1].date() == current.date():
            candle_end = (
                df.index[-1].to_pydatetime()
                + timedelta(minutes=5)
            )

            if candle_end > current:
                df = df.iloc[:-1]

        if df.empty:
            DIAGNOSTICS["download_fail"] += 1
            return None

        age = (
            now_ist() - df.index[-1].to_pydatetime()
        ).total_seconds() / 60

        if age < -5 or age > 20:
            DIAGNOSTICS["download_fail"] += 1
            return None

        DIAGNOSTICS["intraday_download_ok"] += 1
        return df

    except Exception as exc:
        DIAGNOSTICS["download_fail"] += 1
        logging.warning(
            "Intraday download failed for %s: %s", symbol, exc
        )
        return None


def market_regime():
    df = download_daily("^NSEI")

    if df is None:
        return "SIDEWAYS", None, {}

    close = df["Close"]

    ema20 = EMAIndicator(
        close, window=20
    ).ema_indicator()

    ema50 = EMAIndicator(
        close, window=50
    ).ema_indicator()

    adx_obj = ADXIndicator(
        df["High"], df["Low"], close, window=14
    )

    pdi = adx_obj.adx_pos()
    mdi = adx_obj.adx_neg()
    adx_value = adx_obj.adx().iloc[-1]

    c = close.iloc[-1]
    e20 = ema20.iloc[-1]
    e50 = ema50.iloc[-1]

    details = {
        "ema20": round(float(e20), 2),
        "ema50": round(float(e50), 2),
        "adx": round(float(adx_value), 1),
        "plus_di": round(float(pdi.iloc[-1]), 1),
        "minus_di": round(float(mdi.iloc[-1]), 1)
    }

    if c > e20 > e50 and pdi.iloc[-1] > mdi.iloc[-1]:
        return "BULLISH", float(c), details

    if c < e20 < e50 and mdi.iloc[-1] > pdi.iloc[-1]:
        return "BEARISH", float(c), details

    return "SIDEWAYS", float(c), details


def swing_candidate(symbol):
    df = download_daily(symbol)

    if df is None:
        return None

    c = df["Close"]

    ema20 = EMAIndicator(c, 20).ema_indicator()
    ema50 = EMAIndicator(c, 50).ema_indicator()
    ema200 = EMAIndicator(c, 200).ema_indicator()

    rsi = RSIIndicator(c, 14).rsi()
    macd = MACD(c)

    adx_obj = ADXIndicator(
        df["High"], df["Low"], c, 14
    )

    adx = adx_obj.adx()
    pdi = adx_obj.adx_pos()
    mdi = adx_obj.adx_neg()

    atr = AverageTrueRange(
        df["High"], df["Low"], c, 14
    ).average_true_range()

    avg_vol = df["Volume"].rolling(20).mean()

    i = len(df) - 1

    vals = [
        ema20.iloc[i], ema50.iloc[i], ema200.iloc[i],
        rsi.iloc[i], adx.iloc[i], pdi.iloc[i],
        mdi.iloc[i], atr.iloc[i], avg_vol.iloc[i]
    ]

    if any(pd.isna(x) for x in vals):
        return None

    price = float(c.iloc[i])
    av = float(atr.iloc[i])

    rvol = (
        float(df["Volume"].iloc[i] / avg_vol.iloc[i])
        if avg_vol.iloc[i] else 0
    )

    extension = (
        (price - float(ema20.iloc[i])) / av
        if av else 99
    )

    prior_high = float(
        df["High"].iloc[-21:-1].max()
    )

    checks = [
        price > ema20.iloc[i] > ema50.iloc[i] > ema200.iloc[i],
        0 <= extension <= 2.0,
        MIN_RSI <= rsi.iloc[i] <= MAX_RSI,
        adx.iloc[i] >= MIN_ADX and pdi.iloc[i] > mdi.iloc[i],
        rvol >= MIN_RVOL,
        macd.macd().iloc[i] > macd.macd_signal().iloc[i],
        price > prior_high
    ]

    if not all(checks):
        return None

    entry = float(
        df["High"].iloc[i] + 0.05 * av
    )

    recent_low = float(
        df["Low"].iloc[-10:].min()
    )

    stop = max(
        recent_low, entry - 1.5 * av
    )

    risk = entry - stop

    if risk <= 0 or risk > 2 * av:
        return None

    target = entry + MIN_RR_SWING * risk
def short_candidate(symbol):
    df = download_intraday(symbol)

    if df is None or len(df) < 60:
        return None

    c = df["Close"]

    ema9 = EMAIndicator(c, 9).ema_indicator()
    ema20 = EMAIndicator(c, 20).ema_indicator()

    rsi = RSIIndicator(c, 14).rsi()

    adx_obj = ADXIndicator(
        df["High"], df["Low"], c, 14
    )

    adx = adx_obj.adx()
    pdi = adx_obj.adx_pos()
    mdi = adx_obj.adx_neg()

    atr = AverageTrueRange(
        df["High"], df["Low"], c, 14
    ).average_true_range()

    avg_vol = df["Volume"].rolling(20).mean()

    i = len(df) - 1

    vals = [
        ema9.iloc[i], ema20.iloc[i], rsi.iloc[i],
        adx.iloc[i], pdi.iloc[i], mdi.iloc[i],
        atr.iloc[i], avg_vol.iloc[i]
    ]

    if any(pd.isna(x) for x in vals):
        return None

    price = float(c.iloc[i])
    av = float(atr.iloc[i])

    rvol = (
        float(df["Volume"].iloc[i] / avg_vol.iloc[i])
        if avg_vol.iloc[i] else 0
    )

    # Bearish intraday momentum and volume confirmation.
    checks = [
        price < ema9.iloc[i] < ema20.iloc[i],
        rsi.iloc[i] < 48,
        adx.iloc[i] >= MIN_ADX,
        mdi.iloc[i] > pdi.iloc[i],
        rvol >= MIN_RVOL
    ]

    if not all(checks) or av <= 0:
        return None

    entry = price
    stop = entry + 1.2 * av
    target = entry - MIN_RR_SHORT * (stop - entry)

    return {
        "symbol": symbol,
        "strategy": "V11_INTRADAY",
        "direction": "SHORT",
        "entry_trigger": round(entry, 2),
        "stop_loss": round(stop, 2),
        "target": round(target, 2),
        "score": 100,
        "rvol": round(rvol, 2),
        "rsi": round(float(rsi.iloc[i]), 1),
        "adx": round(float(adx.iloc[i]), 1),
        "reward_risk": MIN_RR_SHORT,
        "signal_candle": str(df.index[i])
    }


def active_symbols(signals):
    return {
        s.get("symbol")
        for s in signals
        if s.get("status") in ("WAITING", "OPEN")
    }


def create_record(candidate):
    record = dict(candidate)

    record.update({
        "id": str(uuid.uuid4())[:8],
        "status": "WAITING",
        "created_at": stamp(),
        "entry_time": None,
        "exit_time": None,
        "actual_entry": None,
        "actual_exit": None,
        "exit_reason": None,
        "pnl_percent": None
    })

    return record


def monitor_one(signal, history):
    symbol = signal.get("symbol")

    if not symbol:
        return

    df = download_intraday(symbol)

    if df is None or df.empty:
        return

    last = df.iloc[-1]
    price = float(last["Close"])
    high = float(last["High"])
    low = float(last["Low"])

    direction = signal.get("direction")
    entry = float(signal["entry_trigger"])
    stop = float(signal["stop_loss"])
    target = float(signal["target"])

    if signal["status"] == "WAITING":
        created = datetime.fromisoformat(
            signal["created_at"]
        )

        age = now_ist() - created

        if direction == "BUY":
            expired = age > timedelta(
                days=MAX_SWING_ENTRY_AGE_DAYS
            )
            triggered = high >= entry

        else:
            expired = age > timedelta(
                minutes=MAX_ENTRY_AGE_MINUTES
            )
            triggered = low <= entry

        if expired:
            signal["status"] = "EXPIRED"
            signal["exit_time"] = stamp()
            signal["exit_reason"] = "ENTRY_NOT_TRIGGERED"
            return

        if not triggered:
            return

        signal["status"] = "OPEN"
        signal["entry_time"] = stamp()
        signal["actual_entry"] = entry

        telegram(
            f"🟢 PAPER ENTRY\n"
            f"{symbol} | {direction}\n"
            f"Entry: {entry:.2f}\n"
            f"SL: {stop:.2f} | Target: {target:.2f}"
        )

    if signal["status"] != "OPEN":
        return

    entry = float(signal["actual_entry"])

    # Use conservative stop-first handling if both levels
    # appear inside the same candle.
    if direction == "BUY":
        if low <= stop:
            close_signal(
                signal, history,
                stop if price >= stop else price,
                "STOP_LOSS"
            )
        elif high >= target:
            close_signal(
                signal, history,
                target if price <= target else price,
                "TARGET"
            )

    elif direction == "SHORT":
        if high >= stop:
            close_signal(
                signal, history,
                stop if price <= stop else price,
                "STOP_LOSS"
            )
        elif low <= target:
            close_signal(
                signal, history,
                target if price >= target else price,
                "TARGET"
            )
def close_signal(signal, history, exit_price, reason):
    entry = float(signal["actual_entry"])
    exit_price = float(exit_price)

    if signal["direction"] == "BUY":
        pnl = ((exit_price - entry) / entry) * 100
    else:
        pnl = ((entry - exit_price) / entry) * 100

    signal["status"] = "CLOSED"
    signal["actual_exit"] = round(exit_price, 2)
    signal["exit_time"] = stamp()
    signal["exit_reason"] = reason
    signal["pnl_percent"] = round(pnl, 2)

    history.append({
        "id": signal["id"],
        "symbol": signal["symbol"],
        "direction": signal["direction"],
        "entry": round(entry, 2),
        "exit": round(exit_price, 2),
        "pnl_percent": round(pnl, 2),
        "reason": reason,
        "closed_at": stamp()
    })

    emoji = "✅" if pnl > 0 else "❌"

    telegram(
        f"{emoji} PAPER TRADE CLOSED\n"
        f"{signal['symbol']} | {signal['direction']}\n"
        f"Entry: {entry:.2f}\n"
        f"Exit: {exit_price:.2f}\n"
        f"Result: {pnl:+.2f}%\n"
        f"Reason: {reason}"
    )


def main():
    now = now_ist()

    signals = load_json(SIGNALS_FILE)
    history = load_json(HISTORY_FILE)

    # Monitor existing paper trades on every workflow run.
    for signal in signals:
        if signal.get("status") in ("WAITING", "OPEN"):
            try:
                monitor_one(signal, history)
            except Exception as exc:
                logging.exception(
                    "Monitor error for %s: %s",
                    signal.get("symbol"), exc
                )

    save_json(SIGNALS_FILE, signals)
    save_json(HISTORY_FILE, history)

    # Do not create new signals outside market hours or on weekends.
    if now.weekday() >= 5 or not (
        MARKET_OPEN <= now.time() <= MARKET_CLOSE
    ):
        logging.info("Outside NSE market hours. Monitoring completed.")
        return

    # Avoid repeating the same scan within a half-hour slot.
    slot = now.strftime("%Y-%m-%d-%H-%M")
    slot = slot[:-1] + "0"

    state = load_json(SCAN_STATE_FILE)
    if not isinstance(state, list):
        state = []

    if slot in state:
        logging.info("This half-hour scan slot was already processed.")
        return

    regime, nifty_price, details = market_regime()

    logging.info(
        "Market regime: %s | Nifty: %s | Details: %s",
        regime, nifty_price, details
    )

    occupied = active_symbols(signals)
    candidates = []

    if regime == "BULLISH":
        scan_function = swing_candidate
    elif regime == "BEARISH":
        scan_function = short_candidate
    else:
        scan_function = None

    if scan_function:
        for symbol in STOCKS:
            if symbol in occupied:
                continue

            try:
                candidate = scan_function(symbol)

                if candidate:
                    candidates.append(candidate)

            except Exception as exc:
                logging.warning(
                    "Scan error for %s: %s", symbol, exc
                )

    candidates.sort(
        key=lambda x: (
            x.get("score", 0),
            x.get("rvol", 0),
            x.get("adx", 0)
        ),
        reverse=True
    )

    selected = candidates[:MAX_NEW_SIGNALS]

    for candidate in selected:
        signals.append(create_record(candidate))

    save_json(SIGNALS_FILE, signals)

    state.append(slot)
    state = state[-100:]
    save_json(SCAN_STATE_FILE, state)

    waiting = sum(
        1 for s in signals if s.get("status") == "WAITING"
    )
    opened = sum(
        1 for s in signals if s.get("status") == "OPEN"
    )

    message = (
        "📊 GTF PRO SCANNER V11.1\n"
        f"Time: {now.strftime('%d-%m-%Y %H:%M')} IST\n"
        f"Market regime: {regime}\n"
        f"Nifty reference: {nifty_price}\n"
        f"EMA/ADX details: {details}\n"
        f"Daily downloads OK: {DIAGNOSTICS['daily_download_ok']}\n"
        f"Intraday downloads OK: {DIAGNOSTICS['intraday_download_ok']}\n"
        f"Download failures: {DIAGNOSTICS['download_fail']}\n"
        f"Stocks in universe: {len(STOCKS)}\n"
        f"Qualified candidates: {len(candidates)}\n"
        f"New paper signals: {len(selected)}\n"
        f"Open: {opened} | Waiting: {waiting}\n"
        "Paper trading only — no broker orders."
    )

    logging.info(message)
    telegram(message)


if __name__ == "__main__":
    main()

    return {
        "symbol": symbol,
        "strategy": "V11_SWING",
        "direction": "BUY",
        "entry_trigger": round(entry, 2),
        "stop_loss": round(stop, 2),
        "target": round(target, 2),
        "score": 100,
        "rvol": round(rvol, 2),
        "rsi": round(float(rsi.iloc[i]), 1),
        "adx": round(float(adx.iloc[i]), 1),
        "reward_risk": MIN_RR_SWING,
        "signal_candle": str(df.index[i].date())
    }