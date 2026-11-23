
import os
import json
import logging
import uuid

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
import requests

from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


# ==========================================
# GTF PRO V12.0
# CLEAN INTRADAY PAPER TRADING SCANNER
# ==========================================

VERSION = "GTF PRO V12.0"

IST = ZoneInfo("Asia/Kolkata")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

# PAPER TRADING CAPITAL
CAPITAL = 25000.0

# RISK MANAGEMENT
RISK_PER_TRADE = 0.005
MAX_DAILY_LOSS = 0.015
MAX_CAPITAL_USE = 0.90

# SIGNAL LIMITS
MAX_DAILY_SIGNALS = 3
MAX_ACTIVE_TRADES = 2
MIN_REWARD_RISK = 2.0

# MARKET TIMINGS
MARKET_OPEN = time(9, 15)
LAST_ENTRY_TIME = time(14, 45)
SQUARE_OFF_TIME = time(15, 15)
MARKET_CLOSE = time(15, 30)

# INDICATOR SETTINGS
MIN_ADX = 20
MIN_RVOL = 1.30
ATR_MULTIPLIER = 1.20

# DATA SETTINGS
DATA_INTERVAL = "5m"
DATA_PERIOD = "5d"
MAX_DATA_AGE_MINUTES = 15

# FILES
SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"
STATE_FILE = "scanner_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# NSE CASH EQUITY UNIVERSE
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
        logging.warning("Telegram credentials missing.")
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

    df.columns = [
        str(column).title()
        for column in df.columns
    ]

    required = [
        "Open", "High", "Low", "Close", "Volume"
    ]

    if not all(column in df.columns for column in required):
        return pd.DataFrame()

    df = df[required].copy()

    for column in required:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df = df.dropna()
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    return df

# ==========================================
# PART 2 — DATA AND INDICATORS
# ==========================================

def download_intraday(symbol):
    ticker = f"{symbol}.NS"

    try:
        data = yf.download(
            ticker,
            period=DATA_PERIOD,
            interval=DATA_INTERVAL,
            auto_adjust=True,
            progress=False,
            threads=False,
            prepost=False
        )

        df = clean_frame(data)

        if df.empty:
            logging.warning("%s: no data received", symbol)
            return pd.DataFrame()

        # Convert timestamps to IST.
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")

        df.index = df.index.tz_convert(IST)
        df = df.sort_index()

        # Yahoo 5-minute candles are treated as start-labelled.
        # A candle is complete only after its 5-minute interval ends.
        current = now_ist()
        completed_cutoff = current - timedelta(minutes=5)

        df = df[df.index <= completed_cutoff]

        if df.empty:
            return pd.DataFrame()

        # Check data freshness using candle end time.
        latest_candle_end = df.index[-1] + timedelta(minutes=5)

        if current - latest_candle_end > timedelta(
            minutes=MAX_DATA_AGE_MINUTES
        ):
            logging.warning("%s: stale data", symbol)
            return pd.DataFrame()

        # Keep regular NSE market-session candles only.
        df = df[
            (df.index.time >= time(9, 15))
            & (df.index.time < time(15, 30))
        ]

        if len(df) < 30:
            logging.warning("%s: insufficient 5m candles", symbol)
            return pd.DataFrame()

        return df

    except Exception as error:
        logging.error("%s download error: %s", symbol, error)
        return pd.DataFrame()


def make_15m(df):
    """
    Build 15-minute candles aligned to NSE session:
    09:15-09:30, 09:30-09:45, etc.

    Input candles are start-labelled 5-minute candles.
    Output candles are labelled by their ending time.
    """

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

        # Only completed 15-minute candles.
        current = now_ist()
        candles = candles[
            candles.index <= current
        ]

        # Exclude candles with no trading volume.
        candles = candles[candles["Volume"] > 0]

        return candles

    except Exception as error:
        logging.error("15m resampling error: %s", error)
        return pd.DataFrame()


