import math
import time
import pandas as pd
import yfinance as yf

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

# Cache the market trend globally so it only runs once per scanning session
GLOBAL_MARKET_TREND = None

# ==========================================
# SAFE FLOAT
# ==========================================
def safe_float(value, default=0):
    try:
        if hasattr(value, "iloc"):
            value = value.iloc[-1]
        value = float(value)
        if math.isnan(value): 
            return default 
        return value 
    except: 
        return default 

# ==========================================
# DOWNLOAD WITH RETRY
# ==========================================
def download_stock(symbol):
    for attempt in range(3): 
        try: 
            df = yf.download( 
                symbol, 
                period="1y", 
                interval="1d", 
                auto_adjust=True, 
                progress=False, 
                threads=False 
            ) 
            if not df.empty: 
                # Handles recent yfinance multi-index structural changes safely
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df 
        except Exception: 
            pass 
        time.sleep(2) 
    return None 

# ==========================================
# MARKET TREND (Optimized to run once)
# ==========================================
def get_market_trend():
    global GLOBAL_MARKET_TREND
    if GLOBAL_MARKET_TREND is not None:
        return GLOBAL_MARKET_TREND

    try: 
        nifty = download_stock("^NSEI") 
        if nifty is None or nifty.empty: 
            GLOBAL_MARKET_TREND = "🟢 Bullish"
            return GLOBAL_MARKET_TREND
            
        close = nifty["Close"].squeeze() 
        ema20 = EMAIndicator(close, window=20).ema_indicator() 
        ema50 = EMAIndicator(close, window=50).ema_indicator() 
        
        if close.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1]:
            GLOBAL_MARKET_TREND = "🟢 Bullish"
        else:
            GLOBAL_MARKET_TREND = "🔴 Bearish"
    except: 
        GLOBAL_MARKET_TREND = "🟢 Bullish"
        
    return GLOBAL_MARKET_TREND

# ==========================================
# MAIN SCANNER
# ==========================================
def scan_stock(symbol):
    try: 
        df = download_stock(symbol) 
        if df is None or df.empty: 
            return None 
        if len(df) < 200: 
            return None 
            
        close = df["Close"].squeeze() 
        high = df["High"].squeeze() 
        low = df["Low"].squeeze() 
        volume = df["Volume"].squeeze() 
        
        # Calculate Technical Indicators
        ema20 = EMAIndicator(close, window=20).ema_indicator().bfill() 
        ema50 = EMAIndicator(close, window=50).ema_indicator().bfill() 
        ema200 = EMAIndicator(close, window=200).ema_indicator().bfill() 
        rsi = RSIIndicator(close, window=14).rsi().fillna(50) 
        
        macd = MACD(close) 
        macd_line = macd.macd() 
        signal_line = macd.macd_signal() 
        
        adx = ADXIndicator(high=high, low=low, close=close, window=14).adx().fillna(0) 
        atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range().fillna(0) 
        avg_volume = volume.rolling(20).mean() 
        
        # Current Values
        buy = round(safe_float(close.iloc[-1]), 2) 
        rsi_value = round(safe_float(rsi.iloc[-1]), 2) 
        adx_value = round(safe_float(adx.iloc[-1]), 1) 
        atr_value = round(safe_float(atr.iloc[-1]), 2) 
        
        # Volume Calculation
        last_volume = safe_float(volume.iloc[-1])
        last_avg_volume = safe_float(avg_volume.iloc[-1])
        rvol = round(last_volume / last_avg_volume, 2) if last_avg_volume > 0 else 1.0
        
        score = 0 
        reasons = [] 
        
        # 1. EMA Rules
        if buy > ema20.iloc[-1]: 
            score += 20 
            reasons.append("✅ Price above EMA20") 
        if ema20.iloc[-1] > ema50.iloc[-1]: 
            score += 20 
            reasons.append("✅ EMA20 above EMA50") 
        if ema50.iloc[-1] > ema200.iloc[-1]: 
            score += 20 
            reasons.append("✅ EMA50 above EMA200") 
            
        # 2. RSI Rules
        if 55 <= rsi_value <= 70: 
            score += 20 
            reasons.append(f"✅ RSI Bullish ({rsi_value})") 
            
        # 3. MACD Rules
        if macd_line.iloc[-1] > signal_line.iloc[-1]: 
            score += 10 
            reasons.append("✅ MACD Bullish") 
            
        # 4. ADX Rules
        if adx_value >= 30: 
            score += 15 
            reasons.append(f"✅ Strong Trend ({adx_value})") 
        elif adx_value >= 25: 
            score += 10 
            reasons.append(f"✅ Good Trend ({adx_value})") 
            
        # 5. Relative Volume Rules
        if rvol >= 2: 
            score += 15 
            reasons.append(f"✅ High Relative Volume ({rvol}x)") 
        elif rvol >= 1.5: 
            score += 10 
            reasons.append(f"✅ Relative Volume ({rvol}x)") 
        elif rvol >= 1.2: 
            score += 5 
            reasons.append(f"✅ Relative Volume ({rvol}x)") 
            
        # 6. Breakout Rule (Looking strictly at the previous 20 completed days)
        past_20_days_high = high.iloc[-21:-1].max()
        breakout = buy > past_20_days_high 
        if breakout: 
            score += 10 
            reasons.append("✅ 20-Day Breakout") 
            
        # Filter weak stocks early before processing risk
        if score < 40: 
            return None 
            
        # Trend & Confidence Matrix
        if score >= 110: 
            trend = "🟢 Super Bullish" 
            confidence = "💎 Institutional" 
        elif score >= 90: 
            trend = "🟢 Strong Bullish" 
            confidence = "🔥 Excellent" 
        elif score >= 75: 
            trend = "🟢 Bullish" 
            confidence = "✅ High" 
        elif score >= 60: 
            trend = "🟡 Moderate" 
            confidence = "⚠ Medium" 
        else: 
            trend = "🔴 Weak" 
            confidence = "❌ Low" 
            
        # Risk Management Configurations
        if atr_value <= 0: 
            atr_value = buy * 0.02 
            
        sl = round(buy - (1.5 * atr_value), 2) 
        if sl >= buy: 
            sl = round(buy * 0.98, 2) 
            
        risk = buy - sl 
        if risk <= 0: 
            risk = buy * 0.02 
            
        t1 = round(buy + risk, 2) 
        t2 = round(buy + (2 * risk), 2) 
        t3 = round(buy + (3 * risk), 2) 
        
        return { 
            "symbol": symbol.replace(".NS", ""), 
            "score": score, 
            "trend": trend, 
            "confidence": confidence, 
            "market": get_market_trend(), 
            "reason": "\n".join(reasons), 
            "buy": buy, 
            "sl": sl, 
            "t1": t1, 
            "t2": t2, 
            "t3": t3, 
            "rsi": rsi_value, 
            "rvol": rvol, 
            "adx": adx_value, 
            "atr": atr_value 
        } 
    except Exception as e: 
        print(f"{symbol}: {e}") 
        return None
