
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