def add_vwap(df):
    """
    Calculate VWAP separately for each trading day.
    """

    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()

    typical_price = (
        result["High"] +
        result["Low"] +
        result["Close"]
    ) / 3.0

    price_volume = typical_price * result["Volume"]

    session_dates = pd.Series(
        result.index.date,
        index=result.index
    )

    cumulative_pv = price_volume.groupby(
        session_dates
    ).cumsum()

    cumulative_volume = result["Volume"].groupby(
        session_dates
    ).cumsum()

    result["VWAP"] = (
        cumulative_pv /
        cumulative_volume.replace(0, float("nan"))
    )

    return result


def add_indicators(df):
    """
    Add trend, momentum, volatility and volume indicators.
    """

    if df is None or len(df) < 30:
        return pd.DataFrame()

    result = df.copy()

    try:
        result["EMA9"] = EMAIndicator(
            close=result["Close"],
            window=9
        ).ema_indicator()

        result["EMA20"] = EMAIndicator(
            close=result["Close"],
            window=20
        ).ema_indicator()

        result["RSI"] = RSIIndicator(
            close=result["Close"],
            window=14
        ).rsi()

        adx = ADXIndicator(
            high=result["High"],
            low=result["Low"],
            close=result["Close"],
            window=14
        )

        result["ADX"] = adx.adx()
        result["PLUS_DI"] = adx.adx_pos()
        result["MINUS_DI"] = adx.adx_neg()

        result["ATR"] = AverageTrueRange(
            high=result["High"],
            low=result["Low"],
            close=result["Close"],
            window=14
        ).average_true_range()

        result["AVG_VOLUME"] = (
            result["Volume"].rolling(20).mean()
        )

        result["RVOL"] = (
            result["Volume"] /
            result["AVG_VOLUME"].replace(0, float("nan"))
        )

        result = result.replace(
            [float("inf"), float("-inf")],
            float("nan")
        )

        return result.dropna()

    except Exception as error:
        logging.error("Indicator error: %s", error)
        return pd.DataFrame()


def prepare_stock_data(symbol):
    """
    Prepare both timeframes for one stock.
    """

    five_minute = download_intraday(symbol)

    if five_minute.empty:
        return None

    # VWAP is calculated on the 5-minute data.
    five_minute = add_vwap(five_minute)

    # Build the separate 15-minute trend timeframe.
    fifteen_minute = make_15m(five_minute)

    five_minute = add_indicators(five_minute)
    fifteen_minute = add_indicators(fifteen_minute)

    if five_minute.empty or fifteen_minute.empty:
        return None

    return {
        "5m": five_minute,
        "15m": fifteen_minute
    }


def check_stock_trend(data):
    """
    Confirm the stock trend using completed 15-minute candles.
    """

    if not data or data["15m"].empty:
        return "NO_TRADE"

    df = data["15m"]

    if len(df) < 25:
        return "NO_TRADE"

    last = df.iloc[-1]

    bullish = (
        last["Close"] > last["EMA9"]
        and last["EMA9"] > last["EMA20"]
        and last["PLUS_DI"] > last["MINUS_DI"]
        and last["ADX"] >= MIN_ADX
    )

    bearish = (
        last["Close"] < last["EMA9"]
        and last["EMA9"] < last["EMA20"]
        and last["MINUS_DI"] > last["PLUS_DI"]
        and last["ADX"] >= MIN_ADX
    )

    if bullish:
        return "BULLISH"

    if bearish:
        return "BEARISH"

    return "NO_TRADE"


