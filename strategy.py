import math
import time
import yfinance as yf

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


# ==========================================
# SAFE FLOAT
# ==========================================

def safe_float(value, default=0):
    try:
        value = float(value)

        if math.isnan(value):
            return default

        return value

    except:
        return default


# ==========================================
# DOWNLOAD WITH RETRY
# ==========================================

def download_stock(symbol):

    for attempt in range(3):

        try:

            df = yf.download(
                symbol,
                period="1y",
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False
            )

            if not df.empty:
                return df

        except Exception:
            pass

        time.sleep(2)

    return None


# ==========================================
# MARKET TREND
# ==========================================

def market_is_bullish():

    try:

        nifty = download_stock("^NSEI")

        if nifty is None:
            return True

        close = nifty["Close"].squeeze()

        ema20 = EMAIndicator(close, window=20).ema_indicator()
        ema50 = EMAIndicator(close, window=50).ema_indicator()

        return close.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1]

    except:

        return True


# ==========================================
# MAIN SCANNER
# ==========================================

def scan_stock(symbol):

    try:

        df = download_stock(symbol)

        if df is None:
            return None

        if len(df) < 200:
            return None