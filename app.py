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
OPPORTUNITY_UNIVERSE_PATH = "data/opportunity_universe.csv"
BLINK_UNIVERSE_PATH = "data/blink_universe.csv"

TRANSLATIONS = {
    "en": {
        "app_title": "ZA-BORS Professional Stock Research",
        "language": "Language",
        "scan_settings": "Scan Settings",
        "universe": "Universe",
        "default_universe": "Default liquid US list",
        "blink_universe": "Blink platform watchlist",
        "opportunity_universe": "High-upside watchlist: small caps, ADRs, Israel",
        "custom_tickers": "Custom tickers",
        "min_market_cap": "Minimum market cap filter",
        "min_market_cap_help": "Lower this to include small companies. $0 means no market-cap filter.",
        "max_tickers": "Max tickers to scan",
        "tickers": "Tickers",
        "news_items": "News items per ticker",
        "advisor_mode": "Advisor Mode",
        "risk_profile": "Risk profile",
        "balanced": "Balanced",
        "conservative": "Conservative",
        "aggressive": "Aggressive",
        "account_size": "Account size for sizing ($)",
        "max_risk": "Max risk per trade (%)",
        "stop_loss_pct": "Default stop-loss (%)",
        "max_allocation": "Max allocation per stock (%)",
        "only_professional": "Show only professional-grade signals",
        "optional_secrets": "Optional secrets: OPENAI_API_KEY, OPENAI_MODEL, NEWSAPI_KEY.",
        "fallback_news": "Without keys, the app uses Google News RSS plus keyword catalyst detection.",
        "real_time_note": "For true real-time quotes, connect a paid market-data provider later. yfinance may be delayed.",
        "blink_note": "Blink availability is a working list. Confirm each ticker in the Blink app before trading.",
        "risk_note": "Professional-style research assistant only. It is not a licensed investment advisor, and signals must be reviewed manually before any trade.",
        "market_trend": "Market trend",
        "benchmark_avg": "1M benchmark avg",
        "scan_universe": "Scan universe",
        "last_refresh": "Last dashboard refresh",
        "freshness": "Quote freshness depends on the data provider.",
        "candidates": "Professional Watch / Buy Candidates",
        "filters_caption": "Filters: NYSE/NASDAQ, market cap above $1B, positive catalyst, RSI below 45, price at least 10% below 52-week high, and advisor score above 65.",
        "filters_caption_dynamic": "Filters: NYSE/NASDAQ, selected market-cap minimum, positive catalyst, RSI below 45, price at least 10% below 52-week high, and advisor score above 65.",
        "run_scan": "Run professional scan",
        "refresh_data": "Refresh market data",
        "cache_cleared": "Cached market/news data cleared. Run the scan again for fresh data.",
        "no_signals": "No active buy signals yet. Run a scan or widen the custom universe.",
        "diagnostics": "Diagnostics / filtered tickers",
        "diagnostics_wait": "Diagnostics will appear after the first scan.",
        "watchlist": "My Watchlist",
        "watchlist_help": "Type a ticker and optional note, then press Add. The list is saved for this app session.",
        "notes": "Notes",
        "notes_placeholder": "Why are you watching it?",
        "add_watchlist": "Add to watchlist",
        "remove": "Remove",
        "added_to_watchlist": "{ticker} was added to your watchlist.",
        "already_in_watchlist": "{ticker} is already in your watchlist.",
        "empty_watchlist": "Your watchlist is empty.",
        "added": "Added",
        "starting_scan": "Starting scan...",
        "scanning": "Scanning",
        "advisor_view": "Advisor View",
        "score": "Score",
        "profile": "Profile",
        "catalyst": "The Catalyst",
        "below_high": "Below 52W high",
        "market_cap": "Market cap",
        "volatility": "30D volatility",
        "action_plan": "Professional Action Plan",
        "entry_zone": "entry zone near",
        "stop_loss": "stop-loss",
        "take_profit": "20% take-profit target",
        "risk_reward": "estimated risk/reward",
        "position_sizing": "Position Sizing",
        "suggested": "suggested",
        "shares": "shares",
        "position_value": "position value",
        "at_risk": "at risk",
        "news": "News",
        "no_history": "No price history returned by yfinance.",
        "skipped": "Skipped",
        "signal": "Signal",
        "filtered": "Filtered",
        "error": "Error",
        "diag_ticker": "Ticker",
        "diag_status": "Status",
        "diag_exchange": "Exchange",
        "diag_market_cap": "Market cap",
        "diag_rsi": "RSI 14D",
        "diag_distance": "Below 52W high",
        "diag_score": "Advisor score",
        "diag_verdict": "Verdict",
        "diag_positive": "Positive catalyst",
        "diag_reason": "Reason",
        "no_news": "No recent news was found.",
        "no_catalyst": "Recent headlines did not show a concrete positive-change catalyst. Add an OpenAI API key for stricter LLM analysis.",
        "keyword_detected": "Keyword analysis detected a possible {catalyst}, so this should be reviewed manually before trading.",
        "no_catalyst_summary": "No catalyst summary returned.",
        "passed": "Passed all filters.",
        "failed_blink": "Failed tradeability filter: exchange or market cap.",
        "failed_catalyst": "No concrete positive catalyst.",
        "failed_technical": "Failed buy-low technical validation.",
        "strong": "Strong research candidate",
        "watch": "Watch closely",
        "avoid": "Do not chase",
    },
    "he": {
        "app_title": "ZA-BORS מחקר מניות מקצועי",
        "language": "שפה",
        "scan_settings": "הגדרות סריקה",
        "universe": "מאגר מניות",
        "default_universe": "רשימת מניות אמריקאיות נזילות",
        "blink_universe": "רשימת BLINK",
        "opportunity_universe": "רשימת הזדמנויות: קטנות, ADR וישראליות",
        "custom_tickers": "סימולים מותאמים אישית",
        "min_market_cap": "סינון שווי שוק מינימלי",
        "min_market_cap_help": "הורד את הרף כדי לכלול חברות קטנות. $0 מבטל את סינון שווי השוק.",
        "max_tickers": "מספר מניות מקסימלי לסריקה",
        "tickers": "סימולי מניות",
        "news_items": "מספר חדשות לכל מניה",
        "advisor_mode": "מצב יועץ",
        "risk_profile": "פרופיל סיכון",
        "balanced": "מאוזן",
        "conservative": "שמרני",
        "aggressive": "אגרסיבי",
        "account_size": "גודל תיק לחישוב פוזיציה ($)",
        "max_risk": "סיכון מקסימלי לעסקה (%)",
        "stop_loss_pct": "סטופ-לוס ברירת מחדל (%)",
        "max_allocation": "הקצאה מקסימלית למניה (%)",
        "only_professional": "הצג רק איתותים ברמה מקצועית",
        "optional_secrets": "מפתחות אופציונליים: OPENAI_API_KEY, OPENAI_MODEL, NEWSAPI_KEY.",
        "fallback_news": "ללא מפתחות, האפליקציה משתמשת ב-Google News RSS ובזיהוי קטליזטורים לפי מילות מפתח.",
        "real_time_note": "לציטוטים בזמן אמת מלא יש לחבר ספק נתוני שוק בתשלום. yfinance עשוי להיות מעוכב.",
        "blink_note": "רשימת BLINK היא רשימת עבודה. לפני מסחר אמיתי יש לוודא שכל סימול מופיע באפליקציית BLINK.",
        "risk_note": "זהו עוזר מחקר בסגנון מקצועי בלבד. הוא אינו יועץ השקעות מורשה, וכל איתות דורש בדיקה ידנית לפני פעולה.",
        "market_trend": "מגמת שוק",
        "benchmark_avg": "ממוצע מדדים לחודש",
        "scan_universe": "מניות בסריקה",
        "last_refresh": "עדכון אחרון",
        "freshness": "רעננות המחירים תלויה בספק הנתונים.",
        "candidates": "מעקב מקצועי / מועמדות לקנייה",
        "filters_caption": "סינונים: NYSE/NASDAQ, שווי שוק מעל $1B, קטליזטור חיובי, RSI נמוך מ-45, מחיר לפחות 10% מתחת לשיא 52 שבועות, וציון יועץ מעל 65.",
        "filters_caption_dynamic": "סינונים: NYSE/NASDAQ, רף שווי השוק שבחרת, קטליזטור חיובי, RSI נמוך מ-45, מחיר לפחות 10% מתחת לשיא 52 שבועות, וציון יועץ מעל 65.",
        "run_scan": "הפעל סריקה מקצועית",
        "refresh_data": "רענן נתוני שוק",
        "cache_cleared": "נתוני השוק והחדשות נוקו מהמטמון. הפעל סריקה מחדש לקבלת נתונים טריים.",
        "no_signals": "אין כרגע איתותי קנייה פעילים. הפעל סריקה או הרחב את מאגר המניות.",
        "diagnostics": "אבחון / מניות שסוננו",
        "diagnostics_wait": "האבחון יופיע לאחר הסריקה הראשונה.",
        "watchlist": "רשימת מעקב אישית",
        "watchlist_help": "כתוב סימול מניה והערה אופציונלית, ואז לחץ הוסף. הרשימה נשמרת בסשן של האפליקציה.",
        "notes": "הערות",
        "notes_placeholder": "למה אתה עוקב אחריה?",
        "add_watchlist": "הוסף לרשימת מעקב",
        "remove": "הסר",
        "added_to_watchlist": "{ticker} נוספה לרשימת המעקב.",
        "already_in_watchlist": "{ticker} כבר נמצאת ברשימת המעקב.",
        "empty_watchlist": "רשימת המעקב ריקה.",
        "added": "נוסף בתאריך",
        "starting_scan": "מתחיל סריקה...",
        "scanning": "סורק",
        "advisor_view": "מבט יועץ",
        "score": "ציון",
        "profile": "פרופיל",
        "catalyst": "הקטליזטור",
        "below_high": "מתחת לשיא 52 שבועות",
        "market_cap": "שווי שוק",
        "volatility": "תנודתיות 30 יום",
        "action_plan": "תוכנית פעולה מקצועית",
        "entry_zone": "אזור כניסה סביב",
        "stop_loss": "סטופ-לוס",
        "take_profit": "יעד רווח 20%",
        "risk_reward": "יחס סיכון/סיכוי משוער",
        "position_sizing": "גודל פוזיציה",
        "suggested": "מוצע",
        "shares": "מניות",
        "position_value": "שווי פוזיציה",
        "at_risk": "בסיכון",
        "news": "חדשה",
        "no_history": "לא התקבלו נתוני מחיר מ-yfinance.",
        "skipped": "דולג",
        "signal": "איתות",
        "filtered": "סונן",
        "error": "שגיאה",
        "diag_ticker": "סימול",
        "diag_status": "סטטוס",
        "diag_exchange": "בורסה",
        "diag_market_cap": "שווי שוק",
        "diag_rsi": "RSI 14 יום",
        "diag_distance": "מרחק משיא 52 שבועות",
        "diag_score": "ציון יועץ",
        "diag_verdict": "החלטת יועץ",
        "diag_positive": "קטליזטור חיובי",
        "diag_reason": "סיבה",
        "no_news": "לא נמצאו חדשות עדכניות.",
        "no_catalyst": "הכותרות האחרונות לא הראו קטליזטור חיובי ממשי. הוסף מפתח OpenAI לניתוח AI מדויק יותר.",
        "keyword_detected": "זיהוי לפי מילות מפתח מצא אפשרות לקטליזטור מסוג {catalyst}, ולכן יש לבדוק זאת ידנית לפני פעולה.",
        "no_catalyst_summary": "לא התקבל סיכום קטליזטור.",
        "passed": "עבר את כל הסינונים.",
        "failed_blink": "נכשל בסינון סחירות: בורסה או שווי שוק.",
        "failed_catalyst": "לא נמצא קטליזטור חיובי ממשי.",
        "failed_technical": "נכשל באימות הטכני של קנייה במחיר נמוך.",
        "strong": "כדאי מאוד",
        "watch": "כדאי לעקוב",
        "avoid": "לא כדאי עכשיו",
    },
}

