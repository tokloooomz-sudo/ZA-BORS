# ZA-BORS

Personal Streamlit dashboard for professional-style US stock research and "buy low, sell high" signal discovery.

> This is a professional-style research assistant only. It is not a licensed investment advisor and it is not financial advice.

## What It Does

- Scans a configurable US stock universe.
- Applies the "Blink Filter":
  - NYSE/NASDAQ only.
  - Configurable market-cap floor, from no minimum to $1B.
- Includes a high-upside universe with FUTU, selected small caps, ADRs, and Israeli companies listed in the US.
- Includes a Blink working universe in `data/blink_universe.csv` for tickers the user wants to scan through the Blink workflow.
- Fetches recent news through NewsAPI when available, otherwise Google News RSS.
- Uses OpenAI sentiment/catalyst analysis when `OPENAI_API_KEY` is available.
- Falls back to a conservative keyword catalyst detector when no LLM key is configured.
- Validates "buy low" technicals:
  - 14-day RSI below 45.
  - Current price at least 10% below the 52-week high.
- Shows clean Streamlit cards with:
  - ticker and price,
  - catalyst summary,
  - RSI and dip checklist,
  - advisor score and verdict,
  - proposed entry, stop-loss, and 20% take-profit target,
  - estimated risk/reward,
  - suggested position size based on account size and risk settings,
  - key risk flags.
- Includes a simple manual watchlist.
- Watchlist entries are added through a simple ticker form and can be removed from the page.
- Supports English and Hebrew UI with right-to-left layout in Hebrew.

## Professional Advisor Mode

The sidebar includes risk controls:

- Risk profile: Conservative, Balanced, or Aggressive.
- Account size for position sizing.
- Maximum risk per trade.
- Default stop-loss percentage.
- Maximum allocation per stock.
- Option to show only professional-grade signals.

The app will only mark a candidate as actionable when it passes:

- Tradeability filter: NYSE/NASDAQ and your selected market-cap floor.
- Catalyst filter: concrete positive catalyst.
- Technical filter: RSI below 45 and at least 10% below the 52-week high.
- Advisor score: 65 or higher.

## Real-Time Data

The current implementation uses `yfinance`, which may be delayed or incomplete. For true professional real-time use, connect a dedicated market-data provider such as a paid quote/news API, then replace the `fetch_market_snapshot` and `fetch_news` functions.

Recommended future upgrade path:

1. Add a real-time quote provider.
2. Add authenticated broker availability checks for Blink or the broker you use.
3. Add portfolio holdings and exposure limits.
4. Add alerting by SMS, WhatsApp, email, or push notifications.
5. Add audit logs so every signal records the data used at decision time.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

If `python` is not installed on this Windows machine, install Python 3.11+ first.

## Optional API Keys

Create `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "your_openai_key"
OPENAI_MODEL = "gpt-5.2"
NEWSAPI_KEY = "your_newsapi_key"
```

You can also set these as environment variables.

## Use On Your Phone

The app is mobile-friendly in the browser. For phone access, deploy it online:

1. Push this repository to GitHub.
2. Create a free Streamlit Community Cloud app.
3. Select this repo and set `app.py` as the entry file.
4. Add the secrets above in the Streamlit Cloud secrets manager.
5. Open the deployed URL on your phone and add it to your home screen.

## Notes

- `yfinance` data can be delayed or incomplete.
- News and LLM sentiment are inputs for research, not trading instructions.
- Always confirm that a ticker is available in your actual broker app before placing an order.
- The Blink universe is an editable working list, not an official complete list from Blink.
