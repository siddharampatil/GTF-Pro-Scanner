
"""
GTF PRO V12.0
NSE INTRADAY PAPER TRADING SCANNER
BUY + SHORT | 15-minute trend | 5-minute entry
No live broker orders.
"""

import os
import json
import logging
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
import requests

from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

IST = ZoneInfo("Asia/Kolkata")

# =============== CONFIGURATION ===============

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

TELEGRAM_URL = (
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if BOT_TOKEN else ""
)

CAPITAL = 25000.0
RISK_PER_TRADE = 0.005
MAX_DAILY_LOSS = 0.015
MAX_CAPITAL_USE = 0.90

MAX_DAILY_SIGNALS = 3
MAX_ACTIVE_TRADES = 2

MIN_REWARD_RISK = 2.0

MARKET_OPEN = dtime(9, 15)
LAST_ENTRY_TIME = dtime(14, 45)
SQUARE_OFF_TIME = dtime(15, 15)
MARKET_CLOSE = dtime(15, 30)

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"
STATE_FILE = "scanner_state.json"

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


# =============== TIME HELPERS ===============

def now_ist():
    return datetime.now(IST)


def timestamp():
    return now_ist().isoformat(timespec="seconds")


# =============== JSON FILE HELPERS ===============

def load_json(path, default):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    return data


def save_json(path, data):
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)

    os.replace(temp_path, path)


# =============== TELEGRAM ===============

def telegram(message):
    if not TELEGRAM_URL or not CHAT_ID:
        logging.warning("Telegram credentials missing.")
        return False

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
        return True

    except requests.RequestException as exc:
        logging.error("Telegram error: %s", exc)
        return False


# =============== DATA CLEANING ===============

def clean_frame(df):
    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [str(col).title() for col in df.columns]

    required = ["Open", "High", "Low", "Close", "Volume"]

    if not all(col in df.columns for col in required):
        return None

    df = df[required].copy()

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna()
    df = df.sort_index()

    return df if not df.empty else None

# =============== MARKET DATA DOWNLOAD ===============

def download_intraday(symbol):
    try:
        raw = yf.download(
            symbol,
            period="5d",
            interval="5m",
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=25
        )

        df = clean_frame(raw)

        if df is None:
            return None

        index = pd.DatetimeIndex(df.index)

        if index.tz is None:
            index = index.tz_localize("UTC")

        df.index = index.tz_convert(IST)

        # Remove the currently forming candle.
        current = now_ist()

        if not df.empty:
            candle_end = (
                df.index[-1].to_pydatetime()
                + timedelta(minutes=5)
            )

            if candle_end > current:
                df = df.iloc[:-1]

        if df.empty or len(df) < 30:
            return None

        # Reject stale data.
        candle_end = (
            df.index[-1].to_pydatetime()
            + timedelta(minutes=5)
        )

        age = (
            current - candle_end
        ).total_seconds() / 60

        if age > 20 or age < -2:
            return None

        return df

    except Exception as exc:
        logging.warning(
            "Download failed for %s: %s",
            symbol, exc
        )
        return None


# =============== 15-MINUTE CANDLES ===============

def make_15m(df):
    if df is None or df.empty:
        return None

    result = df.resample(
        "15min",
        label="right",
        closed="right"
    ).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    })

    result = result.dropna()

    # Keep only completed 15-minute candles.
    current = now_ist()

    if not result.empty:
        last_end = result.index[-1].to_pydatetime()

        if last_end > current:
            result = result.iloc[:-1]

    return result if not result.empty else None


# =============== VWAP ===============

def add_vwap(df):
    data = df.copy()

    typical_price = (
        data["High"] + data["Low"] + data["Close"]
    ) / 3

    dates = pd.Series(
        data.index.date,
        index=data.index
    )

    cumulative_pv = (
        typical_price * data["Volume"]
    ).groupby(dates).cumsum()

    cumulative_volume = (
        data["Volume"].groupby(dates).cumsum()
    )

    data["VWAP"] = (
        cumulative_pv / cumulative_volume.replace(0, float("nan"))
    )

    return data


