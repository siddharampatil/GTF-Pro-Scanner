def market_is_bullish():
    """Check Nifty trend and print diagnostic values."""
    global _MARKET_BULLISH

    if _MARKET_BULLISH is not None:
        return _MARKET_BULLISH

    df = download_data("^NSEI")

    if df is None:
        print("MARKET DIAGNOSTIC: Nifty data unavailable")
        _MARKET_BULLISH = False
        return False

    pos = latest_completed_position(df)

    if pos is None:
        print("MARKET DIAGNOSTIC: No completed Nifty candle")
        _MARKET_BULLISH = False
        return False

    close_series = df["Close"]

    ema20_series = EMAIndicator(
        close_series, window=20
    ).ema_indicator()

    ema50_series = EMAIndicator(
        close_series, window=50
    ).ema_indicator()

    close = float(close_series.iloc[pos])
    ema20 = float(ema20_series.iloc[pos])
    ema50 = float(ema50_series.iloc[pos])
    candle_date = str(df.index[pos])

    print("========== NIFTY MARKET DIAGNOSTIC ==========")
    print("Candle date:", candle_date)
    print(f"Nifty close: {close:.2f}")
    print(f"EMA 20:      {ema20:.2f}")
    print(f"EMA 50:      {ema50:.2f}")
    print("Close > EMA20:", close > ema20)
    print("EMA20 > EMA50:", ema20 > ema50)

    _MARKET_BULLISH = close > ema20 > ema50

    print(
        "MARKET FILTER:",
        "BULLISH" if _MARKET_BULLISH else "NOT BULLISH"
    )
    print("=============================================")

    return _MARKET_BULLISH