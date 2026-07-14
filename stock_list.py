import pandas as pd

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

def get_stock_list():
    try:
        df = pd.read_csv(NIFTY500_URL)

        stocks = []

        for symbol in df["Symbol"]:
            stocks.append(f"{symbol}.NS")

        return stocks

    except Exception as e:
        print("Error downloading NIFTY 500 list:", e)

        return [
            "RELIANCE.NS",
            "TCS.NS",
            "INFY.NS",
            "HDFCBANK.NS",
            "ICICIBANK.NS"
        ]