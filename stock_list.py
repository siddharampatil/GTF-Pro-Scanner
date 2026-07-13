import pandas as pd

def get_stock_list():
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    df = pd.read_csv(url)

    symbols = []

    for symbol in df["SYMBOL"]:
        symbols.append(symbol + ".NS")

    return symbols