PROFILE_TO_KEY = {
    "Balanced": "balanced",
    "Conservative": "conservative",
    "Aggressive": "aggressive",
}

VERDICT_TO_KEY = {
    "Strong research candidate": "strong",
    "Watch closely": "watch",
    "Do not chase": "avoid",
}

RISK_TRANSLATIONS_HE = {
    "Catalyst confidence is not high enough for blind execution.": "רמת הביטחון בקטליזטור אינה גבוהה מספיק לפעולה אוטומטית.",
    "High short-term volatility; position size should be reduced.": "תנודתיות קצרה גבוהה; מומלץ להקטין גודל פוזיציה.",
    "High beta; stock may move harder than the market.": "Beta גבוה; המניה עשויה לנוע חזק יותר מהשוק.",
    "RSI filter did not pass.": "סינון RSI לא עבר.",
    "Price is not far enough below its 52-week high.": "המחיר אינו רחוק מספיק משיא 52 השבועות.",
    "Main risks are execution timing, news reversal, and broad market weakness.": "הסיכונים המרכזיים הם תזמון ביצוע, היפוך חדשות וחולשה כללית בשוק.",
}

CATALYST_TRANSLATIONS_HE = {
    "earnings beat": "דוחות טובים מהצפוי",
    "regulatory approval": "אישור רגולטורי",
    "major contract": "חוזה משמעותי",
    "strategic partnership": "שותפות אסטרטגית",
    "breakthrough": "פריצת דרך",
    "product launch": "השקת מוצר",
    "market reaction": "תגובה חיובית בשוק",
    "earnings": "דוחות",
    "contract": "חוזה",
    "approval": "אישור",
    "guidance": "תחזית חברה",
    "partnership": "שותפות",
    "other": "אחר",
    "none": "אין",
}