def check_market_trend():
    """
    Confirm broad Nifty market direction using 15m candles.
    """

    try:
        data = yf.download(
            "^NSEI",
            period=DATA_PERIOD,
            interval=DATA_INTERVAL,
            auto_adjust=True,
            progress=False,
            threads=False,
            prepost=False
        )

        df = clean_frame(data)

        if df.empty:
            return "NO_TRADE", 0.0

        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")

        df.index = df.index.tz_convert(IST)
        df = df.sort_index()

        df = df[
            df.index <= now_ist() - timedelta(minutes=5)
        ]

        df = df[
            (df.index.time >= time(9, 15))
            & (df.index.time < time(15, 30))
        ]

        candles = make_15m(df)
        candles = add_indicators(candles)

        if len(candles) < 25:
            return "NO_TRADE", 0.0

        last = candles.iloc[-1]
        nifty_price = float(last["Close"])

        bullish = (
            last["Close"] > last["EMA9"]
            and last["EMA9"] > last["EMA20"]
            and last["PLUS_DI"] > last["MINUS_DI"]
            and last["ADX"] >= MIN_ADX
        )

        bearish = (
            last["Close"] < last["EMA9"]
            and last["EMA9"] < last["EMA20"]
            and last["MINUS_DI"] > last["PLUS_DI"]
            and last["ADX"] >= MIN_ADX
        )

        if bullish:
            return "BULLISH", nifty_price

        if bearish:
            return "BEARISH", nifty_price

        return "NO_TRADE", nifty_price

    except Exception as error:
        logging.error("Nifty trend error: %s", error)
        return "NO_TRADE", 0.0
def calculate_quantity(entry, stop):
    risk_per_share = abs(entry - stop)

    if risk_per_share <= 0 or entry <= 0:
        return 0

    risk_quantity = int(RISK_PER_TRADE * CAPITAL / risk_per_share)
    capital_quantity = int(CAPITAL * MAX_CAPITAL_USE / entry)

    return max(0, min(risk_quantity, capital_quantity))


def build_signal(symbol, data, market_trend):
    if not data:
        return None

    df5 = data["5m"]
    df15 = data["15m"]

    if len(df5) < 25 or len(df15) < 20:
        return None

    last = df5.iloc[-1]
    previous = df5.iloc[-2]

    stock_trend = check_stock_trend(data)

    # Only trade in the direction of the Nifty trend.
    if market_trend == "BULLISH" and stock_trend == "BULLISH":
        side = "BUY"

        conditions = (
            last["Close"] > last["VWAP"]
            and last["EMA_9"] > last["EMA_20"]
            and 52 <= last["RSI"] <= 70
            and last["ADX"] >= MIN_ADX
            and last["RVOL"] >= MIN_RVOL
            and last["Close"] > previous["High"]
        )

        if not conditions:
            return None

        entry = float(last["Close"])
        stop = entry - (float(last["ATR"]) * ATR_MULTIPLIER)

    elif market_trend == "BEARISH" and stock_trend == "BEARISH":
        side = "SHORT"

        conditions = (
            last["Close"] < last["VWAP"]
            and last["EMA_9"] < last["EMA_20"]
            and 30 <= last["RSI"] <= 48
            and last["ADX"] >= MIN_ADX
            and last["RVOL"] >= MIN_RVOL
            and last["Close"] < previous["Low"]
        )

        if not conditions:
            return None

        entry = float(last["Close"])
        stop = entry + (float(last["ATR"]) * ATR_MULTIPLIER)

    else:
        return None

    risk_per_share = abs(entry - stop)

    if risk_per_share <= 0:
        return None

    quantity = calculate_quantity(entry, stop)

    if quantity <= 0:
        return None

    target = (
        entry + (risk_per_share * MIN_REWARD_RISK)
        if side == "BUY"
        else entry - (risk_per_share * MIN_REWARD_RISK)
    )

    risk_amount = quantity * risk_per_share
    capital_used = quantity * entry

    if risk_amount > CAPITAL * RISK_PER_TRADE:
        return None

    if capital_used > CAPITAL * MAX_CAPITAL_USE:
        return None

    return {
        "id": str(uuid.uuid4()),
        "symbol": symbol,
        "side": side,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "quantity": quantity,
        "risk_amount": round(risk_amount, 2),
        "capital_used": round(capital_used, 2),
        "status": "OPEN",
        "entry_time": now_ist().isoformat(),
        "last_price": round(entry, 2),
        "pnl": 0.0
    }
def get_active_trades():
    trades = load_json(SIGNALS_FILE, [])
    if not isinstance(trades, list):
        return []

    return [
        trade for trade in trades
        if trade.get("status") == "OPEN"
    ]


