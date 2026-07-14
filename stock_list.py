def get_stock_list():
    with open("stocks.txt", "r") as f:
        return [line.strip() for line in f if line.strip()]