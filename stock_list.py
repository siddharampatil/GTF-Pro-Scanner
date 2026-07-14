from nsetools import Nse


def get_stock_list():
    nse = Nse()

    stocks = []

    for symbol in nse.get_stock_codes().keys():
        if symbol != "SYMBOL":
            stocks.append(symbol + ".NS")

    return stocks