MARKET_LABELS_HE = {
    "Risk-on": "נטייה חיובית",
    "Risk-off": "נטייה שלילית",
    "Mixed / neutral": "מעורב / ניטרלי",
}

DIAGNOSTIC_VALUE_TRANSLATIONS_HE = {
    "Skipped": "דולג",
    "Signal": "איתות",
    "Filtered": "סונן",
    "Error": "שגיאה",
    "Strong research candidate": "כדאי מאוד",
    "Watch closely": "כדאי לעקוב",
    "Do not chase": "לא כדאי עכשיו",
    "Passed all filters.": "עבר את כל הסינונים.",
    "Failed Blink filter: exchange or market cap.": "נכשל בסינון Blink: בורסה או שווי שוק.",
    "No concrete positive catalyst.": "לא נמצא קטליזטור חיובי ממשי.",
    "Failed buy-low technical validation.": "נכשל באימות הטכני של קנייה במחיר נמוך.",
}


def tr(lang: str, key: str) -> str:
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(key, TRANSLATIONS["en"].get(key, key))


def language_selector() -> str:
    query_lang = st.query_params.get("lang", "en")
    if isinstance(query_lang, list):
        query_lang = query_lang[0] if query_lang else "en"
    default_lang = "he" if query_lang == "he" else "en"
    options = ["English", "עברית"]
    default_index = 1 if default_lang == "he" else 0

    language_label = st.sidebar.radio(
        "Language / שפה",
        options,
        index=default_index,
        horizontal=True,
        key="language_selector",
    )
    lang = "he" if language_label == "עברית" else "en"

    if st.query_params.get("lang") != lang:
        st.query_params["lang"] = lang

    return lang


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
    min_market_cap: float


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


