from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf


APP_NAME = "ZA-BORS"
MIN_MARKET_CAP = 1_000_000_000
MAJOR_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "NASDAQ", "NYSE"}
DEFAULT_UNIVERSE_PATH = "data/default_universe.csv"


@dataclass
class CatalystResult:
    ticker: str
    has_positive_catalyst: bool
    summary: str
    catalyst_type: str
    confidence: float


def page_setup() -> None:
    st.set_page_config(
        page_title=f"{APP_NAME} Stock Screener",
        page_icon=":chart_with_upwards_trend:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.4rem; }
        [data-testid="stMetricValue"] { font-size: 1.6rem; }
        .signal-card {
            border: 1px solid #d9e1e8;
            border-radius: 8px;
            padding: 18px;
            background: #ffffff;
            box-shadow: 0 12px 28px rgba(23, 33, 43, 0.08);
            margin-bottom: 14px;
        }
        .ticker-line {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: baseline;
        }
        .ticker-symbol { font-size: 1.5rem; font-weight: 800; color: #0b5f59; }
        .price-text { color: #17212b; font-weight: 700; }
        .pill {
            display: inline-block;
            padding: 4px 9px;
            border-radius: 999px;
            background: #eef4f5;
            color: #17212b;
            margin: 4px 6px 4px 0;
            font-size: 0.88rem;
        }
        .risk-note {
            border: 1px solid #f3c969;
            background: #fff7df;
            color: #5f3b00;
            border-radius: 8px;
            padding: 12px 14px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=60 * 60)
def load_default_universe() -> pd.DataFrame:
    return pd.read_csv(DEFAULT_UNIVERSE_PATH)


@st.cache_data(ttl=60 * 15)
def fetch_market_snapshot(ticker: str, lookback_period: str = "1y") -> dict[str, Any]:
    stock = yf.Ticker(ticker)
    history = stock.history(period=lookback_period, interval="1d", auto_adjust=False)

    info: dict[str, Any] = {}
    try:
        info = stock.get_info() or {}
    except Exception:
        info = {}

    return {
        "ticker": ticker.upper(),
        "history": history,
        "info": info,
    }


def compute_rsi(close: pd.Series, period: int = 14) -> float:
    if close.empty or len(close) < period + 2:
        return float("nan")

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def technicals_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    history: pd.DataFrame = snapshot["history"]
    info: dict[str, Any] = snapshot["info"]
    ticker = snapshot["ticker"]

    if history.empty:
        return {
            "ticker": ticker,
            "valid": False,
            "reason": "No price history returned by yfinance.",
        }

    close = history["Close"].dropna()
    current_price = float(close.iloc[-1])
    high_52w = float(close.max())
    market_cap = info.get("marketCap")
    exchange = str(info.get("exchange") or info.get("fullExchangeName") or "").upper()

    if not market_cap:
        market_cap = estimate_market_cap(info, current_price)

    rsi_14 = compute_rsi(close)
    distance_from_high = ((high_52w - current_price) / high_52w) * 100 if high_52w else 0
    exchange_ok = any(code in exchange for code in MAJOR_EXCHANGES)
    market_cap_ok = bool(market_cap and market_cap >= MIN_MARKET_CAP)

    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "exchange": exchange or "Unknown",
        "market_cap": market_cap,
        "current_price": current_price,
        "high_52w": high_52w,
        "rsi_14": rsi_14,
        "distance_from_high": distance_from_high,
        "entry_price": current_price,
        "take_profit": current_price * 1.2,
        "exchange_ok": exchange_ok,
        "market_cap_ok": market_cap_ok,
        "rsi_ok": bool(np.isfinite(rsi_14) and rsi_14 < 45),
        "dip_ok": distance_from_high >= 10,
        "valid": True,
    }


def estimate_market_cap(info: dict[str, Any], current_price: float) -> float | None:
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    if shares and current_price:
        return float(shares) * current_price
    return None


@st.cache_data(ttl=60 * 20)
def fetch_news(ticker: str, company_name: str, max_items: int = 5) -> list[dict[str, str]]:
    news_api_key = get_secret_or_env("NEWSAPI_KEY")
    if news_api_key:
        return fetch_newsapi_news(ticker, company_name, news_api_key, max_items=max_items)
    return fetch_google_rss_news(ticker, company_name, max_items=max_items)


def fetch_newsapi_news(ticker: str, company_name: str, api_key: str, max_items: int) -> list[dict[str, str]]:
    query = f'("{ticker}" OR "{company_name}") AND (stock OR earnings OR contract OR approval OR guidance)'
    response = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": max_items,
            "apiKey": api_key,
        },
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    articles = payload.get("articles", [])
    return [
        {
            "title": item.get("title") or "",
            "summary": item.get("description") or "",
            "source": (item.get("source") or {}).get("name") or "NewsAPI",
            "url": item.get("url") or "",
            "published": item.get("publishedAt") or "",
        }
        for item in articles[:max_items]
    ]


def fetch_google_rss_news(ticker: str, company_name: str, max_items: int) -> list[dict[str, str]]:
    query = requests.utils.quote(f"{ticker} {company_name} stock earnings contract approval")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    response = requests.get(url, timeout=12, headers={"User-Agent": "ZA-BORS/1.0"})
    response.raise_for_status()

    root = ET.fromstring(response.content)
    items = root.findall("./channel/item")
    news: list[dict[str, str]] = []
    for item in items[:max_items]:
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        published = item.findtext("pubDate", default="")
        news.append(
            {
                "title": clean_html(title),
                "summary": "",
                "source": "Google News RSS",
                "url": link,
                "published": published,
            }
        )
    return news


def clean_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def get_secret_or_env(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name)


def analyze_catalyst(ticker: str, company_name: str, news_items: list[dict[str, str]]) -> CatalystResult:
    if not news_items:
        return CatalystResult(ticker, False, "No recent news was found.", "none", 0.0)

    openai_key = get_secret_or_env("OPENAI_API_KEY")
    if openai_key:
        try:
            return analyze_catalyst_with_openai(ticker, company_name, news_items)
        except Exception as exc:
            st.caption(f"LLM analysis fallback for {ticker}: {exc}")

    return analyze_catalyst_with_keywords(ticker, news_items)


def analyze_catalyst_with_openai(
    ticker: str,
    company_name: str,
    news_items: list[dict[str, str]],
) -> CatalystResult:
    from openai import OpenAI

    client = OpenAI(api_key=get_secret_or_env("OPENAI_API_KEY"))
    model = get_secret_or_env("OPENAI_MODEL") or "gpt-5.2"
    news_text = "\n".join(
        f"- {item['title']} | {item.get('summary', '')} | {item.get('source', '')}"
        for item in news_items
    )

    prompt = f"""
Analyze these recent financial headlines for {ticker} ({company_name}).

Return JSON only with this shape:
{{
  "has_positive_catalyst": true,
  "summary": "Exactly two concise sentences explaining why the news may create positive change.",
  "catalyst_type": "earnings|contract|approval|breakthrough|guidance|partnership|other|none",
  "confidence": 0.0
}}

Flag true only for a concrete catalyst for positive change, such as a major contract,
regulatory approval, breakthrough product, material earnings beat, raised guidance,
or a major strategic partnership. Do not flag vague optimism, rumors, analyst chatter,
or general market movement.

Headlines:
{news_text}
""".strip()

    # OpenAI recommends the Responses API for new text generation projects.
    response = client.responses.create(
        model=model,
        instructions="You are a conservative financial-news catalyst classifier. You do not provide investment advice.",
        input=prompt,
    )
    payload = parse_json_object(response.output_text)
    return CatalystResult(
        ticker=ticker,
        has_positive_catalyst=bool(payload.get("has_positive_catalyst")),
        summary=str(payload.get("summary") or "No catalyst summary returned."),
        catalyst_type=str(payload.get("catalyst_type") or "other"),
        confidence=float(payload.get("confidence") or 0.0),
    )


def analyze_catalyst_with_keywords(ticker: str, news_items: list[dict[str, str]]) -> CatalystResult:
    positive_terms = {
        "approval": "regulatory approval",
        "approves": "regulatory approval",
        "beat": "earnings beat",
        "beats": "earnings beat",
        "raises guidance": "raised guidance",
        "contract": "major contract",
        "partnership": "strategic partnership",
        "breakthrough": "breakthrough",
        "launches": "product launch",
        "surges after": "market reaction",
    }
    combined = " ".join(item.get("title", "") + " " + item.get("summary", "") for item in news_items).lower()
    matches = [label for term, label in positive_terms.items() if term in combined]
    if not matches:
        return CatalystResult(
            ticker=ticker,
            has_positive_catalyst=False,
            summary="Recent headlines did not show a concrete positive-change catalyst. Add an OpenAI API key for stricter LLM analysis.",
            catalyst_type="none",
            confidence=0.25,
        )

    top_headline = news_items[0].get("title") or "Recent news"
    return CatalystResult(
        ticker=ticker,
        has_positive_catalyst=True,
        summary=f"{top_headline}. Keyword analysis detected a possible {matches[0]}, so this should be reviewed manually before trading.",
        catalyst_type=matches[0],
        confidence=0.55,
    )


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def scan_tickers(tickers: list[str], max_news_items: int) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    signals: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    progress = st.progress(0, text="Starting scan...")

    for index, ticker in enumerate(tickers, start=1):
        ticker = ticker.strip().upper()
        progress.progress(index / len(tickers), text=f"Scanning {ticker} ({index}/{len(tickers)})")

        try:
            snapshot = fetch_market_snapshot(ticker)
            technicals = technicals_from_snapshot(snapshot)
            if not technicals.get("valid"):
                diagnostics.append({"ticker": ticker, "status": "Skipped", "reason": technicals.get("reason")})
                continue

            blink_ok = technicals["exchange_ok"] and technicals["market_cap_ok"]
            technical_ok = technicals["rsi_ok"] and technicals["dip_ok"]
            company_name = str(technicals["name"])
            news_items = fetch_news(ticker, company_name, max_items=max_news_items)
            catalyst = analyze_catalyst(ticker, company_name, news_items)

            diagnostics.append(
                {
                    "ticker": ticker,
                    "status": "Signal" if blink_ok and technical_ok and catalyst.has_positive_catalyst else "Filtered",
                    "exchange": technicals["exchange"],
                    "market_cap": technicals["market_cap"],
                    "rsi_14": technicals["rsi_14"],
                    "distance_from_high": technicals["distance_from_high"],
                    "positive_catalyst": catalyst.has_positive_catalyst,
                    "reason": filter_reason(blink_ok, technical_ok, catalyst),
                }
            )

            if blink_ok and technical_ok and catalyst.has_positive_catalyst:
                signals.append({**technicals, "catalyst": catalyst, "news": news_items})
        except Exception as exc:
            diagnostics.append({"ticker": ticker, "status": "Error", "reason": str(exc)})

    progress.empty()
    signals.sort(key=lambda row: (row["catalyst"].confidence, row["distance_from_high"]), reverse=True)
    return signals, pd.DataFrame(diagnostics)


def filter_reason(blink_ok: bool, technical_ok: bool, catalyst: CatalystResult) -> str:
    if not blink_ok:
        return "Failed Blink filter: exchange or market cap."
    if not catalyst.has_positive_catalyst:
        return "No concrete positive catalyst."
    if not technical_ok:
        return "Failed buy-low technical validation."
    return "Passed all filters."


def market_trend(tickers: list[str]) -> dict[str, Any]:
    benchmarks = ["SPY", "QQQ", "DIA"]
    rows = []
    for ticker in benchmarks:
        try:
            history = yf.Ticker(ticker).history(period="1mo", interval="1d")
            if len(history) >= 2:
                change = ((history["Close"].iloc[-1] / history["Close"].iloc[0]) - 1) * 100
                rows.append({"ticker": ticker, "change_1m": change})
        except Exception:
            continue

    avg_change = np.mean([row["change_1m"] for row in rows]) if rows else 0
    if avg_change > 3:
        label = "Risk-on"
    elif avg_change < -3:
        label = "Risk-off"
    else:
        label = "Mixed / neutral"
    return {"label": label, "avg_change": avg_change, "benchmarks": rows, "scanned": len(tickers)}


def render_signal_card(signal: dict[str, Any]) -> None:
    catalyst: CatalystResult = signal["catalyst"]
    rsi = signal["rsi_14"]
    distance = signal["distance_from_high"]
    market_cap_b = (signal["market_cap"] or 0) / 1_000_000_000
    rsi_badge = "OK" if signal["rsi_ok"] else "!"
    dip_badge = "OK" if signal["dip_ok"] else "!"
    news_links = " ".join(
        f'<a href="{item["url"]}" target="_blank">News {idx}</a>'
        for idx, item in enumerate(signal["news"][:3], start=1)
        if item.get("url")
    )

    st.markdown(
        f"""
        <div class="signal-card">
            <div class="ticker-line">
                <div><span class="ticker-symbol">{signal["ticker"]}</span> <span>{signal["name"]}</span></div>
                <div class="price-text">${signal["current_price"]:.2f}</div>
            </div>
            <p><strong>The Catalyst:</strong> {catalyst.summary}</p>
            <span class="pill">RSI 14D: {rsi:.1f} {rsi_badge}</span>
            <span class="pill">Below 52W high: {distance:.1f}% {dip_badge}</span>
            <span class="pill">Market cap: ${market_cap_b:.1f}B</span>
            <span class="pill">Catalyst: {catalyst.catalyst_type}</span>
            <p><strong>Action Plan:</strong> proposed entry near ${signal["entry_price"]:.2f};
            20% take-profit target ${signal["take_profit"]:.2f}. Use your own stop-loss and position sizing.</p>
            <p>{news_links}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_watchlist() -> None:
    st.subheader("My Watchlist")
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = pd.DataFrame(columns=["Ticker", "Notes", "Added"])

    with st.form("watchlist_form", clear_on_submit=True):
        col_a, col_b = st.columns([1, 3])
        ticker = col_a.text_input("Ticker", placeholder="AAPL").upper()
        notes = col_b.text_input("Notes", placeholder="Why are you watching it?")
        submitted = st.form_submit_button("Add to watchlist")

    if submitted and ticker:
        new_row = pd.DataFrame(
            [{"Ticker": ticker, "Notes": notes, "Added": datetime.now(timezone.utc).strftime("%Y-%m-%d")}]
        )
        st.session_state.watchlist = pd.concat([st.session_state.watchlist, new_row], ignore_index=True)

    st.data_editor(st.session_state.watchlist, use_container_width=True, num_rows="dynamic")


def sidebar_controls() -> tuple[list[str], int]:
    st.sidebar.header("Scan Settings")
    default_universe = load_default_universe()
    universe_mode = st.sidebar.radio("Universe", ["Default liquid US list", "Custom tickers"], index=0)

    if universe_mode == "Default liquid US list":
        max_count = st.sidebar.slider("Max tickers to scan", 5, len(default_universe), 15)
        tickers = default_universe["ticker"].head(max_count).tolist()
    else:
        raw = st.sidebar.text_area("Tickers", value="AAPL, MSFT, NVDA, AMD, TSLA")
        tickers = [item.strip().upper() for item in raw.replace("\n", ",").split(",") if item.strip()]

    max_news_items = st.sidebar.slider("News items per ticker", 2, 10, 5)
    st.sidebar.divider()
    st.sidebar.caption("Optional secrets: OPENAI_API_KEY, OPENAI_MODEL, NEWSAPI_KEY.")
    st.sidebar.caption("Without keys, the app uses Google News RSS plus keyword catalyst detection.")
    return tickers, max_news_items


def main() -> None:
    page_setup()
    tickers, max_news_items = sidebar_controls()

    st.title("ZA-BORS Stock Screener")
    st.markdown(
        '<div class="risk-note">Research tool only. This is not financial advice, and signals must be reviewed manually before any trade.</div>',
        unsafe_allow_html=True,
    )

    trend = market_trend(tickers)
    col_1, col_2, col_3 = st.columns(3)
    col_1.metric("Market trend", trend["label"])
    col_2.metric("1M benchmark avg", f"{trend['avg_change']:.2f}%")
    col_3.metric("Scan universe", f"{trend['scanned']} tickers")

    st.divider()
    st.subheader("Hot Actions / Buy Signals")
    st.caption("Filters: NYSE/NASDAQ, market cap above $1B, positive catalyst, RSI below 45, and price at least 10% below 52-week high.")

    if st.button("Run scan", type="primary"):
        signals, diagnostics = scan_tickers(tickers, max_news_items=max_news_items)
        st.session_state["signals"] = signals
        st.session_state["diagnostics"] = diagnostics

    signals = st.session_state.get("signals", [])
    diagnostics = st.session_state.get("diagnostics", pd.DataFrame())

    if signals:
        for signal in signals:
            render_signal_card(signal)
    else:
        st.info("No active buy signals yet. Run a scan or widen the custom universe.")

    with st.expander("Diagnostics / filtered tickers", expanded=False):
        if isinstance(diagnostics, pd.DataFrame) and not diagnostics.empty:
            st.dataframe(diagnostics, use_container_width=True)
        else:
            st.caption("Diagnostics will appear after the first scan.")

    st.divider()
    render_watchlist()


if __name__ == "__main__":
    main()