def get_today_history_pnl():
    history = load_json(HISTORY_FILE, [])

    if not isinstance(history, list):
        return 0.0

    today = today_string()
    total = 0.0

    for trade in history:
        exit_time = trade.get("exit_time", "")

        if exit_time.startswith(today):
            total += float(trade.get("pnl", 0))

    return total


def can_open_trade(symbol):
    state = load_json(STATE_FILE, {})

    if not isinstance(state, dict):
        state = {}

    today = today_string()

    # Reset daily counters on a new trading day.
    if state.get("date") != today:
        state = {
            "date": today,
            "signals_count": 0,
            "symbols": []
        }

    active_trades = get_active_trades()

    if state.get("signals_count", 0) >= MAX_DAILY_SIGNALS:
        logging.info("Daily signal limit reached.")
        save_json(STATE_FILE, state)
        return False

    if len(active_trades) >= MAX_ACTIVE_TRADES:
        logging.info("Maximum active trades reached.")
        save_json(STATE_FILE, state)
        return False

    if symbol in state.get("symbols", []):
        logging.info("%s already signalled today.", symbol)
        save_json(STATE_FILE, state)
        return False

    # Closed-trade P&L check. Open-trade P&L will be
    # included in the trade-monitoring section.
    if get_today_history_pnl() <= -(CAPITAL * MAX_DAILY_LOSS):
        logging.warning("Daily loss limit reached. New trades blocked.")
        save_json(STATE_FILE, state)
        return False

    save_json(STATE_FILE, state)
    return True


def register_signal(signal):
    signals = load_json(SIGNALS_FILE, [])

    if not isinstance(signals, list):
        signals = []

    signals.append(signal)
    save_json(SIGNALS_FILE, signals)

    state = load_json(STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}

    today = today_string()

    if state.get("date") != today:
        state = {
            "date": today,
            "signals_count": 0,
            "symbols": []
        }

    state["signals_count"] = state.get("signals_count", 0) + 1
    state.setdefault("symbols", []).append(signal["symbol"])

    save_json(STATE_FILE, state)


def send_signal_alert(signal):
    message = (
        f"📊 {VERSION} — PAPER SIGNAL\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Stock: {signal['symbol']}\n"
        f"Side: {signal['side']}\n"
        f"Entry: ₹{signal['entry']}\n"
        f"Stop Loss: ₹{signal['stop']}\n"
        f"Target: ₹{signal['target']}\n"
        f"Quantity: {signal['quantity']}\n"
        f"Risk: ₹{signal['risk_amount']}\n"
        f"Capital Used: ₹{signal['capital_used']}\n"
        f"Reward/Risk: 1:{MIN_REWARD_RISK:.1f}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Paper trading only. No broker order placed."
    )

    telegram(message)
def close_trade(trade, exit_price, reason):
    entry = float(trade["entry"])
    quantity = int(trade["quantity"])

    if trade["side"] == "BUY":
        pnl = (exit_price - entry) * quantity
    else:
        pnl = (entry - exit_price) * quantity

    trade["status"] = "CLOSED"
    trade["exit_price"] = round(exit_price, 2)
    trade["exit_time"] = now_ist().isoformat()
    trade["exit_reason"] = reason
    trade["pnl"] = round(pnl, 2)

    history = load_json(HISTORY_FILE, [])

    if not isinstance(history, list):
        history = []

    history.append(trade)
    save_json(HISTORY_FILE, history)

    message = (
        f"📋 {VERSION} — PAPER TRADE CLOSED\n"
        f"Stock: {trade['symbol']}\n"
        f"Side: {trade['side']}\n"
        f"Exit: ₹{exit_price:.2f}\n"
        f"Reason: {reason}\n"
        f"P&L: ₹{pnl:.2f}\n"
        f"Paper trading only."
    )

    telegram(message)