# =============== MARKET DIRECTION ===============

def market_direction():
    df = download_intraday("^NSEI")

    if df is None:
        return "NO_TRADE", None, "Nifty data unavailable"

    candles = make_15m(df)

    if candles is None or len(candles) < 25:
        return "NO_TRADE", None, "Insufficient 15-minute Nifty data"

    close = candles["Close"]

    ema9 = EMAIndicator(
        close, window=9
    ).ema_indicator()

    ema20 = EMAIndicator(
        close, window=20
    ).ema_indicator()

    adx_obj = ADXIndicator(
        candles["High"],
        candles["Low"],
        close,
        window=14
    )

    adx = adx_obj.adx()
    plus_di = adx_obj.adx_pos()
    minus_di = adx_obj.adx_neg()

    values = [
        ema9.iloc[-1],
        ema20.iloc[-1],
        adx.iloc[-1],
        plus_di.iloc[-1],
        minus_di.iloc[-1]
    ]

    if any(pd.isna(value) for value in values):
        return "NO_TRADE", None, "Indicator calculation unavailable"

    price = float(close.iloc[-1])
    strength = float(adx.iloc[-1])

    details = (
        f"EMA9: {ema9.iloc[-1]:.2f} | "
        f"EMA20: {ema20.iloc[-1]:.2f} | "
        f"ADX: {strength:.1f}"
    )

    # Avoid weak or unclear market conditions.
    if strength < 20:
        return "NO_TRADE", price, details

    if (
        price > ema9.iloc[-1] > ema20.iloc[-1]
        and plus_di.iloc[-1] > minus_di.iloc[-1]
    ):
        return "BULLISH", price, details

    if (
        price < ema9.iloc[-1] < ema20.iloc[-1]
        and minus_di.iloc[-1] > plus_di.iloc[-1]
    ):
        return "BEARISH", price, details

    return "NO_TRADE", price, details


# =============== STOCK INDICATORS ===============

def calculate_indicators(df):
    if df is None or len(df) < 30:
        return None

    data = add_vwap(df)

    data["EMA9"] = EMAIndicator(
        data["Close"], window=9
    ).ema_indicator()

    data["EMA20"] = EMAIndicator(
        data["Close"], window=20
    ).ema_indicator()

    data["RSI"] = RSIIndicator(
        data["Close"], window=14
    ).rsi()

    adx_obj = ADXIndicator(
        data["High"],
        data["Low"],
        data["Close"],
        window=14
    )

    data["ADX"] = adx_obj.adx()
    data["PLUS_DI"] = adx_obj.adx_pos()
    data["MINUS_DI"] = adx_obj.adx_neg()

    data["ATR"] = AverageTrueRange(
        data["High"],
        data["Low"],
        data["Close"],
        window=14
    ).average_true_range()

    data["AVG_VOLUME"] = (
        data["Volume"].rolling(20).mean()
    )

    return data

# =============== POSITION SIZING ===============

def calculate_quantity(entry, stop):
    risk_per_share = abs(entry - stop)

    if risk_per_share <= 0:
        return 0

    risk_amount = CAPITAL * RISK_PER_TRADE

    quantity_by_risk = int(
        risk_amount / risk_per_share
    )

    quantity_by_capital = int(
        CAPITAL * MAX_CAPITAL_USE / entry
    )

    return max(
        0,
        min(quantity_by_risk, quantity_by_capital)
    )


# =============== SIGNAL VALIDATION ===============

