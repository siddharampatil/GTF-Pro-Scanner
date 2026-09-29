import time
import pandas as pd
import yfinance as yf

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


# =========================================================
# GTF PRO SCANNER V8.1
# Strategy engine only
# =========================================================

def safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


# =========================================================
# DATA DOWNLOAD
# =========================================================

def download_stock(symbol, interval="1d", period="2y"):

    for attempt in range(3):

        try:

            df = yf.download(
                tickers=symbol,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False
            )

            if df is None or df.empty:
                time.sleep(1)
                continue

            # Fix yfinance MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.dropna()

            if len(df) >= 200 or interval == "1wk":
                return df

        except Exception as e:
            print(f"{symbol}: {e}")

        time.sleep(1)

    return None


# =========================================================
# MARKET TREND
# =========================================================

def get_market_trend():

    try:

        nifty = download_stock("^NSEI")

        if nifty is None:
            return "🟡 Unknown"

        close = nifty["Close"]

        ema20 = EMAIndicator(close, 20).ema_indicator()
        ema50 = EMAIndicator(close, 50).ema_indicator()

        last_close = safe_float(close.iloc[-1])
        last_ema20 = safe_float(ema20.iloc[-1])
        last_ema50 = safe_float(ema50.iloc[-1])

        if last_close > last_ema20 > last_ema50:
            return "🟢 Bullish"

        if last_close < last_ema20 < last_ema50:
            return "🔴 Bearish"

        return "🟡 Neutral"

    except Exception:
        return "🟡 Unknown"


MARKET_CONDITION = get_market_trend()


# =========================================================
# DEMAND ZONE
# =========================================================

def identify_demand_zone(close, high, low, lookback=100):

    try:

        body = (close - close.shift(1)).abs()
        avg_body = body.rolling(20).mean()

        start = max(20, len(close) - lookback)

        for i in range(len(close) - 2, start, -1):

            current_body = safe_float(body.iloc[i])
            average_body = safe_float(avg_body.iloc[i])

            if average_body <= 0:
                continue

            bullish = close.iloc[i] > close.iloc[i - 1]

            if bullish and current_body > average_body * 1.5:

                zone_low = safe_float(low.iloc[i - 1])
                zone_high = safe_float(high.iloc[i - 1])

                if zone_low > 0 and zone_high > zone_low:
                    return zone_low, zone_high

    except Exception:
        pass

    return None


# =========================================================
# MAIN SCANNER
# =========================================================