def monitor_open_trades():
    signals = load_json(SIGNALS_FILE, [])

    if not isinstance(signals, list):
        signals = []

    changed = False

    for trade in signals:
        if trade.get("status") != "OPEN":
            continue

        symbol = trade["symbol"]
        data = prepare_stock_data(symbol)

        if not data:
            logging.warning("Cannot monitor %s: data unavailable.", symbol)
            continue

        candle = data["5m"].iloc[-1]

        high = float(candle["High"])
        low = float(candle["Low"])
        close = float(candle["Close"])

        trade["last_price"] = round(close, 2)

        entry = float(trade["entry"])
        stop = float(trade["stop"])
        target = float(trade["target"])

        if trade["side"] == "BUY":
            floating_pnl = (close - entry) * int(trade["quantity"])
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            floating_pnl = (entry - close) * int(trade["quantity"])
            stop_hit = high >= stop
            target_hit = low <= target

        trade["pnl"] = round(floating_pnl, 2)

        if stop_hit:
            close_trade(trade, stop, "STOP LOSS")
            changed = True

        elif target_hit:
            close_trade(trade, target, "TARGET")
            changed = True

        elif now_ist().time() >= SQUARE_OFF_TIME:
            close_trade(trade, close, "TIME-BASED SQUARE OFF")
            changed = True

    if changed or signals:
        save_json(SIGNALS_FILE, signals)


def get_total_daily_pnl():
    closed_pnl = get_today_history_pnl()

    open_pnl = 0.0
    for trade in get_active_trades():
        open_pnl += float(trade.get("pnl", 0))

    return round(closed_pnl + open_pnl, 2)


def daily_loss_limit_reached():
    total_pnl = get_total_daily_pnl()
    loss_limit = CAPITAL * MAX_DAILY_LOSS

    if total_pnl <= -loss_limit:
        logging.warning(
            "Daily loss limit reached. Current P&L: ₹%.2f",
            total_pnl
        )
        return True

    return False
def main():
    current_time = now_ist().time()

    logging.info("Starting %s", VERSION)
    logging.info("Current IST time: %s", now_ist())

    # Do not scan outside regular NSE market hours.
    if current_time < MARKET_OPEN or current_time >= MARKET_CLOSE:
        logging.info("Market is closed. Scanner stopped.")
        return

    # First monitor existing paper trades.
    monitor_open_trades()

    # Block new trades if daily loss limit is reached.
    if daily_loss_limit_reached():
        telegram(
            f"⚠️ {VERSION}\n"
            f"Daily loss limit reached.\n"
            f"New paper signals are blocked today.\n"
            f"Current daily P&L: ₹{get_total_daily_pnl():.2f}"
        )
        return

    # No fresh entries after the configured entry time.
    if current_time > LAST_ENTRY_TIME:
        logging.info("Last entry time passed. Monitoring only.")
        return

    market_trend, nifty_price = check_market_trend()

    logging.info(
        "Nifty trend: %s | Nifty price: %s",
        market_trend,
        nifty_price
    )

    if market_trend == "NO_TRADE":
        logging.info("No clear Nifty trend. No new signals.")
        return

    logging.info("Scanning %s stocks.", len(STOCKS))

    new_signals = 0

    for symbol in STOCKS:
        if new_signals >= MAX_DAILY_SIGNALS:
            break

        if daily_loss_limit_reached():
            logging.warning("Daily loss limit reached during scan.")
            break

        if not can_open_trade(symbol):
            continue

        try:
            data = prepare_stock_data(symbol)

            if not data:
                continue

            signal = build_signal(
                symbol,
                data,
                market_trend
            )

            if signal is None:
                continue

            register_signal(signal)
            send_signal_alert(signal)

            new_signals += 1

            logging.info(
                "New paper signal: %s %s",
                signal["side"],
                symbol
            )

        except Exception:
            logging.exception("Error scanning %s", symbol)

    logging.info(
        "Scan completed. New signals: %s",
        new_signals
    )

    telegram(
        f"📊 {VERSION} — SCAN COMPLETE\n"
        f"Nifty Trend: {market_trend}\n"
        f"Nifty Price: {nifty_price}\n"
        f"New Signals: {new_signals}\n"
        f"Daily P&L: ₹{get_total_daily_pnl():.2f}\n"
        f"Paper trading only."
    )


if __name__ == "__main__":
    main()