def build_candidate(symbol, market, raw_df):
    data = calculate_indicators(raw_df)

    if data is None or len(data) < 30:
        return None, "insufficient indicator data"

    row = data.iloc[-1]
    previous = data.iloc[-2]

    required = [
        "Close", "High", "Low", "VWAP",
        "EMA9", "EMA20", "RSI", "ADX",
        "PLUS_DI", "MINUS_DI", "ATR",
        "AVG_VOLUME"
    ]

    if any(pd.isna(row[x]) for x in required):
        return None, "indicator unavailable"

    price = float(row["Close"])
    vwap = float(row["VWAP"])
    atr = float(row["ATR"])
    average_volume = float(row["AVG_VOLUME"])

    if price <= 0 or atr <= 0 or average_volume <= 0:
        return None, "invalid price or volatility"

    rvol = float(row["Volume"]) / average_volume

    if rvol < 1.30:
        return None, "volume confirmation missing"

    if float(row["ADX"]) < 20:
        return None, "weak intraday trend"

    if market == "BULLISH":
        direction = "BUY"

        checks = [
            price > vwap,
            row["EMA9"] > row["EMA20"],
            row["PLUS_DI"] > row["MINUS_DI"],
            52 <= row["RSI"] <= 70,
            price > previous["High"]
        ]

        if not all(checks):
            return None, "BUY confirmation missing"

        entry = price
        stop = min(
            float(row["Low"]) - 0.05 * atr,
            entry - 1.2 * atr
        )

        risk = entry - stop
        target = entry + MIN_REWARD_RISK * risk

    elif market == "BEARISH":
        direction = "SHORT"

        checks = [
            price < vwap,
            row["EMA9"] < row["EMA20"],
            row["MINUS_DI"] > row["PLUS_DI"],
            30 <= row["RSI"] <= 48,
            price < previous["Low"]
        ]

        if not all(checks):
            return None, "SHORT confirmation missing"

        entry = price
        stop = max(
            float(row["High"]) + 0.05 * atr,
            entry + 1.2 * atr
        )

        risk = stop - entry
        target = entry - MIN_REWARD_RISK * risk

    else:
        return None, "market direction unclear"

    if risk <= 0:
        return None, "invalid stop-loss"

    quantity = calculate_quantity(entry, stop)

    if quantity < 1:
        return None, "capital or risk limit prevents trade"

    capital_required = quantity * entry
    planned_risk = quantity * risk

    if capital_required > CAPITAL * MAX_CAPITAL_USE:
        return None, "capital limit exceeded"

    if planned_risk > CAPITAL * RISK_PER_TRADE + 0.01:
        return None, "risk limit exceeded"

    return {
        "symbol": symbol,
        "direction": direction,
        "entry": round(entry, 2),
        "stop_loss": round(stop, 2),
        "target": round(target, 2),
        "quantity": quantity,
        "capital_required": round(capital_required, 2),
        "planned_risk": round(planned_risk, 2),
        "reward_risk": MIN_REWARD_RISK,
        "rvol": round(rvol, 2),
        "rsi": round(float(row["RSI"]), 1),
        "adx": round(float(row["ADX"]), 1),
        "vwap": round(vwap, 2),
        "created_at": timestamp(),
        "status": "OPEN"
    }, "qualified"


# =============== ACTIVE TRADE HELPERS ===============

def active_trades(signals):
    return [
        trade for trade in signals
        if trade.get("status") == "OPEN"
    ]


def already_traded_today(signals, symbol, today):
    for trade in signals:
        if trade.get("symbol") != symbol:
            continue

        created = trade.get("created_at", "")

        if created[:10] == today:
            return True

    return False


# =============== TELEGRAM SIGNAL FORMAT ===============

def format_signal(signal, market, nifty):
    direction = signal["direction"]

    emoji = "🟢" if direction == "BUY" else "🔴"

    return (
        f"{emoji} GTF PRO V12.0 — PAPER {direction}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Stock: {signal['symbol'].replace('.NS', '')}\n"
        f"Market: {market}\n"
        f"Nifty: {nifty:.2f}\n"
        f"Entry: ₹{signal['entry']:.2f}\n"
        f"Stop-loss: ₹{signal['stop_loss']:.2f}\n"
        f"Target: ₹{signal['target']:.2f}\n"
        f"Quantity: {signal['quantity']}\n"
        f"Capital: ₹{signal['capital_required']:.2f}\n"
        f"Planned risk: ₹{signal['planned_risk']:.2f}\n"
        f"Reward/Risk: 1:{signal['reward_risk']:.1f}\n"
        f"VWAP: ₹{signal['vwap']:.2f}\n"
        f"RSI: {signal['rsi']}\n"
        f"ADX: {signal['adx']}\n"
        f"Relative volume: {signal['rvol']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Paper trading only. No broker order."
    )

