import os
import pandas as pd

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"


def load_symbols(df):
    stocks = (
        df["Symbol"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )
    return [f"{s}.NS" for s in stocks]


def get_stock_list():

    # Try downloading from NSE
    try:
        print("Downloading NIFTY500 list...")
        df = pd.read_csv(NIFTY500_URL)

        if len(df) > 400:
            print(f"Downloaded {len(df)} stocks.")
            return load_symbols(df)

    except Exception as e:
        print(f"NSE download failed: {e}")

    # Use local CSV
    try:
        print("Loading local nifty500.csv...")
        df = pd.read_csv("nifty500.csv")

        if len(df) > 400:
            print(f"Loaded {len(df)} stocks from local file.")
            return load_symbols(df)

    except Exception as e:
        print(f"Local CSV failed: {e}")

    # Emergency fallback
    print("Using emergency fallback list.")

    return [
        "RELIANCE.NS",
        "TCS.NS",
        "INFY.NS",
        "HDFCBANK.NS",
        "ICICIBANK.NS",
        "SBIN.NS",
        "AXISBANK.NS",
        "KOTAKBANK.NS",
        "BHARTIARTL.NS",
        "LT.NS",
        "ITC.NS",
        "HCLTECH.NS",
        "ULTRACEMCO.NS",
        "MARUTI.NS",
        "BAJFINANCE.NS",
        "TITAN.NS",
        "ASIANPAINT.NS",
        "SUNPHARMA.NS",
        "NTPC.NS",
        "POWERGRID.NS",
    ]