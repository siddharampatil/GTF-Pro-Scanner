import pandas as pd

URLS = [
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    "https://archives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
    "https://archives.nseindia.com/content/fo/fo_mktlots.csv"
]


def get_stock_list():

    stocks = set()

    for url in URLS:

        try:

            df = pd.read_csv(url)

            for col in df.columns:

                if col.lower() == "symbol":
                    symbols = (
                        df[col]
                        .dropna()
                        .astype(str)
                        .str.strip()
                    )

                    for s in symbols:
                        if s:
                            stocks.add(s + ".NS")

        except Exception as e:
            print(f"Unable to load {url}: {e}")

    stocks = sorted(list(stocks))

    print(f"Loaded {len(stocks)} stocks")

    return stocks