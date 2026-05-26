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


@dataclass
class AdvisorSettings:
    profile: str
    account_size: float
    risk_per_trade_pct: float
    stop_loss_pct: float
    max_position_pct: float
    require_all_filters: bool


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
        .advisor-verdict {
            border-right: 4px solid #0f766e;
            padding: 10px 12px;
            background: #f1faf8;
            margin: 10px 0;
        }
        .risk-list {
            color: #5b6672;
            margin-top: 6px;
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
    fast_info: dict[str, Any] = {}
    try:
        info = stock.get_info() or {}
    except Exception:
        info = {}
    try:
        fast_info = dict(stock.fast_info or {})
    except Exception:
        fast_info = {}

    return {
        "ticker": ticker.upper(),
        "history": history,
        "info": info,
        "fast_info": fast_info,
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
    fast_info: dict[str, Any] = snapshot.get("fast_info", {})
    ticker = snapshot["ticker"]

    if history.empty:
        return {
            "ticker": ticker,
            "valid": False,
            "reason": "No price history returned by yfinance.",
        }

    close = history["Close"].dropna()
    current_price = first_number(
        fast_info.get("last_price"),
        info.get("currentPrice"),
        info.get("regularMarketPrice"),
        close.iloc[-1],
    )
    high_52w = first_number(info.get("fiftyTwoWeekHigh"), fast_info.get("year_high"), close.max())
    market_cap = info.get("marketCap")
    exchange = str(info.get("exchange") or info.get("fullExchangeName") or "").upper()

    if not market_cap:
        market_cap = estimate_market_cap(info, current_price)

    rsi_14 = compute_rsi(close)
    distance_from_high = ((high_52w - current_price) / high_52w) * 100 if high_52w else 0
    volatility_30d = annualized_volatility(close.tail(31))
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
        "volatility_30d": volatility_30d,
        "beta": info.get("beta"),
        "average_volume": info.get("averageVolume") or fast_info.get("three_month_average_volume"),
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


def first_number(*values: Any) -> float:
    for value in values:
        try:
            number = float(value)
            if np.isfinite(number) and number > 0:
                return number
        except (TypeError, ValueError):
            continue
    return 0.0


def annualized_volatility(close: pd.Series) -> float:
    if len(close) < 3:
        return float("nan")
    returns = close.pct_change().dropna()
    return float(returns.std() * np.sqrt(252) * 100)


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


def scan_tickers(
    tickers: list[str],
    max_news_items: int,
    advisor_settings: AdvisorSettings,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
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
            advisor = build_advisor_view(technicals, catalyst, advisor_settings)

            diagnostics.append(
                {
                    "ticker": ticker,
                    "status": "Signal" if advisor["is_actionable"] else "Filtered",
                    "exchange": technicals["exchange"],
                    "market_cap": technicals["market_cap"],
                    "rsi_14": technicals["rsi_14"],
                    "distance_from_high": technicals["distance_from_high"],
                    "advisor_score": advisor["score"],
                    "verdict": advisor["verdict"],
                    "positive_catalyst": catalyst.has_positive_catalyst,
                    "reason": filter_reason(blink_ok, technical_ok, catalyst),
                }
            )

            if advisor["is_actionable"] or not advisor_settings.require_all_filters:
                signals.append({**technicals, "catalyst": catalyst, "advisor": advisor, "news": news_items})
        except Exception as exc:
            diagnostics.append({"ticker": ticker, "status": "Error", "reason": str(exc)})

    progress.empty()
    signals.sort(key=lambda row: (row["advisor"]["score"], row["catalyst"].confidence), reverse=True)
    return signals, pd.DataFrame(diagnostics)


def build_advisor_view(
    technicals: dict[str, Any],
    catalyst: CatalystResult,
    settings: AdvisorSettings,
) -> dict[str, Any]:
    current_price = technicals["current_price"]
    stop_loss = current_price * (1 - settings.stop_loss_pct / 100)
    take_profit = current_price * 1.2
    risk_per_share = max(current_price - stop_loss, 0.01)
    dollars_at_risk = settings.account_size * (settings.risk_per_trade_pct / 100)
    risk_based_shares = int(dollars_at_risk // risk_per_share)
    max_position_value = settings.account_size * (settings.max_position_pct / 100)
    allocation_based_shares = int(max_position_value // current_price) if current_price else 0
    suggested_shares = max(0, min(risk_based_shares, allocation_based_shares))

    blink_ok = technicals["exchange_ok"] and technicals["market_cap_ok"]
    technical_ok = technicals["rsi_ok"] and technicals["dip_ok"]
    liquidity_score = min((technicals.get("market_cap") or 0) / 50_000_000_000, 1) * 100
    rsi_score = clamp_score(100 - max(0, technicals["rsi_14"] - 30) * 2) if np.isfinite(technicals["rsi_14"]) else 40
    dip_score = clamp_score(technicals["distance_from_high"] * 4)
    catalyst_score = clamp_score(catalyst.confidence * 100)
    risk_penalty = risk_penalty_score(technicals)

    score = round(
        catalyst_score * 0.35
        + rsi_score * 0.2
        + dip_score * 0.2
        + liquidity_score * 0.15
        + (100 - risk_penalty) * 0.1
    )

    is_actionable = blink_ok and technical_ok and catalyst.has_positive_catalyst and score >= 65
    verdict = "Strong research candidate" if score >= 80 else "Watch closely" if score >= 65 else "Do not chase"
    risks = risk_flags(technicals, catalyst)

    return {
        "score": score,
        "verdict": verdict,
        "is_actionable": is_actionable,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": (take_profit - current_price) / risk_per_share,
        "suggested_shares": suggested_shares,
        "suggested_position_value": suggested_shares * current_price,
        "dollars_at_risk": min(suggested_shares * risk_per_share, dollars_at_risk),
        "risks": risks,
        "profile": settings.profile,
    }


def clamp_score(value: float) -> float:
    return min(100, max(0, float(value)))


def risk_penalty_score(technicals: dict[str, Any]) -> float:
    penalty = 0.0
    volatility = technicals.get("volatility_30d")
    beta = technicals.get("beta")
    if volatility and np.isfinite(volatility):
        penalty += max(0, volatility - 45)
    if beta:
        penalty += max(0, float(beta) - 1.5) * 20
    return clamp_score(penalty)


def risk_flags(technicals: dict[str, Any], catalyst: CatalystResult) -> list[str]:
    flags: list[str] = []
    if catalyst.confidence < 0.7:
        flags.append("Catalyst confidence is not high enough for blind execution.")
    if technicals.get("volatility_30d") and technicals["volatility_30d"] > 55:
        flags.append("High short-term volatility; position size should be reduced.")
    if technicals.get("beta") and float(technicals["beta"]) > 1.7:
        flags.append("High beta; stock may move harder than the market.")
    if not technicals["rsi_ok"]:
        flags.append("RSI filter did not pass.")
    if not technicals["dip_ok"]:
        flags.append("Price is not far enough below its 52-week high.")
    if not flags:
        flags.append("Main risks are execution timing, news reversal, and broad market weakness.")
    return flags


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
    advisor: dict[str, Any] = signal["advisor"]
    rsi = signal["rsi_14"]
    distance = signal["distance_from_high"]
    market_cap_b = (signal["market_cap"] or 0) / 1_000_000_000
    volatility = signal.get("volatility_30d")
    beta = signal.get("beta")
    rsi_badge = "OK" if signal["rsi_ok"] else "!"
    dip_badge = "OK" if signal["dip_ok"] else "!"
    risk_items = "".join(f"<li>{risk}</li>" for risk in advisor["risks"])
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
            <div class="advisor-verdict">
                <strong>Advisor View:</strong> {advisor["verdict"]} | Score {advisor["score"]}/100 | Profile: {advisor["profile"]}
            </div>
            <p><strong>The Catalyst:</strong> {catalyst.summary}</p>
            <span class="pill">RSI 14D: {rsi:.1f} {rsi_badge}</span>
            <span class="pill">Below 52W high: {distance:.1f}% {dip_badge}</span>
            <span class="pill">Market cap: ${market_cap_b:.1f}B</span>
            <span class="pill">30D volatility: {format_optional_pct(volatility)}</span>
            <span class="pill">Beta: {format_optional_number(beta)}</span>
            <span class="pill">Catalyst: {catalyst.catalyst_type}</span>
            <p><strong>Professional Action Plan:</strong> entry zone near ${signal["entry_price"]:.2f};
            stop-loss ${advisor["stop_loss"]:.2f}; 20% take-profit target ${advisor["take_profit"]:.2f};
            estimated risk/reward {advisor["risk_reward"]:.2f}:1.</p>
            <p><strong>Position Sizing:</strong> suggested {advisor["suggested_shares"]} shares,
            about ${advisor["suggested_position_value"]:.0f} position value, with about ${advisor["dollars_at_risk"]:.0f} at risk.</p>
            <ul class="risk-list">{risk_items}</ul>
            <p>{news_links}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_optional_pct(value: Any) -> str:
    try:
        number = float(value)
        if np.isfinite(number):
            return f"{number:.1f}%"
    except (TypeError, ValueError):
        pass
    return "N/A"


def format_optional_number(value: Any) -> str:
    try:
        number = float(value)
        if np.isfinite(number):
            return f"{number:.2f}"
    except (TypeError, ValueError):
        pass
    return "N/A"


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


def sidebar_controls() -> tuple[list[str], int, AdvisorSettings]:
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
    st.sidebar.header("Advisor Mode")
    profile = st.sidebar.selectbox("Risk profile", ["Balanced", "Conservative", "Aggressive"], index=0)
    defaults = {
        "Conservative": {"risk": 0.5, "stop": 8.0, "max_position": 10.0},
        "Balanced": {"risk": 1.0, "stop": 10.0, "max_position": 15.0},
        "Aggressive": {"risk": 1.5, "stop": 12.0, "max_position": 20.0},
    }[profile]
    account_size = st.sidebar.number_input("Account size for sizing ($)", min_value=1000, value=10000, step=500)
    risk_per_trade_pct = st.sidebar.slider("Max risk per trade (%)", 0.1, 3.0, defaults["risk"], 0.1)
    stop_loss_pct = st.sidebar.slider("Default stop-loss (%)", 3.0, 20.0, defaults["stop"], 0.5)
    max_position_pct = st.sidebar.slider("Max allocation per stock (%)", 2.0, 40.0, defaults["max_position"], 1.0)
    require_all_filters = st.sidebar.toggle("Show only professional-grade signals", value=True)

    st.sidebar.divider()
    st.sidebar.caption("Optional secrets: OPENAI_API_KEY, OPENAI_MODEL, NEWSAPI_KEY.")
    st.sidebar.caption("Without keys, the app uses Google News RSS plus keyword catalyst detection.")
    st.sidebar.caption("For true real-time quotes, connect a paid market-data provider later. yfinance may be delayed.")
    return tickers, max_news_items, AdvisorSettings(
        profile=profile,
        account_size=float(account_size),
        risk_per_trade_pct=float(risk_per_trade_pct),
        stop_loss_pct=float(stop_loss_pct),
        max_position_pct=float(max_position_pct),
        require_all_filters=bool(require_all_filters),
    )


def main() -> None:
    page_setup()
    tickers, max_news_items, advisor_settings = sidebar_controls()

    st.title("ZA-BORS Professional Stock Research")
    st.markdown(
        '<div class="risk-note">Professional-style research assistant only. It is not a licensed investment advisor, and signals must be reviewed manually before any trade.</div>',
        unsafe_allow_html=True,
    )

    trend = market_trend(tickers)
    col_1, col_2, col_3 = st.columns(3)
    col_1.metric("Market trend", trend["label"])
    col_2.metric("1M benchmark avg", f"{trend['avg_change']:.2f}%")
    col_3.metric("Scan universe", f"{trend['scanned']} tickers")
    st.caption(f"Last dashboard refresh: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}. Quote freshness depends on the data provider.")

    st.divider()
    st.subheader("Professional Watch / Buy Candidates")
    st.caption("Filters: NYSE/NASDAQ, market cap above $1B, positive catalyst, RSI below 45, price at least 10% below 52-week high, and advisor score above 65.")

    col_scan, col_clear = st.columns([2, 1])
    run_scan = col_scan.button("Run professional scan", type="primary")
    clear_cache = col_clear.button("Refresh market data")
    if clear_cache:
        st.cache_data.clear()
        st.success("Cached market/news data cleared. Run the scan again for fresh data.")

    if run_scan:
        signals, diagnostics = scan_tickers(
            tickers,
            max_news_items=max_news_items,
            advisor_settings=advisor_settings,
        )
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
