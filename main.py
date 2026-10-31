
import os
import json
import logging
import requests
import yfinance as yf
import pandas as pd
import numpy as np

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


# ============================================================
# GTF PRO SCANNER V11.2
# NSE CASH EQUITY - PAPER TRADING ONLY
# ============================================================

VERSION = "V11.2"

IST = ZoneInfo("Asia/Kolkata")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

TELEGRAM_URL = (
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
)

SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"
STATE_FILE = "scan_state.json"

MAX_NEW_SIGNALS = 5
MIN_DAILY_ROWS = 220

MIN_ADX = 22
MIN_RVOL = 1.30

MIN_RSI = 50
MAX_RSI = 72

MIN_RR_SWING = 2.0
MIN_RR_SHORT = 1.5

MAX_ENTRY_AGE_MINUTES = 90
MAX_SWING_ENTRY_AGE_DAYS = 5

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
SQUARE_OFF_TIME = time(15, 20)
SHORT_ENTRY_CUTOFF = time(14, 0)

MAX_SCAN_STATE = 100


STOCKS = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
    "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "LT.NS", "BHARTIARTL.NS",
    "ITC.NS", "HINDUNILVR.NS", "BAJFINANCE.NS",
    "MARUTI.NS", "TATAMOTORS.NS", "M&M.NS",
    "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS",
    "NTPC.NS", "POWERGRID.NS", "ONGC.NS",
    "COALINDIA.NS", "TATASTEEL.NS", "JSWSTEEL.NS",
    "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
    "ADANIPORTS.NS", "ASIANPAINT.NS",
    "BAJAJFINSV.NS", "NESTLEIND.NS", "GRASIM.NS",
    "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS",
    "APOLLOHOSP.NS", "EICHERMOT.NS",
    "HEROMOTOCO.NS", "BAJAJ-AUTO.NS",
    "INDUSINDBK.NS", "FEDERALBNK.NS",
    "BANKBARODA.NS", "PNB.NS", "IDFCFIRSTB.NS",
    "DLF.NS", "BEL.NS", "HAL.NS",
    "TRENT.NS", "ZOMATO.NS"
]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

log = logging.getLogger("GTF")


# ============================================================
# BASIC HELPERS
# ============================================================

def now_ist():
    return datetime.now(IST)


def today_string():
    return now_ist().strftime("%Y-%m-%d")


def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        log.warning("Could not read %s: %s", path, exc)

    return default


def save_json(path, data):
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    os.replace(temp_path, path)


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram credentials are missing.")
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
        result = response.json()

        return bool(result.get("ok"))

    except Exception as exc:
        log.error("Telegram error: %s", exc)
        return False


def symbol_name(symbol):
    return symbol.replace(".NS", "")


def safe_float(value, default=0.0):
    try:
        result = float(value)

        if np.isfinite(result):
            return result

    except Exception:
        pass

    return default


# ============================================================
# YAHOO FINANCE DATA
# ============================================================

def clean_yf_frame(data):
    if data is None or data.empty:
        return pd.DataFrame()

    df = data.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close", "Volume"]

    for column in required:
        if column not in df.columns:
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


def download_daily(symbol):
    try:
        raw = yf.download(
            symbol,
            period="2y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=20
        )

        df = clean_yf_frame(raw)

        if len(df) < MIN_DAILY_ROWS:
            return pd.DataFrame()

        return df

    except Exception as exc:
        log.warning("Daily download failed for %s: %s", symbol, exc)
        return pd.DataFrame()


def download_intraday(symbol):
    try:
        raw = yf.download(
            symbol,
            period="5d",
            interval="5m",
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=20
        )

        df = clean_yf_frame(raw)

        if len(df) < 30:
            return pd.DataFrame()

        # Exclude the currently forming 5-minute candle.
        current_time = pd.Timestamp.now(tz="UTC")

        index = pd.DatetimeIndex(df.index)

        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")

        df.index = index

        latest_time = df.index[-1]

        if (current_time - latest_time) > pd.Timedelta(minutes=20):
            return pd.DataFrame()

        df = df.iloc[:-1]

        if len(df) < 25:
            return pd.DataFrame()

        return df

    except Exception as exc:
        log.warning("Intraday download failed for %s: %s", symbol, exc)
        return pd.DataFrame()