# =============== DAILY PERFORMANCE ===============

def daily_pnl(history, today):
    total = 0.0

    for trade in history:
        if trade.get("closed_at", "")[:10] == today:
            total += float(trade.get("pnl_amount", 0))

    return round(total, 2)


# =============== CLOSE PAPER TRADE ===============

def close_trade(signal, history, exit_price, reason):
    entry = float(signal["entry"])
    quantity = int(signal["quantity"])
    exit_price = float(exit_price)

    if signal["direction"] == "BUY":
        pnl = (exit_price - entry) * quantity
    else:
        pnl = (entry - exit_price) * quantity

    signal["status"] = "CLOSED"
    signal["exit_price"] = round(exit_price, 2)
    signal["exit_reason"] = reason
    signal["closed_at"] = timestamp()
    signal["pnl_amount"] = round(pnl, 2)

    history.append({
        "symbol": signal["symbol"],
        "direction": signal["direction"],
        "entry": entry,
        "exit": round(exit_price, 2),
        "quantity": quantity,
        "pnl_amount": round(pnl, 2),
        "reason": reason,
        "closed_at": signal["closed_at"]
    })

    telegram(
        f"{'✅' if pnl >= 0 else '❌'} "
        f"GTF PRO V12.0 — PAPER TRADE CLOSED\n"
        f"Stock: {signal['symbol']}\n"
        f"Direction: {signal['direction']}\n"
        f"Entry: ₹{entry:.2f}\n"
        f"Exit: ₹{exit_price:.2f}\n"
        f"Quantity: {quantity}\n"
        f"P/L: ₹{pnl:+.2f}\n"
        f"Reason: {reason}"
    )


# =============== TRADE MONITOR ===============

def monitor_trades(signals, history):
    now = now_ist()

    for signal in signals:
        if signal.get("status") != "OPEN":
            continue

        symbol = signal["symbol"]
        df = download_intraday(symbol)

        if df is None or df.empty:
            continue

        candle = df.iloc[-1]

        high = float(candle["High"])
        low = float(candle["Low"])
        close = float(candle["Close"])

        entry = float(signal["entry"])
        stop = float(signal["stop_loss"])
        target = float(signal["target"])

        # Square off before market close.
        if now.time() >= SQUARE_OFF_TIME:
            close_trade(
                signal, history, close, "TIME_SQUARE_OFF"
            )
            continue

        if signal["direction"] == "BUY":
            # Conservative assumption: stop first if both
            # stop and target occur in the same candle.
            if low <= stop:
                close_trade(
                    signal, history, stop, "STOP_LOSS"
                )
            elif high >= target:
                close_trade(
                    signal, history, target, "TARGET"
                )

        else:
            if high >= stop:
                close_trade(
                    signal, history, stop, "STOP_LOSS"
                )
            elif low <= target:
                close_trade(
                    signal, history, target, "TARGET"
                )


# =============== MAIN SCANNER ===============

