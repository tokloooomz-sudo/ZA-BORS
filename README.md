# ZA-BORS

ZA-BORS is now a normal web app, not a Streamlit-only app.

It scans a BLINK-focused US stock universe, shows advisor verdicts, lets you add stocks to a persistent watchlist, displays live-ish quotes, and tracks bought positions with sell alerts.

> Research tool only. This is not financial advice.
> The bundled BLINK list is a practical local universe, not an official complete BLINK export. The app also uses live Yahoo Finance search for tickers that are missing from the local list; always confirm final availability inside BLINK before trading.

## Run Locally

```powershell
pip install -r requirements.txt
uvicorn web_app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Main Files

- `web_app.py` - FastAPI backend
- `templates/index.html` - web page
- `static/app.js` - browser logic
- `static/styles.css` - web styling
- `data/blink_universe.csv` - BLINK working stock universe
- `data/watchlist.json` - local personal watchlist, ignored by Git

## Features

- Scan up to 100 BLINK-watchlist tickers.
- Sort advisor decisions by:
  - כדאי מאוד
  - כדאי לעקוב
  - לא כדאי עכשיו
- Color advisor verdicts.
- Color stock prices green/red/yellow by daily movement.
- Add stocks with `+`.
- Remove stocks with `-`.
- Persistent watchlist.
- Mark a stock with `V` when actually bought.
- Enter buy price.
- Show live profit/loss.
- Sell alerts when:
  - SPY drops more than 10% from its recent high.
  - A bought stock gains more than 50% from buy price.

## Deploy As A Website

This app needs a Python server, so GitHub Pages will not run it directly.

Use Render, Railway, Fly.io, or another Python web host.

Start command:

```text
uvicorn web_app:app --host 0.0.0.0 --port $PORT
```

## Notes

- `yfinance` can be delayed or incomplete.
- For true trading-grade real-time prices, connect a paid market-data API.
- `data/watchlist.json` is ignored by Git so personal watchlists are not pushed publicly.
