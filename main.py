
import os
import json
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
import requests

from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


# ==========================================
# GTF PRO V12.0 — INTRADAY PAPER SCANNER
# ==========================================

IST = ZoneInfo("Asia/Kolkata")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

CAPITAL = 25000.0
RISK_PER_TRADE = 0.005
MAX_DAILY_LOSS = 0.015
MAX_CAPITAL_USE = 0.90

MAX_DAILY_SIGNALS = 3
MAX_ACTIVE_TRADES = 2
MIN_REWARD_RISK = 2.0

MARKET_OPEN = time(9, 15)
LAST_ENTRY_TIME = time(14, 45)
SQUARE_OFF_TIME = time(15, 15)
MARKET_CLOSE = time(15, 30)

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"
STATE_FILE = "scanner_state.json"

LOG_LEVEL = logging.INFO

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

STOCKS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "AXISBANK", "KOTAKBANK", "LT", "BHARTIARTL",
    "ITC", "HINDUNILVR", "BAJFINANCE", "MARUTI",
    "TATAMOTORS", "M&M", "SUNPHARMA", "TITAN",
    "ULTRACEMCO", "NTPC", "POWERGRID", "ONGC",
    "COALINDIA", "TATASTEEL", "JSWSTEEL", "HCLTECH",
    "WIPRO", "TECHM", "ADANIPORTS", "ASIANPAINT",
    "BAJAJFINSV", "NESTLEIND", "GRASIM", "CIPLA",
    "DRREDDY", "DIVISLAB", "APOLLOHOSP", "EICHERMOT",
    "HEROMOTOCO", "BAJAJ-AUTO", "INDUSINDBK",
    "FEDERALBNK", "BANKBARODA", "PNB", "IDFCFIRSTB",
    "DLF", "BEL", "HAL", "TRENT", "ZOMATO"
]


def now_ist():
    return datetime.now(IST)


def today_string():
    return now_ist().strftime("%Y-%m-%d")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    temporary = path + ".tmp"

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)

    os.replace(temporary, path)


def telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("Telegram credentials are missing.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=15
        )
        response.raise_for_status()
        return True

    except requests.RequestException as error:
        logging.error("Telegram error: %s", error)
        return False


def clean_frame(data):
    if data is None or data.empty:
        return pd.DataFrame()

    df = data.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [str(col).title() for col in df.columns]

    required = ["Open", "High", "Low", "Close", "Volume"]

    if not all(col in df.columns for col in required):
        return pd.DataFrame()

    df = df[required].copy()

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna()
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    return df

# ==========================================
# PART 2 — MARKET DATA AND INDICATORS
# ==========================================

def download_intraday(symbol):
    ticker = f"{symbol}.NS"

    try:
        data = yf.download(
            ticker,
            period="5d",
            interval="5m",
            auto_adjust=True,
            progress=False,
            threads=False,
            prepost=False
        )

        df = clean_frame(data)

        if df.empty:
            logging.warning("%s: no market data", symbol)
            return pd.DataFrame()

        # Convert timestamps to Indian Standard Time.
        if df.index.tz is None:
            df.index = df.index.tz_localize(IST)
        else:
            df.index = df.index.tz_convert(IST)

        df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()

        # Remove the currently forming 5-minute candle.
        current_time = now_ist()
        completed_before = current_time - timedelta(minutes=5)
        df = df[df.index <= completed_before]

        if df.empty:
            return pd.DataFrame()

        # Reject stale data.
        latest_candle = df.index[-1]

        if current_time - latest_candle > timedelta(minutes=20):
            logging.warning("%s: stale market data", symbol)
            return pd.DataFrame()

        if len(df) < 30:
            logging.warning("%s: insufficient candles", symbol)
            return pd.DataFrame()

        return df

    except Exception as error:
        logging.error("%s download failed: %s", symbol, error)
        return pd.DataFrame()


def make_15m(df):
    if df is None or df.empty:
        return pd.DataFrame()

    try:
        candles = df.resample(
            "15min",
            origin="start_day",
            offset="9h15min",
            label="right",
            closed="left"
        ).agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        })

        candles = candles.dropna()

        # Keep only fully completed 15-minute candles.
        current_time = now_ist()
        candles = candles[candles.index <= current_time]

        return candles

    except Exception as error:
        logging.error("15-minute resampling failed: %s", error)
        return pd.DataFrame()


