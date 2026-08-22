import json
import os
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
IST = timezone(timedelta(hours=5, minutes=30))

def send(text):
    import requests
    requests.post(URL, data={"chat_id": CHAT_ID, "text": text}, timeout=20)

def load(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return []

history = load("trade_history.json")
signals = load("signals.json")

now = datetime.now(IST)
month = now.strftime("%Y-%m")

trades = []
for x in history:
    try:
        if str(x.get("exit_time", "")).startswith(month):
            trades.append(x)
    except:
        pass

wins = [x for x in trades if x.get("result") == "WIN"]
losses = [x for x in trades if x.get("result") == "LOSS"]
t1 = [x for x in trades if x.get("t1_hit")]
t2 = [x for x in trades if x.get("t2_hit")]
t3 = [x for x in trades if x.get("t3_hit")]

total = len(trades)
win_rate = (len(wins) / total * 100) if total else 0
avg_win = sum(float(x.get("pnl_pct") or 0) for x in wins) / len(wins) if wins else 0
avg_loss = sum(float(x.get("pnl_pct") or 0) for x in losses) / len(losses) if losses else 0
net = sum(float(x.get("pnl_pct") or 0) for x in trades)

gross_profit = sum(max(float(x.get("pnl_pct") or 0), 0) for x in trades)
gross_loss = abs(sum(min(float(x.get("pnl_pct") or 0), 0) for x in trades))
profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0)

message = (
    "📊 GTF PRO V7 — MONTHLY REPORT\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    f"📅 Month : {now.strftime('%B %Y')}\n"
    f"📈 Closed Trades : {total}\n"
    f"✅ Wins : {len(wins)}\n"
    f"❌ Losses : {len(losses)}\n"
    f"⏳ Open/Waiting : {sum(1 for x in signals if x.get('status') in ('OPEN','WAITING_ENTRY'))}\n\n"
    f"🏆 Win Rate : {win_rate:.1f}%\n"
    f"🎯 T1 Hit : {len(t1)}\n"
    f"🎯 T2 Hit : {len(t2)}\n"
    f"🎯 T3 Hit : {len(t3)}\n\n"
    f"📈 Avg Winner : {avg_win:.2f}%\n"
    f"📉 Avg Loser : {avg_loss:.2f}%\n"
    f"💰 Net Signal P&L : {net:.2f}%\n"
    f"📊 Profit Factor : {profit_factor:.2f}\n"
)

if trades:
    best = max(trades, key=lambda x: float(x.get("pnl_pct") or 0))
    worst = min(trades, key=lambda x: float(x.get("pnl_pct") or 0))
    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        f"🥇 Best : {best['symbol']} ({best.get('pnl_pct')}%)\n"
        f"🔻 Worst : {worst['symbol']} ({worst.get('pnl_pct')}%)\n"
    )
else:
    message += "\nℹ️ No V7 closed trades recorded for this month yet."

send(message)