# ============================================================
# INDICATORS
# ============================================================

def add_indicators(df):
    df = df.copy()

    df["EMA9"] = EMAIndicator(
        close=df["Close"], window=9
    ).ema_indicator()

    df["EMA20"] = EMAIndicator(
        close=df["Close"], window=20
    ).ema_indicator()

    df["EMA50"] = EMAIndicator(
        close=df["Close"], window=50
    ).ema_indicator()

    df["EMA200"] = EMAIndicator(
        close=df["Close"], window=200
    ).ema_indicator()

    df["RSI"] = RSIIndicator(
        close=df["Close"], window=14
    ).rsi()

    macd = MACD(close=df["Close"])

    df["MACD"] = macd.macd()
    df["MACD_SIGNAL"] = macd.macd_signal()

    adx = ADXIndicator(
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        window=14
    )

    df["ADX"] = adx.adx()
    df["PLUS_DI"] = adx.adx_pos()
    df["MINUS_DI"] = adx.adx_neg()

    atr = AverageTrueRange(
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        window=14
    )

    df["ATR"] = atr.average_true_range()

    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()

    df["RVOL"] = (
        df["Volume"] / df["VOL_AVG20"].replace(0, np.nan)
    )

    return df.dropna()


# ============================================================
# MARKET REGIME
# ============================================================

