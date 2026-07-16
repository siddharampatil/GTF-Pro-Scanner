import pandas as pd

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

FALLBACK_STOCKS = [
    "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS","ICICIBANK.NS",
    "SBIN.NS","LT.NS","ITC.NS","BHARTIARTL.NS","AXISBANK.NS",
    "KOTAKBANK.NS","MARUTI.NS","BAJFINANCE.NS","ASIANPAINT.NS",
    "TITAN.NS","ULTRACEMCO.NS","SUNPHARMA.NS","ADANIPORTS.NS",
    "NTPC.NS","POWERGRID.NS"
]

def get_stock_list():
    try:
        df = pd.read_csv(NIFTY500_URL)
        return [f"{s}.NS" for s in df["Symbol"].dropna().unique()]
    except Exception as e:
        print("Using fallback list:", e)
        return FALLBACK_STOCKS