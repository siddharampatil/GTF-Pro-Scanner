# GTF PRO Scanner V8

V8 package for the existing GTF-Pro-Scanner repository.

Included:
- main.py — daily scanner and signal-book preservation
- monitor.py — entry confirmation, SL/T1/T2/T3 monitoring and closed-trade history
- report.py — monthly win/loss report
- .github/workflows/scanner.yml
- .github/workflows/monitor.yml
- .github/workflows/report.yml
- requirements.txt

Important:
1. Keep your existing `strategy.py`, `stock_list.py` and `stocks.txt` unless you have newer versions.
2. Keep `BOT_TOKEN` and `CHAT_ID` in GitHub repository Secrets.
3. Keep `signals.json` and `trade_history.json` in the repository so GitHub Actions can persist history.
4. GitHub Actions scheduled runs can start late; cron time is a requested schedule, not a guaranteed market-tick timer.
5. The monthly report measures V8 recorded signal exits, not your broker's actual net P&L after brokerage, taxes, slippage or other debits.
