# GTF PRO V11 — Clean single-file package

## Included files
- `main.py`: scanner + paper-trade monitor in one Python file
- `requirements.txt`: dependencies
- `.github/workflows/gtf-pro-v11.yml`: scheduled GitHub Actions workflow
- `signals.json`: empty, clean signal store
- `trade_history.json`: empty, clean trade history

## Important before upload
This is a clean reset. The included JSON files are empty. Replacing your old files will discard old signals and trade history. Download a backup of your existing repository first if you might need those records later.

## Upload on GitHub mobile
1. Open your repository and download/backup the current repository if needed.
2. Upload the contents of this ZIP into the repository root, preserving the `.github/workflows/` folder structure.
3. Delete old `strategy.py`, `monitor.py`, and the old scanner/monitor workflow YAML files so only the V11 workflow runs.
4. Keep only one active workflow: `.github/workflows/gtf-pro-v11.yml`.
5. In GitHub repository Settings → Secrets and variables → Actions, make sure `BOT_TOKEN` and `CHAT_ID` exist.
6. Open Actions → GTF PRO V11 Scanner and Monitor → Run workflow to test manually.

## Strategy behavior
- Nifty bullish: looks for daily swing BUY setups.
- Nifty bearish: looks for 5-minute intraday cash-equity SHORT setups.
- Otherwise: no new trades.
- Maximum 5 new signals per scan.
- Intraday shorts are marked for forced square-off at 15:20 IST.
- Paper trading only; no broker orders.

## Important limitations
- The package uses a 50-stock liquid NSE watchlist embedded in `main.py`, not the previous 754/755-stock universe.
- Yahoo Finance data is not guaranteed real-time or complete. Stale intraday candles are rejected.
- GitHub Actions scheduled runs are best-effort and can be delayed. A five-minute schedule cannot guarantee stop-loss execution or a 15:20 exit.
- This is a paper-trading framework, not a guarantee of safe or profitable trades. Validate results before considering any live use.
- `main.py` uses five-minute Yahoo candles to monitor both swing and intraday paper positions.