def add_indicators(df):
    if df is None or len(df) < 25:
        return pd.DataFrame()

    result = df.copy()

    try:
        # Exponential moving averages.
        result["EMA9"] = EMAIndicator(
            close=result["Close"],
            window=9
        ).ema_indicator()

        result["EMA20"] = EMAIndicator(
            close=result["Close"],
            window=20
        ).ema_indicator()

        # Relative strength index.
        result["RSI"] = RSIIndicator(
            close=result["Close"],
            window=14
        ).rsi()

        # Average directional index.
        adx = ADXIndicator(
            high=result["High"],
            low=result["Low"],
            close=result["Close"],
            window=14
        )

        result["ADX"] = adx.adx()
        result["PLUS_DI"] = adx.adx_pos()
        result["MINUS_DI"] = adx.adx_neg()

        # Average true range.
        result["ATR"] = AverageTrueRange(
            high=result["High"],
            low=result["Low"],
            close=result["Close"],
            window=14
        ).average_true_range()

        # Relative volume.
        result["AVG_VOLUME"] = (
            result["Volume"]
            .rolling(window=20)
            .mean()
        )

        result["RVOL"] = (
            result["Volume"] /
            result["AVG_VOLUME"].replace(0, pd.NA)
        )

        # Intraday VWAP, reset each trading day.
        typical_price = (
            result["High"] +
            result["Low"] +
            result["Close"]
        ) / 3

        price_volume = typical_price * result["Volume"]

        trading_day = pd.Series(
            result.index.date,
            index=result.index
        )

        cumulative_pv = price_volume.groupby(trading_day).cumsum()
        cumulative_volume = result["Volume"].groupby(
            trading_day
        ).cumsum()

        result["VWAP"] = (
            cumulative_pv /
            cumulative_volume.replace(0, pd.NA)
        )

        result = result.replace(
            [float("inf"), float("-inf")],
            pd.NA
        )

        return result.dropna()

    except Exception as error:
        logging.error("Indicator calculation failed: %s", error)
        return pd.DataFrame()


def market_direction():
    """
    Returns:
        market trend: BULLISH, BEARISH, or NO_TRADE
        latest Nifty value
    """

    try:
        data = yf.download(
            "^NSEI",
            period="5d",
            interval="5m",
            auto_adjust=True,
            progress=False,
            threads=False,
            prepost=False
        )

        df = clean_frame(data)

        if df.empty:
            return "NO_TRADE", 0.0

        if df.index.tz is None:
            df.index = df.index.tz_localize(IST)
        else:
            df.index = df.index.tz_convert(IST)

        df = df.sort_index()

        # Exclude incomplete 5-minute candles.
        df = df[df.index <= now_ist() - timedelta(minutes=5)]

        candles = make_15m(df)
        candles = add_indicators(candles)

        if len(candles) < 25:
            return "NO_TRADE", 0.0

        last = candles.iloc[-1]

        nifty_price = float(last["Close"])

        bullish = (
            last["Close"] > last["VWAP"]
            and last["EMA9"] > last["EMA20"]
            and last["PLUS_DI"] > last["MINUS_DI"]
            and last["ADX"] >= 18
        )

        bearish = (
            last["Close"] < last["VWAP"]
            and last["EMA9"] < last["EMA20"]
            and last["MINUS_DI"] > last["PLUS_DI"]
            and last["ADX"] >= 18
        )

        if bullish:
            return "BULLISH", nifty_price

        if bearish:
            return "BEARISH", nifty_price

        return "NO_TRADE", nifty_price

    except Exception as error:
        logging.error("Nifty trend check failed: %s", error)
        return "NO_TRADE", 0.0

# ==========================================
# PART 3 — SIGNALS, RISK AND MAIN SCANNER
# ==========================================

def calculate_quantity(entry, stop):
    risk_per_share = abs(entry - stop)

    if risk_per_share <= 0:
        return 0

    risk_amount = CAPITAL * RISK_PER_TRADE
    quantity_by_risk = int(risk_amount / risk_per_share)

    capital_limit = CAPITAL * MAX_CAPITAL_USE
    quantity_by_capital = int(capital_limit / entry)

    return max(0, min(quantity_by_risk, quantity_by_capital))


def get_daily_signals(signals):
    today = today_string()

    return [
        trade for trade in signals
        if trade.get("created_at", "").startswith(today)
    ]


def active_trades(signals):
    return [
        trade for trade in signals
        if trade.get("status") == "OPEN"
    ]


def daily_pnl(history, signals):
    today = today_string()

    closed_pnl = sum(
        float(trade.get("pnl_amount", 0))
        for trade in history
        if trade.get("closed_at", "").startswith(today)
    )

    floating_pnl = 0.0

    for trade in active_trades(signals):
        price = float(trade.get("last_price", trade["entry"]))
        entry = float(trade["entry"])
        quantity = int(trade["quantity"])

        if trade["side"] == "BUY":
            floating_pnl += (price - entry) * quantity
        else:
            floating_pnl += (entry - price) * quantity

    return closed_pnl + floating_pnl


