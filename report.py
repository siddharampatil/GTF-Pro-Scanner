import os
import json
import requests
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
IST = timezone(timedelta(hours=5, minutes=30))

HISTORY_FILE = "trade_history.json"
SIGNALS_FILE = "signals.json"


def load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def send(text):
    for start in range(0, len(text), 3900):
        r = requests.post(
            URL,
            data={"chat_id": CHAT_ID, "text": text[start:start + 3900]},
            timeout=25,
        )
        r.raise_for_status()


def pct(x):
    return float(x or 0)


history = load(HISTORY_FILE, [])
signals = load(SIGNALS_FILE, [])

now = datetime.now(IST)
month_key = now.strftime("%Y-%m")

# V8 uses closed trades only for the win/loss ratio.
trades = [
    x for x in history
    if str(x.get("exit_time", "")).startswith(month_key)
    and x.get("result") in ("WIN", "LOSS")
]

wins = [x for x in trades if x.get("result") == "WIN"]
losses = [x for x in trades if x.get("result") == "LOSS"]

total = len(trades)
win_rate = (len(wins) / total * 100) if total else 0.0
loss_rate = (len(losses) / total * 100) if total else 0.0

net_pct = sum(pct(x.get("pnl_pct")) for x in trades)
gross_profit = sum(max(pct(x.get("pnl_pct")), 0) for x in trades)
gross_loss = abs(sum(min(pct(x.get("pnl_pct")), 0) for x in trades))
profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0)

avg_win = sum(pct(x.get("pnl_pct")) for x in wins) / len(wins) if wins else 0
avg_loss = sum(pct(x.get("pnl_pct")) for x in losses) / len(losses) if losses else 0

t1 = sum(bool(x.get("t1_hit")) for x in trades)
t2 = sum(bool(x.get("t2_hit")) for x in trades)
t3 = sum(bool(x.get("t3_hit")) for x in trades)
open_count = sum(
    x.get("status") in ("WAITING_ENTRY", "OPEN")
    for x in signals
)

message = (
    "📊 GTF PRO V8 — MONTHLY REPORT\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    f"📅 Month : {now.strftime('%B %Y')}\n"
    f"📈 Closed Trades : {total}\n"
    f"✅ Wins : {len(wins)} ({win_rate:.1f}%)\n"
    f"❌ Losses : {len(losses)} ({loss_rate:.1f}%)\n"
    f"⏳ Open/Waiting : {open_count}\n\n"
    f"🎯 T1 Hits : {t1}\n"
    f"🎯 T2 Hits : {t2}\n"
    f"🏆 T3 Hits : {t3}\n\n"
    f"📈 Avg Winner : {avg_win:.2f}%\n"
    f"📉 Avg Loser : {avg_loss:.2f}%\n"
    f"💰 Net Signal P&L : {net_pct:.2f}%\n"
    f"📊 Profit Factor : {profit_factor:.2f}\n"
)

if trades:
    best = max(trades, key=lambda x: pct(x.get("pnl_pct")))
    worst = min(trades, key=lambda x: pct(x.get("pnl_pct")))
    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        f"📈 Best recorded trade : {best.get('symbol')} "
        f"({pct(best.get('pnl_pct')):.2f}%)\n"
        f"📉 Worst recorded trade : {worst.get('symbol')} "
        f"({pct(worst.get('pnl_pct')):.2f}%)\n"
    )
else:
    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "ℹ️ No closed V8 trades were recorded this month.\n"
        "The report will become meaningful after monitor.py records exits."
    )

send(message)
print("✅ V8 monthly report sent")
