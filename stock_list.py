def get_stock_list():
    with open("stocks.txt", "r") as f:
        stocks = [line.strip() for line in f if line.strip()]
    return stocks