def already_traded_today(symbol, signals):
    today = today_string()

    return any(
        trade.get("symbol") == symbol
        and trade.get("created_at", "").startswith(today)
        for trade in signals
    )


def build_candidate(symbol, market, raw_df):
    df = add_indicators(raw_df)

    if len(df) < 25:
        return None

    # Use the latest completed candle.
    last = df.iloc[-1]
    previous = df.iloc[-2]

    entry = float(last["Close"])
    atr = float(last["ATR"])

    if atr <= 0 or entry <= 0:
        return None

    if float(last["ADX"]) < 20:
        return None

    if float(last["RVOL"]) < 1.30:
        return None

    side = None

    # BUY setup.
    if market == "BULLISH":
        if (
            last["Close"] > last["VWAP"]
            and last["EMA9"] > last["EMA20"]
            and last["PLUS_DI"] > last["MINUS_DI"]
            and 52 <= last["RSI"] <= 70
            and last["Close"] > previous["High"]
        ):
            side = "BUY"

    # SHORT setup.
    elif market == "BEARISH":
        if (
            last["Close"] < last["VWAP"]
            and last["EMA9"] < last["EMA20"]
            and last["MINUS_DI"] > last["PLUS_DI"]
            and 30 <= last["RSI"] <= 48
            and last["Close"] < previous["Low"]
        ):
            side = "SHORT"

    if side is None:
        return None

    if side == "BUY":
        stop = min(
            float(last["Low"]),
            entry - (1.2 * atr)
        )

        risk = entry - stop
        target = entry + (risk * MIN_REWARD_RR)

    else:
        stop = max(
            float(last["High"]),
            entry + (1.2 * atr)
        )

        risk = stop - entry
        target = entry - (risk * MIN_REWARD_RR)

    if risk <= 0 or target <= 0:
        return None

    quantity = calculate_quantity(entry, stop)

    if quantity <= 0:
        return None

    return {
        "symbol": symbol,
        "side": side,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "quantity": quantity,
        "risk_amount": round(risk * quantity, 2),
        "reward_risk": MIN_REWARD_RISK,
        "last_price": round(entry, 2),
        "status": "OPEN",
        "created_at": now_ist().isoformat(),
        "closed_at": None,
        "pnl_amount": 0.0
    }


def close_trade(trade, exit_price, reason, history):
    entry = float(trade["entry"])
    quantity = int(trade["quantity"])

    if trade["side"] == "BUY":
        pnl = (exit_price - entry) * quantity
    else:
        pnl = (entry - exit_price) * quantity

    trade["status"] = "CLOSED"
    trade["exit"] = round(exit_price, 2)
    trade["exit_reason"] = reason
    trade["closed_at"] = now_ist().isoformat()
    trade["pnl_amount"] = round(pnl, 2)

    history.append(trade.copy())

    logging.info(
        "%s closed | %s | P/L: ₹%.2f",
        trade["symbol"], reason, pnl
    )

    return trade


def monitor_trades(signals, history):
    changed = False

    for trade in active_trades(signals):
        symbol = trade["symbol"]
        df = download_intraday(symbol)

        if df.empty:
            continue

        candle = df.iloc[-1]

        entry = float(trade["entry"])
        stop = float(trade["stop"])
        target = float(trade["target"])

        high = float(candle["High"])
        low = float(candle["Low"])
        close = float(candle["Close"])

        trade["last_price"] = close

        exit_price = None
        reason = None

        # Conservative assumption: if both levels are touched
        # in one candle, record the stop-loss first.
        if trade["side"] == "BUY":
            if low <= stop:
                exit_price = stop
                reason = "STOP LOSS"
            elif high >= target:
                exit_price = target
                reason = "TARGET"

        else:
            if high >= stop:
                exit_price = stop
                reason = "STOP LOSS"
            elif low <= target:
                exit_price = target
                reason = "TARGET"

        if now_ist().time() >= SQUARE_OFF_TIME:
            exit_price = close
            reason = "TIME SQUARE-OFF"

        if exit_price is not None:
            close_trade(trade, exit_price, reason, history)

            telegram(
                f"📕 PAPER TRADE CLOSED\n"
                f"Symbol: {symbol}\n"
                f"Side: {trade['side']}\n"
                f"Exit: ₹{exit_price:.2f}\n"
                f"Reason: {reason}\n"
                f"P/L: ₹{trade['pnl_amount']:.2f}"
            )

        changed = True

    return changed