def scan_stock(symbol):

    try:

        df = download_stock(symbol)

        if df is None or len(df) < 200:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        # =================================================
        # INDICATORS
        # =================================================

        ema20 = EMAIndicator(close, 20).ema_indicator()
        ema50 = EMAIndicator(close, 50).ema_indicator()
        ema200 = EMAIndicator(close, 200).ema_indicator()

        rsi = RSIIndicator(close, 14).rsi()

        macd = MACD(close)

        macd_line = macd.macd()
        macd_signal = macd.macd_signal()
        macd_hist = macd.macd_diff()

        adx = ADXIndicator(
            high,
            low,
            close,
            14
        ).adx()

        atr = AverageTrueRange(
            high,
            low,
            close,
            14
        ).average_true_range()

        avg_volume = volume.rolling(20).mean()

        # =================================================
        # CURRENT VALUES
        # =================================================

        buy = safe_float(close.iloc[-1])

        ema20_v = safe_float(ema20.iloc[-1])
        ema50_v = safe_float(ema50.iloc[-1])
        ema200_v = safe_float(ema200.iloc[-1])

        rsi_v = safe_float(rsi.iloc[-1])
        adx_v = safe_float(adx.iloc[-1])
        atr_v = safe_float(atr.iloc[-1])

        current_volume = safe_float(volume.iloc[-1])
        average_volume = safe_float(avg_volume.iloc[-1], 1)

        rvol = current_volume / average_volume

        if buy <= 0:
            return None

        if atr_v <= 0:
            return None

        # =================================================
        # BASIC DATA VALIDATION
        # =================================================

        if any(
            pd.isna(x)
            for x in [
                ema20_v,
                ema50_v,
                ema200_v,
                rsi_v,
                adx_v,
                atr_v
            ]
        ):
            return None

        # =================================================
        # HARD FILTERS
        # =================================================

        # Avoid extremely overextended stocks
        if rsi_v > 78:
            return None

        # Don't reject neutral market.
        # Only block strong bearish Nifty.
        if MARKET_CONDITION == "🔴 Bearish":

            # Allow exceptionally strong stocks even
            # when market is weak.
            if not (
                buy > ema20_v
                and ema20_v > ema50_v
                and rsi_v >= 55
                and adx_v >= 25
            ):
                return None

        # =================================================
        # SCORE ENGINE
        # =================================================

        score = 0
        reasons = []

        # -------------------------------------------------
        # TREND
        # -------------------------------------------------

        if buy > ema20_v:

            score += 10
            reasons.append("✅ Price above EMA20")

        if ema20_v > ema50_v:

            score += 10
            reasons.append("✅ EMA20 above EMA50")

        if ema50_v > ema200_v:

            score += 15
            reasons.append("✅ EMA50 above EMA200")

        # Strong alignment bonus
        if buy > ema20_v > ema50_v > ema200_v:

            score += 5
            reasons.append("🔥 Full bullish EMA alignment")

        # -------------------------------------------------
        # RSI
        # -------------------------------------------------

        if 55 <= rsi_v <= 68:

            score += 15
            reasons.append(
                f"✅ RSI healthy ({rsi_v:.2f})"
            )

        elif 50 <= rsi_v < 55:

            score += 8
            reasons.append(
                f"🟡 RSI improving ({rsi_v:.2f})"
            )

        elif 68 < rsi_v <= 72:

            score += 8
            reasons.append(
                f"⚠ RSI elevated ({rsi_v:.2f})"
            )

        elif 72 < rsi_v <= 78:

            score += 3
            reasons.append(
                f"⚠ RSI high ({rsi_v:.2f})"
            )

        # -------------------------------------------------
        # MACD
        # -------------------------------------------------

        macd_v = safe_float(macd_line.iloc[-1])
        signal_v = safe_float(macd_signal.iloc[-1])
        hist_v = safe_float(macd_hist.iloc[-1])

        if macd_v > signal_v:

            score += 10
            reasons.append("✅ MACD bullish")

        if hist_v > 0:

            score += 5
            reasons.append("✅ MACD histogram positive")

        # -------------------------------------------------
        # ADX
        # -------------------------------------------------

        if adx_v >= 30:

            score += 15
            reasons.append(
                f"🔥 Strong ADX ({adx_v:.2f})"
            )

        elif adx_v >= 25:

            score += 10
            reasons.append(
                f"✅ Good ADX ({adx_v:.2f})"
            )

        elif adx_v >= 20:

            score += 5
            reasons.append(
                f"🟡 Developing trend ({adx_v:.2f})"
            )

        # -------------------------------------------------
        # RELATIVE VOLUME
        # -------------------------------------------------

        if rvol >= 3:

            score += 15
            reasons.append(
                f"🔥 Very high RVOL ({rvol:.2f}x)"
            )

        elif rvol >= 2:

            score += 12
            reasons.append(
                f"✅ Strong RVOL ({rvol:.2f}x)"
            )

        elif rvol >= 1.5:

            score += 8
            reasons.append(
                f"✅ Good RVOL ({rvol:.2f}x)"
            )

        elif rvol >= 1.1:

            score += 3
            reasons.append(
                f"🟡 Improving volume ({rvol:.2f}x)"
            )

        # =================================================
        # BREAKOUT DETECTION
        # =================================================

        prior20_high = safe_float(
            high.iloc[-21:-1].max()
        )

        prior50_high = safe_float(
            high.iloc[-51:-1].max()
        )

        prior100_high = safe_float(
            high.iloc[-101:-1].max()
        )

        breakout20 = buy > prior20_high
        breakout50 = buy > prior50_high
        breakout100 = buy > prior100_high

        # Recent breakout
        if breakout20:

            score += 15
            reasons.append(
                "🚀 20-day breakout"
            )

            # Volume confirmation
            if rvol >= 1.5:

                score += 5
                reasons.append(
                    "🔥 Breakout volume confirmed"
                )

        elif breakout50:

            score += 10
            reasons.append(
                "🚀 50-day breakout"
            )

        elif breakout100:

            score += 8
            reasons.append(
                "🚀 100-day breakout"
            )

        # =================================================
        # 200-DAY HIGH
        # =================================================

        prior200_high = safe_float(
            high.iloc[-201:-1].max()
        )

        if prior200_high > 0 and buy >= prior200_high:

            score += 8
            reasons.append(
                "🚀 200-day high"
            )

        # =================================================
        # WEEKLY TREND
        # =================================================

        try:

            weekly = close.resample("W").last()

            if len(weekly) >= 50:

                weekly20 = EMAIndicator(
                    weekly,
                    20
                ).ema_indicator()

                weekly50 = EMAIndicator(
                    weekly,
                    50
                ).ema_indicator()

                weekly_close = safe_float(
                    weekly.iloc[-1]
                )

                weekly20_v = safe_float(
                    weekly20.iloc[-1]
                )

                weekly50_v = safe_float(
                    weekly50.iloc[-1]
                )

                if (
                    weekly_close >
                    weekly20_v >
                    weekly50_v
                ):

                    score += 10
                    reasons.append(
                        "✅ Weekly trend bullish"
                    )

        except Exception:
            pass

        # =================================================
        # DEMAND ZONE
        # =================================================

        zone = identify_demand_zone(
            close,
            high,
            low
        )

        if zone:

            zone_low, zone_high = zone

            # Price near zone
            zone_range = zone_high - zone_low

            if zone_range > 0:

                distance = abs(
                    buy - zone_high
                )

                if distance <= max(
                    zone_range * 2,
                    atr_v
                ):

                    score += 5
                    reasons.append(
                        "🏦 Near demand zone"
                    )

        # =================================================
        # PRICE MOMENTUM
        # =================================================

        if len(close) >= 10:

            price_10d_ago = safe_float(
                close.iloc[-10]
            )

            if price_10d_ago > 0:

                momentum = (
                    (buy - price_10d_ago)
                    / price_10d_ago
                ) * 100

                if 3 <= momentum <= 12:

                    score += 5
                    reasons.append(
                        f"📈 Healthy momentum ({momentum:.1f}%)"
                    )

                elif momentum > 12:

                    score += 2
                    reasons.append(
                        f"⚠ Fast momentum ({momentum:.1f}%)"
                    )

        # =================================================
        # MARKET SUPPORT
        # =================================================

        if MARKET_CONDITION == "🟢 Bullish":

            score += 5
            reasons.append(
                "🌐 Nifty market supportive"
            )

        elif MARKET_CONDITION == "🟡 Neutral":

            score += 2
            reasons.append(
                "🌐 Nifty market neutral"
            )

        # =================================================
        # FINAL SCORE
        # =================================================

        score = max(
            0,
            min(score, 100)
        )

        # =================================================
        # QUALITY FILTER
        # =================================================

        if score < 80:
            return None

        # =================================================
        # CONFIDENCE
        # =================================================

        if score >= 92:

            trend = "🟢 Super Bullish"
            confidence = "💎 Institutional"

        elif score >= 87:

            trend = "🟢 Strong Bullish"
            confidence = "🔥 Excellent"

        elif score >= 82:

            trend = "🟢 Bullish"
            confidence = "✅ High"

        else:

            trend = "🟢 Bullish"
            confidence = "🟡 Good"

        # =================================================
        # RISK MANAGEMENT
        # =================================================

        # ATR stop
        sl = buy - (1.5 * atr_v)

        if sl <= 0 or sl >= buy:
            return None

        risk = buy - sl

        if risk <= 0:
            return None

        t1 = buy + risk
        t2 = buy + (2 * risk)
        t3 = buy + (3 * risk)

        # =================================================
        # RESULT
        # =================================================

        return {

            "symbol": symbol.replace(".NS", ""),

            "score": int(score),

            "trend": trend,

            "confidence": confidence,

            "market": MARKET_CONDITION,

            "reason": "\n".join(reasons),

            "buy": round(buy, 2),

            "sl": round(sl, 2),

            "t1": round(t1, 2),

            "t2": round(t2, 2),

            "t3": round(t3, 2),

            "rsi": round(rsi_v, 2),

            "rvol": round(rvol, 2),

            "adx": round(adx_v, 2),

            "atr": round(atr_v, 2)
        }

    except Exception as e:

        print(f"{symbol}: {e}")

        return None