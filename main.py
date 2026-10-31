"""
GTF PRO SCANNER V11.1 — single-file paper-trading system
NSE cash equities only. No broker orders are placed.

Market regime:
  BULLISH  -> daily swing BUY setups
  BEARISH  -> intraday cash-equity SHORT setups
  SIDEWAYS -> no new entries

Important:
- Yahoo Finance data may be delayed, incomplete, or unavailable.
- GitHub Actions schedules are best-effort, not an execution guarantee.
- Paper-trading results are simulations, not evidence of future profitability.
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
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage" if BOT_TOKEN else ""
SIGNALS_FILE = "signals.json"
HISTORY_FILE = "trade_history.json"

# A deliberately smaller liquid-stock universe to reduce Yahoo rate limits.
# Add/remove NSE symbols here as needed. All symbols are cash-equity tickers.
STOCKS = [
    "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS","ICICIBANK.NS",
    "SBIN.NS","AXISBANK.NS","KOTAKBANK.NS","LT.NS","BHARTIARTL.NS",
    "ITC.NS","HINDUNILVR.NS","BAJFINANCE.NS","MARUTI.NS","TATAMOTORS.NS",
    "M&M.NS","SUNPHARMA.NS","TITAN.NS","ULTRACEMCO.NS","NTPC.NS",
    "POWERGRID.NS","ONGC.NS","COALINDIA.NS","TATASTEEL.NS","JSWSTEEL.NS",
    "HCLTECH.NS","WIPRO.NS","TECHM.NS","ADANIPORTS.NS","ASIANPAINT.NS",
    "BAJAJFINSV.NS","NESTLEIND.NS","GRASIM.NS","CIPLA.NS","DRREDDY.NS",
    "DIVISLAB.NS","APOLLOHOSP.NS","EICHERMOT.NS","HEROMOTOCO.NS","BAJAJ-AUTO.NS",
    "INDUSINDBK.NS","FEDERALBNK.NS","BANKBARODA.NS","PNB.NS","IDFCFIRSTB.NS",
    "DLF.NS","BEL.NS","HAL.NS","TRENT.NS","ZOMATO.NS"
]

MAX_NEW_SIGNALS = 5
MAX_ACTIVE_PER_SYMBOL = 1
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
SCAN_STATE_FILE = "scan_state.json"
DIAGNOSTICS = {"daily_download_ok": 0, "intraday_download_ok": 0, "download_fail": 0}
SQUARE_OFF_TIME = dtime(15, 20)
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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
        raise ValueError(f"{path} must contain a JSON list; refusing to overwrite it.")
    return data


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def telegram(message):
    if not TELEGRAM_URL or not CHAT_ID:
        logging.info("Telegram not configured; skipping notification.")
        return
    try:
        response = requests.post(
            TELEGRAM_URL,
            data={"chat_id": CHAT_ID, "text": message},
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:
        logging.warning("Telegram notification failed: %s", exc)


def clean_yf_frame(df):
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).title() for c in df.columns]
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in df.columns for c in required):
        return None
    df = df[required].copy()
    for c in required:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna()
    return df if not df.empty else None


def download_daily(symbol):
    try:
        df = yf.download(symbol, period="2y", interval="1d", auto_adjust=True,
                         progress=False, threads=False, timeout=20)
        df = clean_yf_frame(df)
        if df is None or len(df) < MIN_DAILY_ROWS:
            DIAGNOSTICS["download_fail"] += 1
            return None
        DIAGNOSTICS["daily_download_ok"] += 1
        return df
    except Exception as exc:
        DIAGNOSTICS["download_fail"] += 1
        logging.warning("Daily download failed for %s: %s", symbol, exc)
        return None


def download_intraday(symbol):
    try:
        df = yf.download(symbol, period="5d", interval="5m", auto_adjust=True,
                         progress=False, threads=False, timeout=20)
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
            candle_end = df.index[-1].to_pydatetime() + timedelta(minutes=5)
            if candle_end > current:
                df = df.iloc[:-1]
        if df.empty:
            DIAGNOSTICS["download_fail"] += 1
            return None
        age = (now_ist() - df.index[-1].to_pydatetime()).total_seconds() / 60
        if age < -5 or age > 20:
            DIAGNOSTICS["download_fail"] += 1
            return None
        DIAGNOSTICS["intraday_download_ok"] += 1
        return df
    except Exception as exc:
        DIAGNOSTICS["download_fail"] += 1
        logging.warning("Intraday download failed for %s: %s", symbol, exc)
        return None


def market_regime():
    df = download_daily("^NSEI")
    if df is None:
        return "SIDEWAYS", None, {}
    close = df["Close"]
    ema20 = EMAIndicator(close, window=20).ema_indicator()
    ema50 = EMAIndicator(close, window=50).ema_indicator()
    adx_obj = ADXIndicator(df["High"], df["Low"], close, window=14)
    pdi, mdi = adx_obj.adx_pos(), adx_obj.adx_neg()
    adx_value = adx_obj.adx().iloc[-1]
    c, e20, e50 = close.iloc[-1], ema20.iloc[-1], ema50.iloc[-1]
    details = {"ema20": round(float(e20), 2), "ema50": round(float(e50), 2),
               "adx": round(float(adx_value), 1),
               "plus_di": round(float(pdi.iloc[-1]), 1),
               "minus_di": round(float(mdi.iloc[-1]), 1)}
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
    adx_obj = ADXIndicator(df["High"], df["Low"], c, 14)
    adx = adx_obj.adx()
    pdi, mdi = adx_obj.adx_pos(), adx_obj.adx_neg()
    atr = AverageTrueRange(df["High"], df["Low"], c, 14).average_true_range()
    avg_vol = df["Volume"].rolling(20).mean()
    i = len(df) - 1
    vals = [ema20.iloc[i], ema50.iloc[i], ema200.iloc[i], rsi.iloc[i],
            adx.iloc[i], pdi.iloc[i], mdi.iloc[i], atr.iloc[i], avg_vol.iloc[i]]
    if any(pd.isna(x) for x in vals):
        return None
    price = float(c.iloc[i])
    av = float(atr.iloc[i])
    rvol = float(df["Volume"].iloc[i] / avg_vol.iloc[i]) if avg_vol.iloc[i] else 0
    extension = (price - float(ema20.iloc[i])) / av if av else 99
    prior_high = float(df["High"].iloc[-21:-1].max())
    checks = [
        price > ema20.iloc[i] > ema50.iloc[i] > ema200.iloc[i],
        0 <= extension <= 2.0,
        MIN_RSI <= rsi.iloc[i] <= MAX_RSI,
        adx.iloc[i] >= MIN_ADX and pdi.iloc[i] > mdi.iloc[i],
        rvol >= MIN_RVOL,
        macd.macd().iloc[i] > macd.macd_signal().iloc[i],
        price > prior_high,
    ]
    if not all(checks):
        return None
    entry = float(df["High"].iloc[i] + 0.05 * av)
    recent_low = float(df["Low"].iloc[-10:].min())
    stop = max(recent_low, entry - 1.5 * av)
    risk = entry - stop
    if risk <= 0 or risk > 2 * av:
        return None
    target = entry + MIN_RR_SWING * risk
    return {
        "symbol": symbol, "strategy": "V11_SWING", "direction": "BUY",
        "entry_trigger": round(entry, 2), "stop_loss": round(stop, 2),
        "target": round(target, 2), "score": 100, "rvol": round(rvol, 2),
        "rsi": round(float(rsi.iloc[i]), 1), "adx": round(float(adx.iloc[i]), 1),
        "reward_risk": MIN_RR_SWING, "signal_candle": str(df.index[i].date())
    }


def short_candidate(symbol):
    df = download_intraday(symbol)
    if df is None or len(df) < 60:
        return None
    c = df["Close"]
    ema9 = EMAIndicator(c, 9).ema_indicator()
    ema20 = EMAIndicator(c, 20).ema_indicator()
    rsi = RSIIndicator(c, 14).rsi()
    adx_obj = ADXIndicator(df["High"], df["Low"], c, 14)
    adx = adx_obj.adx()
    mdi, pdi = adx_obj.adx_neg(), adx_obj.adx_pos()
    atr = AverageTrueRange(df["High"], df["Low"], c, 14).average_true_range()
    avg_vol = df["Volume"].rolling(20).mean()
    i = len(df) - 1
    if any(pd.isna(x) for x in [ema9.iloc[i], ema20.iloc[i], rsi.iloc[i],
                                adx.iloc[i], mdi.iloc[i], pdi.iloc[i],
                                atr.iloc[i], avg_vol.iloc[i]]):
        return None
    price = float(c.iloc[i])
    av = float(atr.iloc[i])
    rvol = float(df["Volume"].iloc[i] / avg_vol.iloc[i]) if avg_vol.iloc[i] else 0
    breakdown = float(df["Low"].iloc[-21:-1].min())
    if not (price < ema9.iloc[i] < ema20.iloc[i] and price < breakdown
            and rsi.iloc[i] < 45 and adx.iloc[i] >= 18
            and mdi.iloc[i] > pdi.iloc[i] and rvol >= 1.3):
        return None
    entry = price
    stop = max(float(df["High"].iloc[-6:].max()), entry + 0.8 * av)
    risk = stop - entry
    if risk <= 0 or risk > 2.5 * av:
        return None
    target = entry - MIN_RR_SHORT * risk
    if target <= 0:
        return None
    return {
        "symbol": symbol, "strategy": "V11_INTRADAY_SHORT", "direction": "SHORT",
        "entry_trigger": round(entry, 2), "stop_loss": round(stop, 2),
        "target": round(target, 2), "score": 85, "rvol": round(rvol, 2),
        "rsi": round(float(rsi.iloc[i]), 1), "adx": round(float(adx.iloc[i]), 1),
        "reward_risk": MIN_RR_SHORT, "signal_candle": str(df.index[i])
    }


def active_symbol_set(signals):
    return {
        s.get("symbol") for s in signals
        if s.get("status") in ("WAITING_ENTRY", "OPEN")
    }


def create_record(candidate):
    return {
        "signal_id": str(uuid.uuid4()),
        **candidate,
        "status": "WAITING_ENTRY",
        "created_at": stamp(),
        "entry_price": None,
        "entered_at": None,
        "exit_price": None,
        "exited_at": None,
        "exit_reason": None,
        "strategy_version": "V11.1"
    }


def monitor_one(signal, history, current_time):
    symbol = signal["symbol"]
    direction = signal.get("direction", "BUY")
    short = direction == "SHORT"
    # Intraday short trades are never carried overnight.
    if short and current_time.time() >= SQUARE_OFF_TIME:
        if signal["status"] == "OPEN":
            px = signal.get("last_price") or signal["entry_price"]
            close_signal(signal, history, float(px), "MANDATORY_SQUARE_OFF")
        else:
            signal["status"] = "EXPIRED"
            signal["exit_reason"] = "NO_ENTRY_BEFORE_SQUARE_OFF"
            signal["exited_at"] = stamp()
        return

    df = download_intraday(symbol)
    if df is None:
        return
    candle = df.iloc[-1]
    high, low, op, close = map(float, [candle["High"], candle["Low"], candle["Open"], candle["Close"]])
    signal["last_price"] = close

    entry_trigger = float(signal["entry_trigger"])
    sl, target = float(signal["stop_loss"]), float(signal["target"])
    if signal["status"] == "WAITING_ENTRY":
        created = datetime.fromisoformat(signal["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=IST)
        age_seconds = (current_time - created).total_seconds()
        if short:
            expired = age_seconds > MAX_ENTRY_AGE_MINUTES * 60
        else:
            expired = age_seconds > MAX_SWING_ENTRY_AGE_DAYS * 24 * 60 * 60
        if expired:
            signal["status"] = "EXPIRED"
            signal["exit_reason"] = "ENTRY_WINDOW_EXPIRED"
            signal["exited_at"] = stamp()
            return
        triggered = (low <= entry_trigger) if short else (high >= entry_trigger)
        if not triggered:
            return
        # Conservative gap handling and ambiguous same-candle stop rule.
        entry = min(entry_trigger, op) if short and op < entry_trigger else max(entry_trigger, op) if not short and op > entry_trigger else entry_trigger
        if short:
            if high >= sl:
                signal["status"] = "EXPIRED"
                signal["exit_reason"] = "STOP_TOUCHED_ON_ENTRY_CANDLE"
                signal["exited_at"] = stamp()
                return
        else:
            if low <= sl:
                signal["status"] = "EXPIRED"
                signal["exit_reason"] = "STOP_TOUCHED_ON_ENTRY_CANDLE"
                signal["exited_at"] = stamp()
                return
        signal["status"] = "OPEN"
        signal["entry_price"] = round(entry, 2)
        signal["entered_at"] = stamp()
        telegram(f"🟢 V11 PAPER ENTRY\n{symbol} {direction}\nEntry: {entry:.2f}\nSL: {sl:.2f}\nTarget: {target:.2f}")
        return

    if signal["status"] != "OPEN":
        return
    entry = float(signal["entry_price"])
    if short:
        if high >= sl:
            close_signal(signal, history, sl if op <= sl else op, "STOP_LOSS")
        elif low <= target:
            close_signal(signal, history, target if op >= target else op, "TARGET")
    else:
        if low <= sl:
            close_signal(signal, sl if op >= sl else op, "STOP_LOSS")
        elif high >= target:
            close_signal(signal, target if op <= target else op, "TARGET")


def close_signal(signal, history, exit_price, reason):
    if signal.get("status") == "CLOSED":
        return
    entry = float(signal["entry_price"])
    direction = signal.get("direction", "BUY")
    pnl = ((entry - exit_price) / entry * 100) if direction == "SHORT" else ((exit_price - entry) / entry * 100)
    signal.update({
        "status": "CLOSED", "exit_price": round(exit_price, 2),
        "exited_at": stamp(), "exit_reason": reason, "pnl_percent": round(pnl, 2)
    })
    if not any(x.get("signal_id") == signal.get("signal_id") for x in history):
        history.append({
            "signal_id": signal["signal_id"], "symbol": signal["symbol"],
            "strategy": signal.get("strategy"), "direction": direction,
            "entry_price": entry, "exit_price": round(exit_price, 2),
            "pnl_percent": round(pnl, 2), "exit_reason": reason,
            "entered_at": signal.get("entered_at"), "exited_at": signal["exited_at"]
        })
    telegram(f"🏁 V11 PAPER EXIT\n{signal['symbol']} {direction}\nExit: {exit_price:.2f}\nReason: {reason}\nP&L: {pnl:.2f}%")


def main():
    current = now_ist()
    signals = load_json(SIGNALS_FILE)
    history = load_json(HISTORY_FILE)
    scan_state = load_json(SCAN_STATE_FILE)

    # Manage existing positions first on every run.
    for signal in signals:
        if signal.get("status") in ("WAITING_ENTRY", "OPEN") and signal.get("symbol"):
            try:
                monitor_one(signal, history, current)
            except Exception as exc:
                logging.exception("Monitor error for %s: %s", signal.get("symbol"), exc)
            time.sleep(0.15)

    regime, nifty, market_details = market_regime()
    logging.info("Market regime=%s Nifty=%s details=%s", regime, nifty, market_details)
    new_records = []
    in_market_hours = MARKET_OPEN <= current.time() <= MARKET_CLOSE

    # One scan per half-hour slot; tolerates delayed GitHub Actions starts.
    slot = current.strftime("%Y-%m-%d-") + ("A" if current.minute < 30 else "B")
    already_scanned = slot in scan_state
    scan_window = in_market_hours and (0 <= current.minute <= 14 or 30 <= current.minute <= 44)
    scan_attempted = False
    scan_count = 0
    candidate_count = 0
    filtered_count = 0

    if scan_window and not already_scanned and regime in ("BULLISH", "BEARISH"):
        scan_attempted = True
        blocked = active_symbol_set(signals)
        candidates = []
        for symbol in STOCKS:
            if symbol in blocked:
                continue
            scan_count += 1
            try:
                candidate = swing_candidate(symbol) if regime == "BULLISH" else short_candidate(symbol)
                if candidate:
                    candidates.append(candidate)
            except Exception as exc:
                logging.warning("Scan error for %s: %s", symbol, exc)
            time.sleep(0.15)

        candidate_count = len(candidates)
        filtered_count = max(0, scan_count - candidate_count)
        candidates.sort(key=lambda x: (x["score"], x["rvol"]), reverse=True)
        for candidate in candidates[:MAX_NEW_SIGNALS]:
            record = create_record(candidate)
            signals.append(record)
            new_records.append(record)
            blocked.add(candidate["symbol"])

        scan_state.append(slot)
        scan_state = scan_state[-20:]

    save_json(SIGNALS_FILE, signals)
    save_json(HISTORY_FILE, history)
    save_json(SCAN_STATE_FILE, scan_state)

    open_count = sum(s.get("status") == "OPEN" for s in signals)
    waiting_count = sum(s.get("status") == "WAITING_ENTRY" for s in signals)
    if not in_market_hours:
        scan_status = "Outside market hours"
    elif regime == "SIDEWAYS":
        scan_status = "Skipped: Nifty is sideways"
    elif already_scanned:
        scan_status = "Already scanned this 30-minute slot"
    elif scan_attempted:
        scan_status = "Completed"
    else:
        scan_status = "Waiting for scan window"

    report = (
        f"📊 GTF PRO SCANNER V11.1\n"
        f"Time: {current.strftime('%d-%m-%Y %H:%M')} IST\n"
        f"Market regime: {regime}\n"
        f"Nifty: {nifty if nifty is not None else 'Unavailable'}\n"
        f"EMA20: {market_details.get('ema20', 'NA')} | EMA50: {market_details.get('ema50', 'NA')}\n"
        f"ADX: {market_details.get('adx', 'NA')} | +DI: {market_details.get('plus_di', 'NA')} | -DI: {market_details.get('minus_di', 'NA')}\n"
        f"Scan status: {scan_status}\n"
        f"Stocks checked: {scan_count} | Data OK daily/intraday: {DIAGNOSTICS['daily_download_ok']}/{DIAGNOSTICS['intraday_download_ok']}\n"
        f"Data failures: {DIAGNOSTICS['download_fail']} | Filtered/no setup: {filtered_count}\n"
        f"Qualified candidates: {candidate_count}\n"
        f"New paper signals: {len(new_records)}\n"
        f"Open: {open_count} | Waiting: {waiting_count}\n"
        f"Universe: {len(STOCKS)} liquid NSE stocks\n"
        f"{'No new setup this run.' if not new_records else 'New signals: ' + ', '.join(x['symbol'] for x in new_records)}\n"
        f"Paper trading only — no broker orders."
    )
    logging.info(report)
    if new_records or (scan_window and not already_scanned) or current.minute in (0, 30):
        telegram(report)

if __name__ == "__main__":
    main()