def format_signal(trade, nifty):
    return (
        f"📊 GTF PRO V12.0\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📌 {trade['side']} — {trade['symbol']}\n"
        f"💰 Entry: ₹{trade['entry']:.2f}\n"
        f"🛑 Stop Loss: ₹{trade['stop']:.2f}\n"
        f"🎯 Target: ₹{trade['target']:.2f}\n"
        f"📦 Quantity: {trade['quantity']}\n"
        f"⚖️ Risk: ₹{trade['risk_amount']:.2f}\n"
        f"📈 Reward/Risk: 1:{trade['reward_risk']:.1f}\n"
        f"📊 Nifty: {nifty:.2f}\n"
        f"💼 Paper Capital: ₹{CAPITAL:.0f}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"⚠️ PAPER TRADE ONLY"
    )


def main():
    logging.info("Starting GTF PRO V12.0")

    signals = load_json(SIGNALS_FILE, [])
    history = load_json(HISTORY_FILE, [])
    state = load_json(STATE_FILE, {})

    if not isinstance(signals, list):
        signals = []

    if not isinstance(history, list):
        history = []

    if not isinstance(state, dict):
        state = {}

    # Always monitor existing paper trades first.
    monitor_trades(signals, history)

    save_json(SIGNALS_FILE, signals)
    save_json(HISTORY_FILE, history)

    current = now_ist()
    current_time = current.time()

    if current.weekday() >= 5:
        logging.info("Weekend — scanner stopped.")
        return

    if current_time < MARKET_OPEN or current_time > MARKET_CLOSE:
        logging.info("Outside market hours.")
        return

    # New entries are not allowed after the last-entry time.
    if current_time > LAST_ENTRY_TIME:
        logging.info("Last entry time passed.")
        return

    # One scan per 5-minute time slot.
    slot = current.strftime("%Y-%m-%d-%H-%M")
    slot = slot[:-1] + "0"

    if state.get("last_slot") == slot:
        logging.info("This scan slot was already processed.")
        return

    today_signals = get_daily_signals(signals)

    if len(today_signals) >= MAX_DAILY_SIGNALS:
        logging.info("Daily signal limit reached.")
        state["last_slot"] = slot
        save_json(STATE_FILE, state)
        return

    pnl = daily_pnl(history, signals)

    if pnl <= -(CAPITAL * MAX_DAILY_LOSS):
        logging.warning("Daily loss limit reached. No new entries.")
        telegram(
            "🛑 GTF PRO V12.0\n"
            "Daily loss limit reached.\n"
            "No new paper entries will be generated."
        )
        state["last_slot"] = slot
        save_json(STATE_FILE, state)
        return

    if len(active_trades(signals)) >= MAX_ACTIVE_TRADES:
        logging.info("Maximum active trades reached.")
        state["last_slot"] = slot
        save_json(STATE_FILE, state)
        return

    market, nifty = market_direction()

    logging.info(
        "Market: %s | Nifty: %.2f",
        market, nifty
    )

    if market == "NO_TRADE":
        logging.info("No clear Nifty trend. No new signals.")
        state["last_slot"] = slot
        save_json(STATE_FILE, state)
        return

    new_signals = []

    for symbol in STOCKS:
        if len(today_signals) + len(new_signals) >= MAX_DAILY_SIGNALS:
            break

        if len(active_trades(signals)) + len(new_signals) >= MAX_ACTIVE_TRADES:
            break

        if already_traded_today(symbol, signals):
            continue

        df = download_intraday(symbol)

        if df.empty:
            continue

        candidate = build_candidate(symbol, market, df)

        if candidate is None:
            continue

        # Check risk limit again before adding a trade.
        current_pnl = daily_pnl(history, signals)

        if current_pnl <= -(CAPITAL * MAX_DAILY_LOSS):
            logging.warning("Daily loss limit reached during scan.")
            break

        signals.append(candidate)
        new_signals.append(candidate)

        save_json(SIGNALS_FILE, signals)

        telegram(format_signal(candidate, nifty))

        logging.info(
            "New %s signal: %s",
            candidate["side"], symbol
        )

    save_json(SIGNALS_FILE, signals)

    state["last_slot"] = slot
    save_json(STATE_FILE, state)

    logging.info(
        "Scan completed | Market: %s | New signals: %d",
        market, len(new_signals)
    )

    telegram(
        f"📊 GTF PRO V12.0 SCAN REPORT\n"
        f"Market: {market}\n"
        f"Nifty: {nifty:.2f}\n"
        f"New signals: {len(new_signals)}\n"
        f"Active trades: {len(active_trades(signals))}\n"
        f"Daily P/L: ₹{daily_pnl(history, signals):.2f}\n"
        f"Paper capital: ₹{CAPITAL:.0f}"
    )


if __name__ == "__main__":
    main()