def apply_language_css(lang: str) -> None:
    if lang != "he":
        return
    st.markdown(
        """
        <style>
        .stApp, .stSidebar, .signal-card, .risk-note, .advisor-verdict {
            direction: rtl;
            text-align: right;
        }
        .ticker-line {
            flex-direction: row-reverse;
        }
        .advisor-verdict {
            border-right: 0;
            border-left: 4px solid #0f766e;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=60 * 60)
def load_default_universe() -> pd.DataFrame:
    return pd.read_csv(DEFAULT_UNIVERSE_PATH)


@st.cache_data(ttl=60 * 60)
def load_opportunity_universe() -> pd.DataFrame:
    return pd.read_csv(OPPORTUNITY_UNIVERSE_PATH)


@st.cache_data(ttl=60 * 60)
def load_blink_universe() -> pd.DataFrame:
    return pd.read_csv(BLINK_UNIVERSE_PATH)


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


def technicals_from_snapshot(snapshot: dict[str, Any], min_market_cap: float = MIN_MARKET_CAP) -> dict[str, Any]:
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
    market_cap_ok = bool((min_market_cap <= 0) or (market_cap and market_cap >= min_market_cap))

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


def analyze_catalyst(ticker: str, company_name: str, news_items: list[dict[str, str]], lang: str) -> CatalystResult:
    if not news_items:
        return CatalystResult(ticker, False, tr(lang, "no_news"), "none", 0.0)

    openai_key = get_secret_or_env("OPENAI_API_KEY")
    if openai_key:
        try:
            return analyze_catalyst_with_openai(ticker, company_name, news_items, lang)
        except Exception as exc:
            st.caption(f"LLM analysis fallback for {ticker}: {exc}")

    return analyze_catalyst_with_keywords(ticker, news_items, lang)


def analyze_catalyst_with_openai(
    ticker: str,
    company_name: str,
    news_items: list[dict[str, str]],
    lang: str,
) -> CatalystResult:
    from openai import OpenAI

    client = OpenAI(api_key=get_secret_or_env("OPENAI_API_KEY"))
    model = get_secret_or_env("OPENAI_MODEL") or "gpt-5.2"
    news_text = "\n".join(
        f"- {item['title']} | {item.get('summary', '')} | {item.get('source', '')}"
        for item in news_items
    )

    output_language = "Hebrew" if lang == "he" else "English"
    prompt = f"""
Analyze these recent financial headlines for {ticker} ({company_name}).

Return JSON only with this shape:
{{
  "has_positive_catalyst": true,
  "summary": "Exactly two concise sentences explaining why the news may create positive change.",
  "catalyst_type": "earnings|contract|approval|breakthrough|guidance|partnership|other|none",
  "confidence": 0.0
}}

The "summary" field must be written in {output_language}.
If {output_language} is Hebrew, write clear natural Hebrew and do not mix English except ticker symbols or company names.

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
        summary=str(payload.get("summary") or tr(lang, "no_catalyst_summary")),
        catalyst_type=str(payload.get("catalyst_type") or "other"),
        confidence=float(payload.get("confidence") or 0.0),
    )


