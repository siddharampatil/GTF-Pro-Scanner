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