def main():
    now = now_ist()
    today = now.strftime("%Y-%m-%d")

    signals = load_json(SIGNALS_FILE, [])
    history = load_json(HISTORY_FILE, [])
    state = load_json(STATE_FILE, {})

    if not isinstance(signals, list):
        raise ValueError("signals.json must contain a list")

    if not isinstance(history, list):
        raise ValueError("trade_history.json must contain a list")

    if not isinstance(state, dict):
        raise ValueError("scanner_state.json must contain an object")

    # Monitor open paper trades.
    monitor_trades(signals, history)

    save_json(SIGNALS_FILE, signals)
    save_json(HISTORY_FILE, history)

    # Do not create signals outside market hours.
    if now.weekday() >= 5 or not (
        MARKET_OPEN <= now.time() <= LAST_ENTRY_TIME
    ):
        logging.info("Outside entry hours.")
        return

    # Prevent repeated scans in the same five-minute slot.
    slot = now.strftime("%Y-%m-%d-%H-%M")
    slot = slot[:-1] + "0"

    if state.get("last_slot") == slot:
        logging.info("Scan slot already processed.")
        return

    # Save slot before scanning to avoid duplicate alerts
    # if the workflow is triggered more than once.
    state["last_slot"] = slot
    save_json(STATE_FILE, state)

    # Enforce daily limits.
    todays_signals = [
        s for s in signals
        if s.get("created_at", "")[:10] == today
    ]

    if len(todays_signals) >= MAX_DAILY_SIGNALS:
        logging.info("Daily signal limit reached.")
        return

    pnl_today = daily_pnl(history, today)

    if pnl_today <= -(CAPITAL * MAX_DAILY_LOSS):
        logging.warning("Daily loss limit reached.")
        telegram(
            "🛑 GTF PRO V12.0\n"
            "Daily paper loss limit reached.\n"
            "No more new signals today."
        )
        return

    opened = active_trades(signals)

    if len(opened) >= MAX_ACTIVE_TRADES:
        logging.info("Maximum active trades reached.")
        return

    market, nifty, market_details = market_direction()

    if market == "NO_TRADE" or nifty is None:
        telegram(
            "⚪ GTF PRO V12.0 — NO TRADE\n"
            f"Reason: {market_details}\n"
            "Waiting for a clear market direction."
        )
        return

    candidates = []
    rejection_count = 0
    data_failures = 0

    occupied = {
        trade["symbol"]
        for trade in active_trades(signals)
    }

    for symbol in STOCKS:
        if symbol in occupied:
            continue

        if already_traded_today(signals, symbol, today):
            continue

        df = download_intraday(symbol)

        if df is None:
            data_failures += 1
            continue

        candidate, reason = build_candidate(
            symbol, market, df
        )

        if candidate:
            candidates.append(candidate)
        else:
            rejection_count += 1
            logging.info(
                "%s rejected: %s", symbol, reason
            )

    candidates.sort(
        key=lambda x: (
            x["adx"],
            x["rvol"],
            x["reward_risk"]
        ),
        reverse=True
    )

    remaining_daily = (
        MAX_DAILY_SIGNALS - len(todays_signals)
    )

    remaining_active = (
        MAX_ACTIVE_TRADES - len(opened)
    )

    limit = min(
        remaining_daily,
        remaining_active,
        3
    )

    selected = candidates[:limit]

    for candidate in selected:
        signals.append(candidate)

        telegram(
            format_signal(
                candidate, market, nifty
            )
        )

    save_json(SIGNALS_FILE, signals)
    save_json(HISTORY_FILE, history)

    todays_open = len(active_trades(signals))
    todays_pnl = daily_pnl(history, today)

    report = (
        "📊 GTF PRO V12.0 — SCAN REPORT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Time: {now.strftime('%d-%m-%Y %H:%M')} IST\n"
        f"Market: {market}\n"
        f"Nifty: {nifty:.2f}\n"
        f"Market details: {market_details}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Stocks checked: {len(STOCKS)}\n"
        f"Data failures: {data_failures}\n"
        f"Rejected: {rejection_count}\n"
        f"Qualified: {len(candidates)}\n"
        f"New calls: {len(selected)}\n"
        f"Open trades: {todays_open}\n"
        f"Closed P/L today: ₹{todays_pnl:+.2f}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Paper trading only. No broker orders."
    )

    logging.info(report)
    telegram(report)


if __name__ == "__main__":
    main()