def market_regime():
    result = {
        "regime": "SIDEWAYS",
        "nifty": 0,
        "ema20": 0,
        "ema50": 0,
        "adx": 0,
        "plus_di": 0,
        "minus_di": 0
    }

    df = download_daily("^NSEI")

    if df.empty:
        log.warning("Nifty data unavailable. Using SIDEWAYS.")
        return result

    df = add_indicators(df)

    if len(df) < 5:
        return result

    last = df.iloc[-1]

    close = safe_float(last["Close"])
    ema20 = safe_float(last["EMA20"])
    ema50 = safe_float(last["EMA50"])
    adx = safe_float(last["ADX"])
    plus_di = safe_float(last["PLUS_DI"])
    minus_di = safe_float(last["MINUS_DI"])

    regime = "SIDEWAYS"

    if (
        close > ema20 > ema50
        and plus_di > minus_di
        and adx >= MIN_ADX
    ):
        regime = "BULLISH"

    elif (
        close < ema20 < ema50
        and minus_di > plus_di
        and adx >= MIN_ADX
    ):
        regime = "BEARISH"

    result.update({
        "regime": regime,
        "nifty": round(close, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "adx": round(adx, 2),
        "plus_di": round(plus_di, 2),
        "minus_di": round(minus_di, 2)
    })

    return result


# ============================================================
# SWING BUY CANDIDATE
# ============================================================

def swing_candidate(symbol, df):
    if df.empty or len(df) < MIN_DAILY_ROWS:
        return None, "insufficient daily data"

    df = add_indicators(df)

    if len(df) < 25:
        return None, "indicator data insufficient"

    last = df.iloc[-1]
    previous = df.iloc[-2]

    close = safe_float(last["Close"])
    high = safe_float(last["High"])
    low = safe_float(last["Low"])

    ema20 = safe_float(last["EMA20"])
    ema50 = safe_float(last["EMA50"])
    ema200 = safe_float(last["EMA200"])

    rsi = safe_float(last["RSI"])
    adx = safe_float(last["ADX"])
    plus_di = safe_float(last["PLUS_DI"])
    minus_di = safe_float(last["MINUS_DI"])

    atr = safe_float(last["ATR"])
    rvol = safe_float(last["RVOL"])

    if not (close > ema20 > ema50 > ema200):
        return None, "daily trend not bullish"

    if not (MIN_RSI <= rsi <= MAX_RSI):
        return None, "RSI outside range"

    if adx < MIN_ADX:
        return None, "ADX too low"

    if plus_di <= minus_di:
        return None, "positive DI confirmation missing"

    if rvol < MIN_RVOL:
        return None, "volume confirmation missing"

    if safe_float(last["MACD"]) <= safe_float(last["MACD_SIGNAL"]):
        return None, "MACD not bullish"

    previous_high = safe_float(
        df["High"].iloc[-21:-1].max()
    )

    if close <= previous_high:
        return None, "20-day breakout missing"

    if atr <= 0:
        return None, "invalid ATR"

    extension = (close - ema20) / atr

    if extension < 0 or extension > 2.0:
        return None, "price extension too high or invalid"

    entry = high + (0.05 * atr)

    recent_low = safe_float(
        df["Low"].iloc[-10:].min()
    )

    stop = max(
        recent_low,
        entry - (1.5 * atr)
    )

    if stop >= entry:
        return None, "invalid stop loss"

    risk = entry - stop
    target = entry + (MIN_RR_SWING * risk)

    if risk <= 0:
        return None, "invalid risk"

    return {
        "symbol": symbol,
        "name": symbol_name(symbol),
        "side": "BUY",
        "strategy": "SWING",
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "rr": round((target - entry) / risk, 2),
        "score": 80,
        "rsi": round(rsi, 2),
        "adx": round(adx, 2),
        "rvol": round(rvol, 2),
        "created_at": now_ist().isoformat(),
        "status": "WAITING_ENTRY"
    }, "qualified"

# ============================================================
# INTRADAY SHORT CANDIDATE
# PAPER TRADING ONLY - MUST SQUARE OFF INTRADAY
# ============================================================

def short_candidate(symbol, df):
    if df.empty or len(df) < 30:
        return None, "insufficient intraday data"

    df = add_indicators(df)

    if len(df) < 20:
        return None, "intraday indicators insufficient"

    last = df.iloc[-1]

    close = safe_float(last["Close"])
    low = safe_float(last["Low"])

    ema9 = safe_float(last["EMA9"])
    ema20 = safe_float(last["EMA20"])

    rsi = safe_float(last["RSI"])
    adx = safe_float(last["ADX"])

    plus_di = safe_float(last["PLUS_DI"])
    minus_di = safe_float(last["MINUS_DI"])

    atr = safe_float(last["ATR"])
    rvol = safe_float(last["RVOL"])

    if close >= ema9 or ema9 >= ema20:
        return None, "intraday trend not bearish"

    if rsi >= 45:
        return None, "RSI not bearish"

    if adx < 18:
        return None, "intraday ADX too low"

    if minus_di <= plus_di:
        return None, "negative DI confirmation missing"

    if rvol < MIN_RVOL:
        return None, "intraday volume too low"

    previous_low = safe_float(
        df["Low"].iloc[-21:-1].min()
    )

    if low >= previous_low:
        return None, "20-bar breakdown missing"

    if atr <= 0:
        return None, "invalid intraday ATR"

    entry = close

    recent_high = safe_float(
        df["High"].iloc[-6:].max()
    )

    stop = max(
        recent_high,
        entry + (0.8 * atr)
    )

    if stop <= entry:
        return None, "invalid short stop"

    risk = stop - entry
    target = entry - (MIN_RR_SHORT * risk)

    if target <= 0 or risk <= 0:
        return None, "invalid short target"

    return {
        "symbol": symbol,
        "name": symbol_name(symbol),
        "side": "SHORT",
        "strategy": "INTRADAY",
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "rr": round((entry - target) / risk, 2),
        "score": 80,
        "rsi": round(rsi, 2),
        "adx": round(adx, 2),
        "rvol": round(rvol, 2),
        "created_at": now_ist().isoformat(),
        "status": "WAITING_ENTRY"
    }, "qualified"


# ============================================================
# SIGNAL MANAGEMENT
# ============================================================

def active_symbol_exists(signals, symbol):
    for signal in signals:
        if (
            signal.get("symbol") == symbol
            and signal.get("status") in [
                "WAITING_ENTRY",
                "OPEN"
            ]
        ):
            return True

    return False


def create_signal(candidate, signals):
    signal = candidate.copy()

    signal["id"] = (
        symbol_name(signal["symbol"])
        + "_"
        + now_ist().strftime("%Y%m%d%H%M%S")
    )

    signal["entry_time"] = None
    signal["exit_time"] = None
    signal["exit_price"] = None
    signal["pnl_percent"] = None

    signal["version"] = VERSION

    signals.append(signal)

    return signal


def close_trade(signal, price, reason):
    entry = safe_float(signal.get("actual_entry", signal["entry"]))

    if entry <= 0:
        return

    if signal["side"] == "BUY":
        pnl = ((price - entry) / entry) * 100
    else:
        pnl = ((entry - price) / entry) * 100

    signal["status"] = "CLOSED"
    signal["exit_price"] = round(price, 2)
    signal["exit_time"] = now_ist().isoformat()
    signal["pnl_percent"] = round(pnl, 2)
    signal["exit_reason"] = reason

    log.info(
        "Closed %s %s P&L %.2f%%",
        signal["symbol"],
        signal["side"],
        pnl
    )


# ============================================================
# PAPER TRADE MONITOR
# ============================================================

def monitor_signals(signals, history):
    messages = []

    current = now_ist()
    current_time = current.time()

    for signal in signals:

        status = signal.get("status")

        if status not in ["WAITING_ENTRY", "OPEN"]:
            continue

        symbol = signal["symbol"]
        side = signal["side"]
        strategy = signal["strategy"]

        # ----------------------------------------------------
        # Expire old waiting signals
        # ----------------------------------------------------

        try:
            created = datetime.fromisoformat(
                signal["created_at"]
            )

            if created.tzinfo is None:
                created = created.replace(tzinfo=IST)

            age = current - created

        except Exception:
            age = timedelta(days=999)

        if status == "WAITING_ENTRY":

            if strategy == "INTRADAY":
                if current_time >= SQUARE_OFF_TIME:
                    signal["status"] = "EXPIRED"
                    signal["exit_reason"] = "intraday entry expired"

                    messages.append(
                        f"⌛ EXPIRED: {signal['name']} SHORT\n"
                        f"Reason: Intraday entry window closed."
                    )
                    continue

            elif age > timedelta(days=MAX_SWING_ENTRY_AGE_DAYS):
                signal["status"] = "EXPIRED"
                signal["exit_reason"] = "swing entry expired"

                messages.append(
                    f"⌛ EXPIRED: {signal['name']} BUY\n"
                    f"Reason: Entry window expired."
                )
                continue

        # ----------------------------------------------------
        # Download recent intraday candles
        # ----------------------------------------------------

        df = download_intraday(symbol)

        if df.empty:
            continue

        last_price = safe_float(df["Close"].iloc[-1])

        if last_price <= 0:
            continue

        # ----------------------------------------------------
        # Waiting entry
        # ----------------------------------------------------

        if status == "WAITING_ENTRY":

            entry = safe_float(signal["entry"])

            if strategy == "INTRADAY" and current_time >= SQUARE_OFF_TIME:
                signal["status"] = "EXPIRED"
                signal["exit_reason"] = "intraday entry cutoff"

                continue

            if side == "BUY":
                triggered = safe_float(df["High"].iloc[-1]) >= entry
            else:
                triggered = safe_float(df["Low"].iloc[-1]) <= entry

            if not triggered:
                continue

            signal["status"] = "OPEN"
            signal["actual_entry"] = round(entry, 2)
            signal["entry_time"] = current.isoformat()

            messages.append(
                f"🟢 PAPER ENTRY\n"
                f"{signal['name']} ({side})\n"
                f"Entry: {entry:.2f}\n"
                f"Stop: {signal['stop']:.2f}\n"
                f"Target: {signal['target']:.2f}\n"
                f"Strategy: {strategy}"
            )

            status = "OPEN"

        # ----------------------------------------------------
        # Open trade monitoring
        # ----------------------------------------------------

        if status != "OPEN":
            continue

        entry = safe_float(
            signal.get("actual_entry", signal["entry"])
        )

        stop = safe_float(signal["stop"])
        target = safe_float(signal["target"])

        candle_high = safe_float(df["High"].iloc[-1])
        candle_low = safe_float(df["Low"].iloc[-1])

        exit_reason = None
        exit_price = None

        if side == "BUY":

            # Conservative handling when stop and target
            # are both touched in the same candle.
            if candle_low <= stop:
                exit_reason = "STOP LOSS"
                exit_price = stop

            elif candle_high >= target:
                exit_reason = "TARGET HIT"
                exit_price = target

        else:

            if candle_high >= stop:
                exit_reason = "STOP LOSS"
                exit_price = stop

            elif candle_low <= target:
                exit_reason = "TARGET HIT"
                exit_price = target

        # Mandatory intraday square-off for short paper trades.
        if (
            exit_reason is None
            and strategy == "INTRADAY"
            and current_time >= SQUARE_OFF_TIME
        ):
            exit_reason = "INTRADAY SQUARE OFF"
            exit_price = last_price

        if exit_reason:

            close_trade(
                signal,
                exit_price,
                exit_reason
            )

            history.append(signal.copy())

            messages.append(
                f"🔴 PAPER EXIT\n"
                f"{signal['name']} ({side})\n"
                f"Exit: {exit_price:.2f}\n"
                f"Reason: {exit_reason}\n"
                f"P&L: {signal['pnl_percent']:.2f}%"
            )

    return messages


# ============================================================
# SCAN SLOT CONTROL
# ============================================================

def current_scan_slot():
    current = now_ist()

    half_hour = "A" if current.minute < 30 else "B"

    return current.strftime("%Y-%m-%d-%H-") + half_hour


def can_scan(state):
    current = now_ist()

    if current.weekday() >= 5:
        return False

    if not (MARKET_OPEN <= current.time() <= SHORT_ENTRY_CUTOFF):
        return False

    slot = current_scan_slot()

    if state.get("last_slot") == slot:
        return False

    return True

# ============================================================
# SCANNER MAIN LOOP
# ============================================================

def run_scanner():

    signals = load_json(SIGNALS_FILE, [])
    history = load_json(HISTORY_FILE, [])
    state = load_json(STATE_FILE, {})

    if not isinstance(signals, list):
        signals = []

    if not isinstance(history, list):
        history = []

    if not isinstance(state, dict):
        state = {}

    log.info("Starting GTF PRO SCANNER %s", VERSION)

    # --------------------------------------------------------
    # Monitor existing paper trades first
    # --------------------------------------------------------

    monitor_messages = monitor_signals(signals, history)

    for message in monitor_messages:
        send_telegram(message)

    save_json(SIGNALS_FILE, signals)
    save_json(HISTORY_FILE, history)

    # --------------------------------------------------------
    # Check market regime
    # --------------------------------------------------------

    market = market_regime()
    regime = market["regime"]

    log.info("Market regime: %s", regime)
    log.info("Nifty: %s", market["nifty"])

    # --------------------------------------------------------
    # Scan slot control
    # --------------------------------------------------------

    if not can_scan(state):

        report = (
            f"📊 GTF PRO SCANNER {VERSION}\n"
            f"Time: {now_ist().strftime('%d-%m-%Y %H:%M IST')}\n"
            f"Market: {regime}\n"
            f"Nifty: {market['nifty']}\n"
            f"Status: Outside scan window or slot already scanned."
        )

        log.info(report.replace("\n", " | "))

        save_json(SIGNALS_FILE, signals)
        save_json(HISTORY_FILE, history)

        return

    state["last_slot"] = current_scan_slot()

    # --------------------------------------------------------
    # Candidate scanning
    # --------------------------------------------------------

    candidates = []
    daily_ok = 0
    intraday_ok = 0
    failures = 0
    checked = 0

    rejection_reasons = {}

    def reject(reason):
        rejection_reasons[reason] = (
            rejection_reasons.get(reason, 0) + 1
        )

    for symbol in STOCKS:

        if len(candidates) >= MAX_NEW_SIGNALS:
            break

        if active_symbol_exists(signals, symbol):
            reject("already active")
            continue

        checked += 1

        try:

            candidate = None
            reason = "no setup"

            # ------------------------------------------------
            # BULLISH: Swing BUY
            # ------------------------------------------------

            if regime == "BULLISH":

                daily = download_daily(symbol)

                if daily.empty:
                    failures += 1
                    reject("daily data unavailable")
                    continue

                daily_ok += 1

                candidate, reason = swing_candidate(
                    symbol,
                    daily
                )

            # ------------------------------------------------
            # BEARISH: Intraday SHORT
            # ------------------------------------------------

            elif regime == "BEARISH":

                intraday = download_intraday(symbol)

                if intraday.empty:
                    failures += 1
                    reject("intraday data unavailable")
                    continue

                intraday_ok += 1

                candidate, reason = short_candidate(
                    symbol,
                    intraday
                )

            # ------------------------------------------------
            # SIDEWAYS: Test both strategies
            # ------------------------------------------------

            else:

                daily = download_daily(symbol)

                if not daily.empty:
                    daily_ok += 1

                    candidate, reason = swing_candidate(
                        symbol,
                        daily
                    )

                if candidate is None:

                    intraday = download_intraday(symbol)

                    if not intraday.empty:
                        intraday_ok += 1

                        candidate, reason = short_candidate(
                            symbol,
                            intraday
                        )

            if candidate is None:
                reject(reason)
                continue

            candidates.append(candidate)

            log.info(
                "Qualified: %s %s score=%s",
                symbol,
                candidate["side"],
                candidate["score"]
            )

        except Exception as exc:

            failures += 1

            log.exception(
                "Error scanning %s: %s",
                symbol,
                exc
            )

            reject("unexpected error")

    # --------------------------------------------------------
    # Create new paper signals
    # --------------------------------------------------------

    new_signals = []

    for candidate in candidates[:MAX_NEW_SIGNALS]:

        if active_symbol_exists(signals, candidate["symbol"]):
            continue

        signal = create_signal(candidate, signals)

        new_signals.append(signal)

    # --------------------------------------------------------
    # Save scan state
    # --------------------------------------------------------

    state["last_run"] = now_ist().isoformat()
    state["last_regime"] = regime
    state["last_checked"] = checked
    state["last_candidates"] = len(candidates)

    state["scan_count"] = state.get("scan_count", 0) + 1

    state["history"] = state.get("history", [])[-MAX_SCAN_STATE:]

    save_json(SIGNALS_FILE, signals)
    save_json(HISTORY_FILE, history)
    save_json(STATE_FILE, state)

    # --------------------------------------------------------
    # Telegram messages for new signals
    # --------------------------------------------------------

    for signal in new_signals:

        message = (
            f"📈 GTF PRO PAPER SIGNAL {VERSION}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Stock: {signal['name']}\n"
            f"Side: {signal['side']}\n"
            f"Strategy: {signal['strategy']}\n"
            f"Entry: ₹{signal['entry']:.2f}\n"
            f"Stop Loss: ₹{signal['stop']:.2f}\n"
            f"Target: ₹{signal['target']:.2f}\n"
            f"Risk Reward: 1:{signal['rr']:.2f}\n"
            f"RSI: {signal['rsi']}\n"
            f"ADX: {signal['adx']}\n"
            f"Relative Volume: {signal['rvol']}\n"
            f"Status: WAITING ENTRY\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Paper trading only. Not a buy/sell guarantee."
        )

        send_telegram(message)

    # --------------------------------------------------------
    # Final diagnostic report
    # --------------------------------------------------------

    open_count = sum(
        1 for s in signals
        if s.get("status") == "OPEN"
    )

    waiting_count = sum(
        1 for s in signals
        if s.get("status") == "WAITING_ENTRY"
    )

    closed_count = sum(
        1 for s in history
        if s.get("status") == "CLOSED"
    )

    report = (
        f"📊 GTF PRO SCANNER {VERSION}\n"
        f"Time: {now_ist().strftime('%d-%m-%Y %H:%M IST')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Market: {regime}\n"
        f"Nifty: {market['nifty']}\n"
        f"EMA20: {market['ema20']}\n"
        f"EMA50: {market['ema50']}\n"
        f"ADX: {market['adx']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Stocks checked: {checked}\n"
        f"Daily data OK: {daily_ok}\n"
        f"Intraday data OK: {intraday_ok}\n"
        f"Data failures: {failures}\n"
        f"Qualified candidates: {len(candidates)}\n"
        f"New paper signals: {len(new_signals)}\n"
        f"Open: {open_count}\n"
        f"Waiting: {waiting_count}\n"
        f"Closed: {closed_count}\n"
    )

    if rejection_reasons:

        report += "\nTop rejection reasons:\n"

        sorted_reasons = sorted(
            rejection_reasons.items(),
            key=lambda item: item[1],
            reverse=True
        )

        for reason, count in sorted_reasons[:6]:

            report += f"• {reason}: {count}\n"

    if not new_signals:
        report += "\nNo new setup this run."

    report += (
        "\n\n⚠️ Paper trading only. "
        "Signals are not guaranteed profitable."
    )

    log.info("\n%s", report)

    send_telegram(report)


# ============================================================
# PROGRAM ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:
        run_scanner()

    except Exception as exc:

        log.exception("Scanner crashed: %s", exc)

        send_telegram(
            f"🚨 GTF PRO SCANNER {VERSION} ERROR\n"
            f"{str(exc)[:1000]}"
        )

        raise
