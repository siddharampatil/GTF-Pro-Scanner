import pandas as pd

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"


def get_stock_list():

    try:

        df = pd.read_csv(NIFTY500_URL)

        stocks = (
            df["Symbol"]
            .dropna()
            .astype(str)
            .str.strip()
            .unique()
            .tolist()
        )

        return [f"{symbol}.NS" for symbol in stocks]

    except Exception as e:

        print(f"Unable to download NIFTY500 list: {e}")

        # Fallback list
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
            "POWERGRID.NS"

        ]