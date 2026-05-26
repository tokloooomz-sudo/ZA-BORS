# ZA-BORS

Personal Streamlit dashboard for scanning US stocks for possible "buy low, sell high" research signals.

> This is a research tool only. It is not financial advice.

## What It Does

- Scans a configurable US stock universe.
- Applies the "Blink Filter":
  - NYSE/NASDAQ only.
  - Market cap above $1B.
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
  - proposed entry and 20% take-profit target.
- Includes a simple manual watchlist.

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