def analyze_catalyst_with_keywords(ticker: str, news_items: list[dict[str, str]], lang: str) -> CatalystResult:
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
            summary=tr(lang, "no_catalyst"),
            catalyst_type="none",
            confidence=0.25,
        )

    top_headline = news_items[0].get("title") or "Recent news"
    catalyst_type = matches[0]
    catalyst_label = translate_catalyst_type(catalyst_type, lang)
    if lang == "he":
        summary = tr(lang, "keyword_detected").format(catalyst=catalyst_label)
    else:
        summary = f"{top_headline}. {tr(lang, 'keyword_detected').format(catalyst=catalyst_label)}"
    return CatalystResult(
        ticker=ticker,
        has_positive_catalyst=True,
        summary=summary,
        catalyst_type=catalyst_type,
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
    lang: str,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    signals: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    progress = st.progress(0, text=tr(lang, "starting_scan"))

    for index, ticker in enumerate(tickers, start=1):
        ticker = ticker.strip().upper()
        progress.progress(index / len(tickers), text=f"{tr(lang, 'scanning')} {ticker} ({index}/{len(tickers)})")

        try:
            snapshot = fetch_market_snapshot(ticker)
            technicals = technicals_from_snapshot(snapshot, advisor_settings.min_market_cap)
            if not technicals.get("valid"):
                diagnostics.append({"ticker": ticker, "status": tr(lang, "skipped"), "reason": tr(lang, "no_history")})
                continue

            blink_ok = technicals["exchange_ok"] and technicals["market_cap_ok"]
            technical_ok = technicals["rsi_ok"] and technicals["dip_ok"]
            company_name = str(technicals["name"])
            news_items = fetch_news(ticker, company_name, max_items=max_news_items)
            catalyst = analyze_catalyst(ticker, company_name, news_items, lang)
            advisor = build_advisor_view(technicals, catalyst, advisor_settings)

            diagnostics.append(
                {
                    "ticker": ticker,
                    "status": tr(lang, "signal") if advisor["is_actionable"] else tr(lang, "filtered"),
                    "exchange": technicals["exchange"],
                    "market_cap": technicals["market_cap"],
                    "rsi_14": technicals["rsi_14"],
                    "distance_from_high": technicals["distance_from_high"],
                    "advisor_score": advisor["score"],
                    "verdict": translate_verdict(advisor["verdict"], lang),
                    "positive_catalyst": catalyst.has_positive_catalyst,
                    "reason": filter_reason(blink_ok, technical_ok, catalyst, lang),
                }
            )

            if advisor["is_actionable"] or not advisor_settings.require_all_filters:
                signals.append({**technicals, "catalyst": catalyst, "advisor": advisor, "news": news_items})
        except Exception as exc:
            diagnostics.append({"ticker": ticker, "status": tr(lang, "error"), "reason": str(exc)})

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


def filter_reason(blink_ok: bool, technical_ok: bool, catalyst: CatalystResult, lang: str) -> str:
    if not blink_ok:
        return tr(lang, "failed_blink")
    if not catalyst.has_positive_catalyst:
        return tr(lang, "failed_catalyst")
    if not technical_ok:
        return tr(lang, "failed_technical")
    return tr(lang, "passed")


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


def render_signal_card(signal: dict[str, Any], lang: str) -> None:
    catalyst: CatalystResult = signal["catalyst"]
    advisor: dict[str, Any] = signal["advisor"]
    rsi = signal["rsi_14"]
    distance = signal["distance_from_high"]
    market_cap_b = (signal["market_cap"] or 0) / 1_000_000_000
    volatility = signal.get("volatility_30d")
    beta = signal.get("beta")
    rsi_badge = "OK" if signal["rsi_ok"] else "!"
    dip_badge = "OK" if signal["dip_ok"] else "!"
    risk_items = "".join(f"<li>{translate_risk(risk, lang)}</li>" for risk in advisor["risks"])
    news_links = " ".join(
        f'<a href="{item["url"]}" target="_blank">{tr(lang, "news")} {idx}</a>'
        for idx, item in enumerate(signal["news"][:3], start=1)
        if item.get("url")
    )
    verdict = tr(lang, VERDICT_TO_KEY.get(advisor["verdict"], advisor["verdict"]))
    profile = tr(lang, PROFILE_TO_KEY.get(advisor["profile"], advisor["profile"]))
    catalyst_summary = translate_catalyst_summary(catalyst.summary, lang)
    catalyst_type = translate_catalyst_type(catalyst.catalyst_type, lang)

    st.markdown(
        f"""
        <div class="signal-card">
            <div class="ticker-line">
                <div><span class="ticker-symbol">{signal["ticker"]}</span> <span>{signal["name"]}</span></div>
                <div class="price-text">${signal["current_price"]:.2f}</div>
            </div>
            <div class="advisor-verdict">
                <strong>{tr(lang, "advisor_view")}:</strong> {verdict} | {tr(lang, "score")} {advisor["score"]}/100 | {tr(lang, "profile")}: {profile}
            </div>
            <p><strong>{tr(lang, "catalyst")}:</strong> {catalyst_summary}</p>
            <span class="pill">RSI 14D: {rsi:.1f} {rsi_badge}</span>
            <span class="pill">{tr(lang, "below_high")}: {distance:.1f}% {dip_badge}</span>
            <span class="pill">{tr(lang, "market_cap")}: ${market_cap_b:.1f}B</span>
            <span class="pill">{tr(lang, "volatility")}: {format_optional_pct(volatility)}</span>
            <span class="pill">Beta: {format_optional_number(beta)}</span>
            <span class="pill">{tr(lang, "catalyst")}: {catalyst_type}</span>
            <p><strong>{tr(lang, "action_plan")}:</strong> {tr(lang, "entry_zone")} ${signal["entry_price"]:.2f};
            {tr(lang, "stop_loss")} ${advisor["stop_loss"]:.2f}; {tr(lang, "take_profit")} ${advisor["take_profit"]:.2f};
            {tr(lang, "risk_reward")} {advisor["risk_reward"]:.2f}:1.</p>
            <p><strong>{tr(lang, "position_sizing")}:</strong> {tr(lang, "suggested")} {advisor["suggested_shares"]} {tr(lang, "shares")},
            ${advisor["suggested_position_value"]:.0f} {tr(lang, "position_value")}, ${advisor["dollars_at_risk"]:.0f} {tr(lang, "at_risk")}.</p>
            <ul class="risk-list">{risk_items}</ul>
            <p>{news_links}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def translate_risk(risk: str, lang: str) -> str:
    if lang == "he":
        return RISK_TRANSLATIONS_HE.get(risk, risk)
    return risk


def translate_catalyst_type(catalyst_type: str, lang: str) -> str:
    if lang == "he":
        return CATALYST_TRANSLATIONS_HE.get(catalyst_type, catalyst_type)
    return catalyst_type


def translate_verdict(verdict: str, lang: str) -> str:
    return tr(lang, VERDICT_TO_KEY.get(verdict, verdict))


def translate_market_label(label: str, lang: str) -> str:
    if lang == "he":
        return MARKET_LABELS_HE.get(label, label)
    return label


def translate_catalyst_summary(summary: str, lang: str) -> str:
    if lang != "he":
        return summary
    replacements = {
        "Keyword analysis detected a possible": "זיהוי לפי מילות מפתח מצא אפשרות לקטליזטור מסוג",
        "so this should be reviewed manually before trading.": "ולכן יש לבדוק זאת ידנית לפני פעולה.",
        "Recent headlines did not show a concrete positive-change catalyst. Add an OpenAI API key for stricter LLM analysis.": tr(lang, "no_catalyst"),
        "No recent news was found.": tr(lang, "no_news"),
        "No catalyst summary returned.": tr(lang, "no_catalyst_summary"),
    }
    translated = summary
    for english, hebrew in replacements.items():
        translated = translated.replace(english, hebrew)
    for english, hebrew in CATALYST_TRANSLATIONS_HE.items():
        translated = re.sub(rf"\b{re.escape(english)}\b", hebrew, translated, flags=re.IGNORECASE)
    hebrew_anchor = "זיהוי לפי מילות מפתח"
    if hebrew_anchor in translated:
        prefix, suffix = translated.split(hebrew_anchor, 1)
        if prefix and sum(char.isascii() and char.isalpha() for char in prefix) > 12:
            translated = f"{hebrew_anchor}{suffix}"
    return translated


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


def render_watchlist(lang: str) -> None:
    st.subheader(tr(lang, "watchlist"))
    st.caption(tr(lang, "watchlist_help"))
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = []

    with st.form("watchlist_form", clear_on_submit=True):
        col_a, col_b = st.columns([1, 3])
        ticker = col_a.text_input("Ticker", placeholder="FUTU").upper().strip()
        notes = col_b.text_input(tr(lang, "notes"), placeholder=tr(lang, "notes_placeholder"))
        submitted = st.form_submit_button(tr(lang, "add_watchlist"))

    if submitted and ticker:
        existing = {row["Ticker"] for row in st.session_state.watchlist}
        if ticker in existing:
            st.warning(tr(lang, "already_in_watchlist").format(ticker=ticker))
        else:
            st.session_state.watchlist.append(
                {
                    "Ticker": ticker,
                    "Notes": notes,
                    "Added": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }
            )
            st.success(tr(lang, "added_to_watchlist").format(ticker=ticker))

    if not st.session_state.watchlist:
        st.info(tr(lang, "empty_watchlist"))
        return

    for index, row in enumerate(list(st.session_state.watchlist)):
        col_ticker, col_notes, col_added, col_remove = st.columns([1, 4, 1.4, 1])
        col_ticker.markdown(f"**{row['Ticker']}**")
        col_notes.write(row.get("Notes") or "-")
        col_added.caption(f"{tr(lang, 'added')}: {row.get('Added', '-')}")
        if col_remove.button(tr(lang, "remove"), key=f"remove_watchlist_{index}_{row['Ticker']}"):
            st.session_state.watchlist.pop(index)
            st.rerun()


def localize_diagnostics(df: pd.DataFrame, lang: str) -> pd.DataFrame:
    if df.empty:
        return df
    localized = df.copy()
    if lang == "he":
        for column in ["status", "verdict", "reason"]:
            if column in localized.columns:
                localized[column] = localized[column].map(lambda value: DIAGNOSTIC_VALUE_TRANSLATIONS_HE.get(str(value), value))
        column_names = {
            "ticker": tr(lang, "diag_ticker"),
            "status": tr(lang, "diag_status"),
            "exchange": tr(lang, "diag_exchange"),
            "market_cap": tr(lang, "diag_market_cap"),
            "rsi_14": tr(lang, "diag_rsi"),
            "distance_from_high": tr(lang, "diag_distance"),
            "advisor_score": tr(lang, "diag_score"),
            "verdict": tr(lang, "diag_verdict"),
            "positive_catalyst": tr(lang, "diag_positive"),
            "reason": tr(lang, "diag_reason"),
        }
        localized = localized.rename(columns=column_names)
    return localized


def sidebar_controls(lang: str) -> tuple[list[str], int, AdvisorSettings]:
    st.sidebar.header(tr(lang, "scan_settings"))
    default_universe = load_default_universe()
    opportunity_universe = load_opportunity_universe()
    blink_universe = load_blink_universe()
    universe_labels = [
        tr(lang, "default_universe"),
        tr(lang, "blink_universe"),
        tr(lang, "opportunity_universe"),
        tr(lang, "custom_tickers"),
    ]
    universe_mode = st.sidebar.radio(tr(lang, "universe"), universe_labels, index=0)

    if universe_mode == tr(lang, "default_universe"):
        max_count = st.sidebar.slider(tr(lang, "max_tickers"), 5, len(default_universe), 15)
        tickers = default_universe["ticker"].head(max_count).tolist()
    elif universe_mode == tr(lang, "blink_universe"):
        max_count = st.sidebar.slider(tr(lang, "max_tickers"), 5, len(blink_universe), min(35, len(blink_universe)))
        tickers = blink_universe["ticker"].head(max_count).tolist()
        st.sidebar.caption(tr(lang, "blink_note"))
    elif universe_mode == tr(lang, "opportunity_universe"):
        max_count = st.sidebar.slider(tr(lang, "max_tickers"), 5, len(opportunity_universe), min(25, len(opportunity_universe)))
        tickers = opportunity_universe["ticker"].head(max_count).tolist()
    else:
        raw = st.sidebar.text_area(tr(lang, "tickers"), value="AAPL, MSFT, NVDA, AMD, TSLA")
        tickers = [item.strip().upper() for item in raw.replace("\n", ",").split(",") if item.strip()]

    market_cap_options = {
        "No minimum / ללא מינימום": 0.0,
        "$50M": 50_000_000.0,
        "$100M": 100_000_000.0,
        "$300M": 300_000_000.0,
        "$1B": 1_000_000_000.0,
    }
    default_cap_index = 4 if universe_mode == tr(lang, "default_universe") else 1
    market_cap_label = st.sidebar.selectbox(
        tr(lang, "min_market_cap"),
        list(market_cap_options),
        index=default_cap_index,
        help=tr(lang, "min_market_cap_help"),
    )
    min_market_cap = market_cap_options[market_cap_label]
    max_news_items = st.sidebar.slider(tr(lang, "news_items"), 2, 10, 5)
    st.sidebar.divider()
    st.sidebar.header(tr(lang, "advisor_mode"))
    profile_options = ["Balanced", "Conservative", "Aggressive"]
    profile_label_to_value = {tr(lang, PROFILE_TO_KEY[value]): value for value in profile_options}
    profile_label = st.sidebar.selectbox(tr(lang, "risk_profile"), list(profile_label_to_value), index=0)
    profile = profile_label_to_value[profile_label]
    defaults = {
        "Conservative": {"risk": 0.5, "stop": 8.0, "max_position": 10.0},
        "Balanced": {"risk": 1.0, "stop": 10.0, "max_position": 15.0},
        "Aggressive": {"risk": 1.5, "stop": 12.0, "max_position": 20.0},
    }[profile]
    account_size = st.sidebar.number_input(tr(lang, "account_size"), min_value=1000, value=10000, step=500)
    risk_per_trade_pct = st.sidebar.slider(tr(lang, "max_risk"), 0.1, 3.0, defaults["risk"], 0.1)
    stop_loss_pct = st.sidebar.slider(tr(lang, "stop_loss_pct"), 3.0, 20.0, defaults["stop"], 0.5)
    max_position_pct = st.sidebar.slider(tr(lang, "max_allocation"), 2.0, 40.0, defaults["max_position"], 1.0)
    require_all_filters = st.sidebar.toggle(tr(lang, "only_professional"), value=True)

    st.sidebar.divider()
    st.sidebar.caption(tr(lang, "optional_secrets"))
    st.sidebar.caption(tr(lang, "fallback_news"))
    st.sidebar.caption(tr(lang, "real_time_note"))
    return tickers, max_news_items, AdvisorSettings(
        profile=profile,
        account_size=float(account_size),
        risk_per_trade_pct=float(risk_per_trade_pct),
        stop_loss_pct=float(stop_loss_pct),
        max_position_pct=float(max_position_pct),
        require_all_filters=bool(require_all_filters),
        min_market_cap=float(min_market_cap),
    )


def main() -> None:
    page_setup()
    lang = language_selector()
    apply_language_css(lang)
    tickers, max_news_items, advisor_settings = sidebar_controls(lang)

    st.title(tr(lang, "app_title"))
    st.markdown(
        f'<div class="risk-note">{tr(lang, "risk_note")}</div>',
        unsafe_allow_html=True,
    )

    trend = market_trend(tickers)
    col_1, col_2, col_3 = st.columns(3)
    col_1.metric(tr(lang, "market_trend"), translate_market_label(trend["label"], lang))
    col_2.metric(tr(lang, "benchmark_avg"), f"{trend['avg_change']:.2f}%")
    col_3.metric(tr(lang, "scan_universe"), f"{trend['scanned']}")
    st.caption(f"{tr(lang, 'last_refresh')}: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}. {tr(lang, 'freshness')}")

    st.divider()
    st.subheader(tr(lang, "candidates"))
    st.caption(tr(lang, "filters_caption_dynamic"))

    col_scan, col_clear = st.columns([2, 1])
    run_scan = col_scan.button(tr(lang, "run_scan"), type="primary")
    clear_cache = col_clear.button(tr(lang, "refresh_data"))
    if clear_cache:
        st.cache_data.clear()
        st.success(tr(lang, "cache_cleared"))

    if run_scan:
        signals, diagnostics = scan_tickers(
            tickers,
            max_news_items=max_news_items,
            advisor_settings=advisor_settings,
            lang=lang,
        )
        st.session_state["signals"] = signals
        st.session_state["diagnostics"] = diagnostics

    signals = st.session_state.get("signals", [])
    diagnostics = st.session_state.get("diagnostics", pd.DataFrame())

    if signals:
        for signal in signals:
            render_signal_card(signal, lang)
    else:
        st.info(tr(lang, "no_signals"))

    with st.expander(tr(lang, "diagnostics"), expanded=False):
        if isinstance(diagnostics, pd.DataFrame) and not diagnostics.empty:
            st.dataframe(localize_diagnostics(diagnostics, lang), use_container_width=True)
        else:
            st.caption(tr(lang, "diagnostics_wait"))

    st.divider()
    render_watchlist(lang)


if __name__ == "__main__":
    main()
