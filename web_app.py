from __future__ import annotations

import json
import os
import re
import secrets
import time
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
WATCHLIST_PATH = DATA_DIR / "watchlist.json"
WATCHLIST_SEED_PATH = DATA_DIR / "watchlist_seed.json"
BLINK_UNIVERSE_PATH = DATA_DIR / "blink_universe.csv"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
ACTIONABLE_VERDICTS = {"כדאי לקנות"}

POSITIVE_NEWS_TERMS = {
    "approval": 18,
    "approved": 18,
    "fda approval": 24,
    "contract": 18,
    "deal": 16,
    "agreement": 14,
    "partnership": 16,
    "investment": 18,
    "funding": 18,
    "financing": 14,
    "cash infusion": 24,
    "strategic investment": 24,
    "buyout": 26,
    "acquisition": 22,
    "merger": 20,
    "takeover": 24,
    "asset sale": 14,
    "sale": 10,
    "beats": 16,
    "beat": 14,
    "raises guidance": 20,
    "guidance raised": 20,
    "launch": 12,
    "breakthrough": 20,
    "upgrade": 10,
}

NEGATIVE_NEWS_TERMS = {
    "bankruptcy": 35,
    "delisting": 32,
    "going concern": 30,
    "sec investigation": 28,
    "investigation": 18,
    "lawsuit": 14,
    "fraud": 35,
    "offering": 18,
    "dilution": 24,
    "downgrade": 12,
    "misses": 16,
    "missed": 14,
    "cuts guidance": 22,
    "guidance cut": 22,
    "halts": 26,
    "halted": 26,
}

LEVERAGED_SCAN_QUERIES = [
    "Tradr 2X Long Daily ETF",
    "2X Long Daily ETF",
    "Leverage Shares 2x Long Daily ETF",
    "GraniteShares 2x Long Daily ETF",
]

LEVERAGED_SCAN_SEEDS = [
    {"ticker": "NEBX", "name": "Tradr 2X Long NBIS Daily ETF", "category": "2X Long / leveraged ETF"},
    {"ticker": "NBIG", "name": "Leverage Shares 2x Long NBIS Daily ETF", "category": "2X Long / leveraged ETF"},
    {"ticker": "NBIL", "name": "GraniteShares 2x Long NBIS Daily ETF", "category": "2X Long / leveraged ETF"},
    {"ticker": "RGTU", "name": "Tradr 2X Long RGTI Daily ETF", "category": "2X Long / leveraged ETF"},
    {"ticker": "TARK", "name": "Tradr 2X Long Innovation ETF", "category": "2X Long / leveraged ETF"},
    {"ticker": "MQQQ", "name": "Tradr 2X Long Innovation 100 Monthly ETF", "category": "2X Long / leveraged ETF"},
    {"ticker": "QQQP", "name": "Tradr 2X Long Innovation 100 Quarterly ETF", "category": "2X Long / leveraged ETF"},
    {"ticker": "SPYQ", "name": "Tradr 2X Long SPY Quarterly ETF", "category": "2X Long / leveraged ETF"},
]

app = FastAPI(title="ZA-BORS")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


class WatchItem(BaseModel):
    ticker: str
    notes: str = ""
    buy_price: float = 0.0
    invested_amount: float = 0.0
    target_buy_min: float = 0.0
    target_exit_max: float = 0.0
    owned: bool = False


class ScanRequest(BaseModel):
    tickers: int = 100
    min_market_cap: float = 50_000_000
    min_investment: float = 5
    max_investment: float = 100


def auth_settings() -> tuple[str | None, str | None]:
    return os.getenv("ZA_BORS_USERNAME"), os.getenv("ZA_BORS_PASSWORD")


def session_secret() -> str:
    return os.getenv("ZA_BORS_SESSION_SECRET") or os.getenv("ZA_BORS_PASSWORD") or "local-dev"


def sign_session(username: str) -> str:
    issued_at = str(int(time.time()))
    payload = f"{username}:{issued_at}"
    signature = hmac_new(session_secret().encode(), payload.encode(), sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_session(token: str | None) -> str | None:
    if not token:
        return None

    parts = token.split(":")
    if len(parts) != 3:
        return None

    username, issued_at, signature = parts
    payload = f"{username}:{issued_at}"
    expected = hmac_new(session_secret().encode(), payload.encode(), sha256).hexdigest()
    if not compare_digest(signature, expected):
        return None

    try:
        age = time.time() - int(issued_at)
    except ValueError:
        return None

    if age > SESSION_MAX_AGE:
        return None
    return username


def require_login(request: Request) -> str:
    expected_username = os.getenv("ZA_BORS_USERNAME")
    expected_password = os.getenv("ZA_BORS_PASSWORD")

    if not expected_username or not expected_password:
        return "local"

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
    username = verify_session(token)
    if username:
        return username

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Login required",
    )


@app.get("/", response_class=HTMLResponse)
def login_home():
    template = templates.get_template("login.html")
    return template.render(app_name="ZA-BORS", error="")


@app.get("/app", response_class=HTMLResponse)
def app_home():
    template = templates.get_template("index.html")
    return template.render(app_name="ZA-BORS")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    template = templates.get_template("login.html")
    return template.render(app_name="ZA-BORS", error="")


@app.post("/api/login")
async def login(request: Request) -> JSONResponse:
    expected_username, expected_password = auth_settings()
    if not expected_username or not expected_password:
        return JSONResponse({"ok": True, "token": sign_session("local")})

    payload = await request.json()
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    username_ok = secrets.compare_digest(username, expected_username)
    password_ok = secrets.compare_digest(password, expected_password)
    if not username_ok or not password_ok:
        return JSONResponse({"ok": False, "message": "שם משתמש או סיסמה לא נכונים"}, status_code=401)

    return JSONResponse({"ok": True, "token": sign_session(username)})


@app.post("/api/logout")
def logout() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.get("/api/ping")
def ping(_: str = Depends(require_login)) -> dict[str, Any]:
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/universe")
def universe(_: str = Depends(require_login)) -> dict[str, Any]:
    df = pd.read_csv(BLINK_UNIVERSE_PATH)
    return {"tickers": df.head(100).to_dict(orient="records")}


@app.get("/api/search")
def search_stocks(
    q: str = "",
    _: str = Depends(require_login),
) -> dict[str, Any]:
    raw_query = q.strip()
    if not raw_query:
        return {"results": [], "checked": 0}

    search_terms = stock_search_terms(raw_query)
    normalized_terms = [term.lower() for term in search_terms]
    preferred_symbols = preferred_search_symbols(raw_query) or {term.upper() for term in search_terms if looks_like_symbol(term)}
    df = pd.read_csv(BLINK_UNIVERSE_PATH).fillna("")
    ticker_values = df["ticker"].astype(str).str.lower()
    name_values = df["name"].astype(str).str.lower()
    category_values = df["category"].astype(str).str.lower()
    mask = pd.Series(False, index=df.index)
    exact_mask = pd.Series(False, index=df.index)
    for term in normalized_terms:
        mask = mask | ticker_values.str.contains(term, regex=False) | name_values.str.contains(term, regex=False) | category_values.str.contains(term, regex=False)
        if looks_like_symbol(term):
            exact_mask = exact_mask | (ticker_values == term)

    exact_local = df.loc[exact_mask].to_dict(orient="records")
    partial_local = df.loc[mask & ~exact_mask].head(19).to_dict(orient="records")
    candidates = [
        {
            "ticker": str(row.get("ticker", "")).upper(),
            "name": row.get("name", ""),
            "category": row.get("category", ""),
            "source": "BLINK local list",
            "quoteType": "ETF" if "etf" in f"{row.get('name', '')} {row.get('category', '')}".lower() else "EQUITY",
            "exchange": "",
            "isLeveraged": is_leveraged_product(row.get("ticker", ""), row.get("name", ""), row.get("category", "")),
        }
        for row in [*exact_local, *partial_local]
    ]

    seen = {row["ticker"] for row in candidates}
    for term in search_terms:
        for row in live_symbol_search(term):
            if row["ticker"] not in seen:
                candidates.append(row)
                seen.add(row["ticker"])
            if len(candidates) >= 20:
                break
        if len(candidates) >= 20:
            break

    candidates.sort(key=lambda row: (row["ticker"] not in preferred_symbols, row["ticker"]))
    return {"results": candidates, "checked": len(candidates)}


@app.get("/api/watchlist")
def get_watchlist(_: str = Depends(require_login)) -> dict[str, Any]:
    rows = load_watchlist()
    enriched = []
    changed = False
    for row in rows:
        try:
            quote = fetch_quote(row["Ticker"])
            if not row.get("TargetBuyMin") and quote.get("suggestedBuyMin"):
                row["TargetBuyMin"] = float(quote["suggestedBuyMin"])
                changed = True
            if not row.get("TargetExitMax") and quote.get("suggestedExitMax"):
                row["TargetExitMax"] = float(quote["suggestedExitMax"])
                changed = True
            alerts = item_alerts(row, quote)
        except Exception as exc:
            quote = {"price": 0, "change": 0, "changePct": 0, "updatedAt": "N/A", "error": str(exc)}
            alerts = [f"{row['Ticker']}: לא הצלחתי להביא מחיר כרגע, אבל המניה נשארת ברשימת המעקב."]
        enriched.append({**row, "quote": quote, "alerts": alerts})
    if changed or rows:
        save_watchlist(rows)
    return JSONResponse(
        {"items": enriched, "market": market_risk()},
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.post("/api/watchlist")
def add_watchlist(item: WatchItem, _: str = Depends(require_login)) -> dict[str, Any]:
    rows = load_watchlist()
    ticker = item.ticker.upper().strip()
    if not ticker:
        return {"ok": False, "message": "Missing ticker"}
    if any(row["Ticker"] == ticker for row in rows):
        return {"ok": False, "message": f"{ticker} already exists"}
    rows.append(
        normalize_watchlist_row(
            {
                "Ticker": ticker,
                "Notes": item.notes,
                "Added": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "BuyPrice": float(item.buy_price or 0),
                "InvestedAmount": float(item.invested_amount or 0),
                "TargetBuyMin": float(item.target_buy_min or 0),
                "TargetExitMax": float(item.target_exit_max or 0),
                "Owned": bool(item.owned),
            }
        )
    )
    save_watchlist(rows)
    return {"ok": True}


@app.patch("/api/watchlist/{ticker}")
def update_watchlist(ticker: str, item: WatchItem, _: str = Depends(require_login)) -> dict[str, Any]:
    rows = load_watchlist()
    target = ticker.upper().strip()
    for row in rows:
        if row["Ticker"] == target:
            row["Notes"] = item.notes
            row["BuyPrice"] = float(item.buy_price or 0)
            row["InvestedAmount"] = float(item.invested_amount or 0)
            row["TargetBuyMin"] = float(item.target_buy_min or 0)
            row["TargetExitMax"] = float(item.target_exit_max or 0)
            row["Owned"] = bool(item.owned)
            row.update(normalize_watchlist_row(row))
            save_watchlist(rows)
            return {"ok": True}
    return {"ok": False, "message": "Ticker not found"}


@app.delete("/api/watchlist/{ticker}")
def delete_watchlist(ticker: str, _: str = Depends(require_login)) -> dict[str, Any]:
    target = ticker.upper().strip()
    rows = [row for row in load_watchlist() if row["Ticker"] != target]
    save_watchlist(rows)
    return {"ok": True}


@app.post("/api/scan")
def scan(req: ScanRequest, _: str = Depends(require_login)) -> JSONResponse:
    if req.max_investment < req.min_investment:
        req.min_investment, req.max_investment = req.max_investment, req.min_investment

    full_universe_df = pd.read_csv(BLINK_UNIVERSE_PATH).fillna("")
    base_universe_df = full_universe_df.head(min(max(req.tickers, 1), 100))
    leveraged_universe_df = full_universe_df[
        full_universe_df.apply(
            lambda row: is_leveraged_product(row.get("ticker", ""), row.get("name", ""), row.get("category", "")),
            axis=1,
        )
    ]
    live_leveraged_df = pd.DataFrame(live_leveraged_scan_candidates())
    universe_df = pd.concat([base_universe_df, leveraged_universe_df, live_leveraged_df]).drop_duplicates(subset=["ticker"])
    rows = []
    for item in universe_df.to_dict(orient="records"):
        ticker = str(item.get("ticker", ""))
        try:
            row = scan_one(ticker, req)
            row["category"] = item.get("category", "")
            row["isLeveraged"] = is_leveraged_product(row["ticker"], row["name"], row["category"])
            if row["isLeveraged"]:
                row["leverageWarning"] = "מוצר ממונף: רווח והפסד יכולים להיות מוכפלים, מתאים רק לסיכון גבוה."
            if row["priceInRange"] and is_buy_candidate(row):
                rows.append(row)
        except Exception as exc:
            continue
    rows.sort(
        key=lambda row: (
            verdict_order(row["verdict"]),
            -row.get("opportunityScore", 0),
            -row["score"],
            row.get("nearLow5mPct", 999),
            not row.get("isLeveraged"),
        )
    )
    return JSONResponse({"rows": rows, "scanned": len(universe_df)})


def scan_one(ticker: str, req: ScanRequest) -> dict[str, Any]:
    stock = yf.Ticker(ticker)
    info = safe_info(stock)
    fast = safe_fast_info(stock)
    hist = stock.history(period="1y", interval="1d", auto_adjust=False)
    close = hist["Close"].dropna() if not hist.empty else pd.Series(dtype=float)
    price = first_number(fast.get("last_price"), info.get("currentPrice"), info.get("regularMarketPrice"), close.iloc[-1] if len(close) else 0)
    previous_close = first_number(fast.get("previous_close"), info.get("previousClose"), close.iloc[-2] if len(close) >= 2 else 0)
    change = price - previous_close if price and previous_close else 0
    change_pct = (change / previous_close) * 100 if previous_close else 0
    high_52 = first_number(info.get("fiftyTwoWeekHigh"), fast.get("year_high"), close.max() if len(close) else 0)
    low_5m, high_5m, avg_5m = five_month_history_range(hist)
    distance = ((high_52 - price) / high_52) * 100 if high_52 else 0
    below_high_5m = ((high_5m - price) / high_5m) * 100 if high_5m else 0
    near_low_5m = ((price - low_5m) / low_5m) * 100 if low_5m else 999
    five_month_opportunity = is_five_month_opportunity(near_low_5m, below_high_5m)
    rsi = compute_rsi(close)
    market_cap = first_number(info.get("marketCap"))
    exchange = str(info.get("exchange") or info.get("fullExchangeName") or "")
    name = info.get("shortName") or info.get("longName") or ticker
    quote_type = str(info.get("quoteType") or "").upper()
    leveraged_or_etf = quote_type == "ETF" or is_leveraged_product(ticker, name, quote_type)
    exchange_ok = any(code in exchange.upper() for code in ["NMS", "NYQ", "NGM", "NCM", "NASDAQ", "NYSE", "ASE", "AMEX", "PCX", "BATS", "BTS", "CBOE"])
    cap_ok = leveraged_or_etf or req.min_market_cap <= 0 or market_cap >= req.min_market_cap
    price_in_range = price > 0 and req.min_investment <= price <= req.max_investment
    news_signal = analyze_news(stock.news if hasattr(stock, "news") else [])
    technical_risk = crash_risk(close, price, high_52, change_pct, rsi)
    catalyst = news_signal["positive"] and not news_signal["negative"]
    opportunity_score = five_month_opportunity_score(near_low_5m, below_high_5m)
    score = score_stock(rsi, distance, market_cap, news_signal, technical_risk, price_in_range, opportunity_score)
    buy_candidate = is_buy_setup(rsi, distance, news_signal, technical_risk, price_in_range, score, five_month_opportunity)
    verdict = "כדאי לקנות" if buy_candidate else "לא כדאי עכשיו"
    if not exchange_ok or not cap_ok or not price_in_range or technical_risk["avoid"]:
        verdict = "לא כדאי עכשיו"
    reason = reason_text(exchange_ok, cap_ok, price_in_range, news_signal, technical_risk, rsi, distance, five_month_opportunity, near_low_5m, below_high_5m)
    return {
        "ticker": ticker,
        "name": name,
        "price": price,
        "change": change,
        "changePct": change_pct,
        "low5m": low_5m,
        "high5m": high_5m,
        "avg5m": avg_5m,
        "exchange": exchange or "N/A",
        "marketCap": market_cap,
        "rsi": rsi,
        "distance": distance,
        "nearLow5mPct": near_low_5m,
        "belowHigh5mPct": below_high_5m,
        "opportunityScore": opportunity_score,
        "score": score,
        "verdict": verdict,
        "positiveCatalyst": catalyst,
        "priceInRange": price_in_range,
        "newsScore": news_signal["score"],
        "riskScore": technical_risk["score"],
        "catalystText": news_signal["summary"],
        "riskText": technical_risk["summary"],
        "latestNews": news_signal["latest"],
        "reason": reason,
        "scoreExplanation": score_explanation(rsi, distance, news_signal, technical_risk, price_in_range, near_low_5m, below_high_5m, opportunity_score),
    }


def load_watchlist() -> list[dict[str, Any]]:
    if not WATCHLIST_PATH.exists():
        seed_rows = load_watchlist_seed()
        if seed_rows:
            save_watchlist(seed_rows)
        return seed_rows
    try:
        data = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = normalize_watchlist_rows(data)
    if not rows:
        seed_rows = load_watchlist_seed()
        if seed_rows:
            save_watchlist(seed_rows)
            return seed_rows
    return rows


def load_watchlist_seed() -> list[dict[str, Any]]:
    if not WATCHLIST_SEED_PATH.exists():
        return []
    try:
        data = json.loads(WATCHLIST_SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return normalize_watchlist_rows(data)


def normalize_watchlist_rows(data: Any) -> list[dict[str, Any]]:
    rows = []
    for row in data if isinstance(data, list) else []:
        if isinstance(row, dict) and row.get("Ticker"):
            rows.append(normalize_watchlist_row(row))
    return rows


def normalize_watchlist_row(row: dict[str, Any]) -> dict[str, Any]:
    buy_price = float(row.get("BuyPrice") or 0)
    invested_amount = float(row.get("InvestedAmount") or 0)
    owned = bool(row.get("Owned", False)) and buy_price > 0 and invested_amount > 0
    if not owned:
        buy_price = 0.0
        invested_amount = 0.0

    return {
        "Ticker": str(row.get("Ticker", "")).upper().strip(),
        "Notes": str(row.get("Notes", "")),
        "Added": str(row.get("Added", "")),
        "BuyPrice": buy_price,
        "InvestedAmount": invested_amount,
        "TargetBuyMin": float(row.get("TargetBuyMin") or 0),
        "TargetExitMax": float(row.get("TargetExitMax") or 0),
        "Owned": owned,
    }


def save_watchlist(rows: list[dict[str, Any]]) -> None:
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_quote(ticker: str) -> dict[str, Any]:
    stock = yf.Ticker(ticker)
    info = safe_info(stock)
    fast = safe_fast_info(stock)
    price = first_number(fast.get("last_price"), info.get("currentPrice"), info.get("regularMarketPrice"))
    prev = first_number(fast.get("previous_close"), info.get("previousClose"), info.get("regularMarketPreviousClose"))
    if not price:
        hist = stock.history(period="2d", interval="1m")
        if not hist.empty:
            price = float(hist["Close"].dropna().iloc[-1])
    change = price - prev if price and prev else 0
    pct = (change / prev) * 100 if prev else 0
    plan = five_month_price_plan(stock, price)
    return {
        "price": price,
        "change": change,
        "changePct": pct,
        "updatedAt": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        **plan,
    }


def five_month_price_plan(stock: yf.Ticker, current_price: float) -> dict[str, Any]:
    try:
        hist = stock.history(period="3mo", interval="1d", auto_adjust=False)
    except Exception:
        hist = pd.DataFrame()

    if hist.empty or "Low" not in hist or "High" not in hist:
        return {
            "low5m": 0,
            "high5m": 0,
            "avg5m": 0,
            "suggestedBuyMin": 0,
            "suggestedExitMax": 0,
            "planNote": "אין מספיק נתוני 3 חודשים.",
        }

    lows = hist["Low"].dropna()
    highs = hist["High"].dropna()
    closes = hist["Close"].dropna()
    if lows.empty or highs.empty:
        return {
            "low5m": 0,
            "high5m": 0,
            "avg5m": 0,
            "suggestedBuyMin": 0,
            "suggestedExitMax": 0,
            "planNote": "אין מספיק נתוני שפל/שיא.",
        }

    low_5m = float(lows.min())
    high_5m = float(highs.max())
    avg_5m = float(closes.mean()) if not closes.empty else 0
    last_close = float(closes.iloc[-1]) if not closes.empty else current_price

    # Conservative working levels: buy near the lower quarter, exit before the top.
    price_range = max(0, high_5m - low_5m)
    suggested_buy = low_5m + price_range * 0.18 if price_range else low_5m
    suggested_exit = high_5m - price_range * 0.12 if price_range else high_5m

    if current_price and suggested_buy > current_price:
        suggested_buy = max(low_5m, current_price * 0.98)
    if current_price and suggested_exit < current_price:
        suggested_exit = max(current_price * 1.08, high_5m)

    return {
        "low5m": round(low_5m, 2),
        "high5m": round(high_5m, 2),
        "avg5m": round(avg_5m, 2),
        "suggestedBuyMin": round(suggested_buy, 2),
        "suggestedExitMax": round(suggested_exit, 2),
        "planNote": f"שפל 3 חודשים ${low_5m:.2f}, ממוצע 3 חודשים ${avg_5m:.2f}, שיא 3 חודשים ${high_5m:.2f}.",
        "lastClose5m": round(last_close, 2),
    }


def five_month_history_range(hist: pd.DataFrame) -> tuple[float, float, float]:
    if hist.empty or "Low" not in hist or "High" not in hist or "Close" not in hist:
        return 0.0, 0.0, 0.0

    try:
        latest_date = hist.index.max()
        recent = hist.loc[hist.index >= latest_date - pd.DateOffset(months=3)]
    except Exception:
        recent = hist.tail(66)

    lows = recent["Low"].dropna()
    highs = recent["High"].dropna()
    closes = recent["Close"].dropna()
    if lows.empty or highs.empty or closes.empty:
        return 0.0, 0.0, 0.0
    return round(float(lows.min()), 2), round(float(highs.max()), 2), round(float(closes.mean()), 2)


def item_alerts(row: dict[str, Any], quote: dict[str, Any]) -> list[str]:
    alerts = []
    buy = float(row.get("BuyPrice") or 0)
    invested = float(row.get("InvestedAmount") or 0)
    price = float(quote.get("price") or 0)
    if row.get("Owned") and buy > 0 and price > 0:
        profit = ((price - buy) / buy) * 100
        if profit >= 50:
            profit_amount = ((price - buy) / buy) * invested if invested > 0 else price - buy
            alerts.append(f"{row['Ticker']} ברווח {profit:.2f}% ממחיר הקנייה, בערך ${profit_amount:.2f}. שקול מימוש רווח.")
    return alerts


def market_risk() -> dict[str, Any]:
    hist = yf.Ticker("SPY").history(period="6mo", interval="1d")
    if hist.empty:
        return {"triggered": False, "drop": 0}
    close = hist["Close"].dropna()
    current = float(close.iloc[-1])
    high = float(close.max())
    drop = ((high - current) / high) * 100 if high else 0
    return {"triggered": drop >= 10, "drop": drop}


def live_symbol_search(query: str) -> list[dict[str, Any]]:
    try:
        search = yf.Search(query, max_results=12)
        quotes = search.quotes or []
    except Exception:
        quotes = []

    results = []
    allowed_types = {"EQUITY", "ETF"}
    allowed_exchanges = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "NASDAQ", "NYSE", "AMEX"}
    for quote in quotes:
        symbol = str(quote.get("symbol") or "").upper().strip()
        quote_type = str(quote.get("quoteType") or "").upper()
        exchange = str(quote.get("exchange") or quote.get("exchDisp") or "").upper()
        if not symbol or quote_type not in allowed_types:
            continue
        if exchange and not any(code in exchange for code in allowed_exchanges):
            continue

        results.append(
            {
                "ticker": symbol,
                "name": quote.get("shortname") or quote.get("longname") or symbol,
                "category": "נמצא בנתוני שוק חיים - בדוק זמינות ב-BLINK",
                "source": "Yahoo Finance live search",
                "quoteType": quote_type,
                "exchange": quote.get("exchDisp") or exchange,
                "isLeveraged": is_leveraged_product(
                    symbol,
                    quote.get("shortname") or quote.get("longname") or symbol,
                    quote_type,
                ),
            }
        )
    return results


def live_leveraged_scan_candidates() -> list[dict[str, Any]]:
    rows = list(LEVERAGED_SCAN_SEEDS)
    seen = {row["ticker"] for row in rows}
    for query in LEVERAGED_SCAN_QUERIES:
        for row in live_symbol_search(query):
            ticker = row["ticker"]
            if ticker in seen:
                continue
            if not is_leveraged_product(ticker, row.get("name", ""), f"{row.get('category', '')} {row.get('quoteType', '')}"):
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "name": row.get("name", ticker),
                    "category": "2X Long / leveraged ETF from live Yahoo search",
                }
            )
            seen.add(ticker)
            if len(rows) >= 30:
                return rows
    return rows


def stock_search_terms(raw_query: str) -> list[str]:
    query = raw_query.strip()
    if not query:
        return []

    terms = []
    for match in re.findall(r"\(([A-Za-z][A-Za-z0-9.\-]{0,9})\)", query):
        terms.append(match.upper())

    if looks_like_symbol(query):
        terms.append(query.upper())

    ignored = {"ETF", "ETN", "INC", "LTD", "PLC", "CORP", "LONG", "SHORT", "DAILY", "STOCK"}
    for token in re.findall(r"\b[A-Za-z][A-Za-z0-9.\-]{0,9}\b", query):
        upper = token.upper()
        if looks_like_symbol(upper) and upper not in ignored:
            terms.append(upper)

    terms.append(query)
    unique_terms = []
    seen = set()
    for term in terms:
        key = term.lower()
        if key not in seen:
            unique_terms.append(term)
            seen.add(key)
    return unique_terms[:8]


def preferred_search_symbols(raw_query: str) -> set[str]:
    symbols = {match.upper() for match in re.findall(r"\(([A-Za-z][A-Za-z0-9.\-]{0,9})\)", raw_query)}
    if looks_like_symbol(raw_query):
        symbols.add(raw_query.upper())
    return symbols


def is_leveraged_product(ticker: str, name: str, category: str = "") -> bool:
    text = f"{ticker} {name} {category}".lower()
    has_leverage_term = bool(re.search(r"\b[23]x\b|\b[23]x\s+(long|short)\b|leveraged|ultra|tradr", text))
    is_etf_like = "etf" in text or "etn" in text or "fund" in text or "tradr" in text
    return has_leverage_term and is_etf_like


def looks_like_symbol(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", value.strip()))


def compute_rsi(close: pd.Series, period: int = 14) -> float:
    if close.empty or len(close) < period + 2:
        return 50.0
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    value = float(rsi.iloc[-1])
    return value if np.isfinite(value) else 50.0


def analyze_news(news_items: list[dict[str, Any]]) -> dict[str, Any]:
    titles = []
    for item in news_items[:8]:
        title = str(item.get("title") or item.get("content", {}).get("title") or "").strip()
        if title:
            titles.append(title)

    text = " ".join(titles).lower()
    positive_hits = [(term, weight) for term, weight in POSITIVE_NEWS_TERMS.items() if term in text]
    negative_hits = [(term, weight) for term, weight in NEGATIVE_NEWS_TERMS.items() if term in text]
    positive_score = sum(weight for _, weight in positive_hits)
    negative_score = sum(weight for _, weight in negative_hits)
    score = max(-60, min(60, positive_score - negative_score))

    if positive_hits and not negative_hits:
        summary = f"נמצאה אפשרות לחדשות חיוביות: {', '.join(term for term, _ in positive_hits[:3])}."
    elif positive_hits and negative_hits:
        summary = f"יש חדשות מעורבות: חיובי ({positive_hits[0][0]}) מול סיכון ({negative_hits[0][0]})."
    elif negative_hits:
        summary = f"נמצאו סימני חדשות שליליות: {', '.join(term for term, _ in negative_hits[:3])}."
    else:
        summary = "לא נמצאה כרגע חדשה חיובית חזקה שמסבירה עלייה קרובה."

    return {
        "positive": positive_score >= 16,
        "negative": negative_score >= 18,
        "score": score,
        "summary": summary,
        "latest": titles[0] if titles else "אין כותרת חדשות זמינה.",
    }


def crash_risk(close: pd.Series, price: float, high_52: float, change_pct: float, rsi: float) -> dict[str, Any]:
    if close.empty or len(close) < 30 or not price:
        return {"avoid": False, "score": 0, "summary": "אין מספיק היסטוריה כדי לאבחן התרסקות."}

    latest = float(close.iloc[-1])
    close_5d = float(close.iloc[-6]) if len(close) >= 6 else latest
    close_20d = float(close.iloc[-21]) if len(close) >= 21 else latest
    close_60d = float(close.iloc[-61]) if len(close) >= 61 else latest
    ma50 = float(close.tail(50).mean()) if len(close) >= 50 else latest
    ma200 = float(close.tail(200).mean()) if len(close) >= 200 else ma50

    drop_5d = ((close_5d - latest) / close_5d) * 100 if close_5d else 0
    drop_20d = ((close_20d - latest) / close_20d) * 100 if close_20d else 0
    drop_60d = ((close_60d - latest) / close_60d) * 100 if close_60d else 0
    drop_from_high = ((high_52 - price) / high_52) * 100 if high_52 else 0

    risk = 0
    reasons = []
    if drop_5d >= 12:
        risk += 25
        reasons.append(f"ירידה של {drop_5d:.1f}% ב-5 ימים")
    if drop_20d >= 25:
        risk += 30
        reasons.append(f"ירידה של {drop_20d:.1f}% בחודש")
    if drop_60d >= 45:
        risk += 25
        reasons.append(f"ירידה של {drop_60d:.1f}% ב-3 חודשים")
    if drop_from_high >= 70:
        risk += 20
        reasons.append(f"{drop_from_high:.1f}% מתחת לשיא")
    if latest < ma50 < ma200:
        risk += 20
        reasons.append("המניה מתחת לממוצעי 50 ו-200 יום")
    if change_pct <= -8:
        risk += 15
        reasons.append("ירידה יומית חדה")
    if rsi < 18 and drop_20d >= 20:
        risk += 15
        reasons.append("RSI נמוך מאוד יחד עם נפילה מהירה")

    risk = int(max(0, min(100, risk)))
    avoid = risk >= 65
    summary = " | ".join(reasons[:3]) if reasons else "לא זוהתה התרסקות טכנית חריגה."
    return {"avoid": avoid, "score": risk, "summary": summary}


def is_five_month_opportunity(near_low_5m: float, below_high_5m: float) -> bool:
    return near_low_5m <= 15 or below_high_5m >= 15


def five_month_opportunity_score(near_low_5m: float, below_high_5m: float) -> int:
    near_low_score = max(0, min(100, 100 - max(0, near_low_5m) * 4))
    below_high_score = max(0, min(100, below_high_5m * 4))
    return int(max(near_low_score, below_high_score))


def score_stock(
    rsi: float,
    distance: float,
    market_cap: float,
    news_signal: dict[str, Any],
    technical_risk: dict[str, Any],
    price_in_range: bool,
    opportunity_score: int,
) -> int:
    rsi_score = max(0, min(100, 100 - max(0, rsi - 35) * 2))
    dip_score = max(0, min(100, distance * 3))
    cap_score = max(0, min(100, market_cap / 1_000_000_000 * 10))
    news_score = float(news_signal.get("score") or 0)
    risk_score = float(technical_risk.get("score") or 0)
    score = (
        rsi_score * 0.2
        + dip_score * 0.25
        + opportunity_score * 0.25
        + cap_score * 0.1
        + max(-35, min(35, news_score))
        - risk_score * 0.45
        + (10 if price_in_range else -35)
    )
    return int(max(0, min(100, round(score))))


def is_buy_setup(
    rsi: float,
    distance: float,
    news_signal: dict[str, Any],
    technical_risk: dict[str, Any],
    price_in_range: bool,
    score: int,
    five_month_opportunity: bool,
) -> bool:
    if not price_in_range or technical_risk.get("avoid"):
        return False
    if not five_month_opportunity:
        return False
    if rsi > 48:
        return False

    rebound_signal = news_signal.get("positive") and not news_signal.get("negative")
    deep_value_pullback = distance >= 25 and rsi <= 42 and int(technical_risk.get("score") or 0) < 50
    solid_buy_score = score >= 72 and distance >= 15 and rsi <= 45
    return bool(rebound_signal or deep_value_pullback or solid_buy_score)


def is_buy_candidate(row: dict[str, Any]) -> bool:
    return row.get("verdict") == "כדאי לקנות"


def reason_text(
    exchange_ok: bool,
    cap_ok: bool,
    price_in_range: bool,
    news_signal: dict[str, Any],
    technical_risk: dict[str, Any],
    rsi: float,
    distance: float,
    five_month_opportunity: bool,
    near_low_5m: float,
    below_high_5m: float,
) -> str:
    if not exchange_ok:
        return "לא נסחרת בבורסה מתאימה."
    if not cap_ok:
        return "שווי שוק נמוך מהרף שבחרת."
    if not price_in_range:
        return "מחיר המניה מחוץ לטווח המחיר שבחרת."
    if technical_risk.get("avoid"):
        return f"להתרחק כרגע: זוהה סיכון התרסקות ({technical_risk.get('summary')})."
    if news_signal.get("negative"):
        return f"לא כדאי עכשיו: החדשות כוללות סיכון שלילי ({news_signal.get('summary')})."
    if not five_month_opportunity:
        return f"לא כדאי עכשיו: המניה לא קרובה מספיק לשפל 3 חודשים ({near_low_5m:.1f}% מעל השפל) ולא לפחות 15% מתחת לשיא 3 חודשים ({below_high_5m:.1f}%)."
    if not news_signal.get("positive"):
        return "לא נמצא קטליזטור חיובי ממשי לפי החדשות האחרונות."
    if distance < 12 and not five_month_opportunity:
        return "המחיר לא נמוך מספיק ביחס לשיא/טווח רגיל."
    if rsi > 48:
        return "RSI גבוה יחסית, לא מספיק buy-low."
    if news_signal.get("positive"):
        return f"כדאי לקנות: המחיר נמוך ביחס לשיא ויש סימן שיכול לתמוך בעלייה קרובה. {news_signal.get('summary')}"
    return "כדאי לקנות בזהירות: המחיר נמוך משמעותית ביחס לשיא, בלי סיכון התרסקות גבוה, ועם פוטנציאל חזרה למעלה."


def score_explanation(
    rsi: float,
    distance: float,
    news_signal: dict[str, Any],
    technical_risk: dict[str, Any],
    price_in_range: bool,
    near_low_5m: float,
    below_high_5m: float,
    opportunity_score: int,
) -> str:
    parts = []
    if news_signal.get("positive") and not news_signal.get("negative"):
        parts.append("חדשות חיוביות מחזקות את הסיכוי לעלייה")
    elif news_signal.get("negative"):
        parts.append("חדשות שליליות הורידו את הציון")
    else:
        parts.append("אין כרגע קטליזטור חדשות חזק")

    if 25 <= rsi <= 45:
        parts.append(f"RSI {rsi:.1f} מתאים ל-buy low")
    elif rsi > 55:
        parts.append(f"RSI {rsi:.1f} גבוה יחסית")
    else:
        parts.append(f"RSI {rsi:.1f}")

    if distance >= 10:
        parts.append(f"{distance:.1f}% מתחת לשיא 52 שבועות")
    else:
        parts.append("לא מספיק רחוקה מהשיא")

    if near_low_5m <= 15:
        parts.append(f"קרובה לשפל 3 חודשים: {near_low_5m:.1f}% מעל השפל")
    elif below_high_5m >= 15:
        parts.append(f"{below_high_5m:.1f}% מתחת לשיא 3 חודשים")
    else:
        parts.append("לא קרובה מספיק לתחתית 3 חודשים")
    parts.append(f"ציון הזדמנות 3 חודשים {opportunity_score}/100")

    risk_score = int(technical_risk.get("score") or 0)
    if risk_score >= 65:
        parts.append("סיכון התרסקות גבוה")
    elif risk_score >= 35:
        parts.append("סיכון בינוני")
    else:
        parts.append("סיכון התרסקות נמוך")

    if not price_in_range:
        parts.append("מחוץ לטווח מחיר המניה שבחרת")

    return " | ".join(parts)


def verdict_order(verdict: str) -> int:
    return {"כדאי לקנות": 0, "לא כדאי עכשיו": 2}.get(verdict, 3)


def safe_info(stock: yf.Ticker) -> dict[str, Any]:
    try:
        return stock.get_info() or {}
    except Exception:
        return {}


def safe_fast_info(stock: yf.Ticker) -> dict[str, Any]:
    try:
        return dict(stock.fast_info or {})
    except Exception:
        return {}


def first_number(*values: Any) -> float:
    for value in values:
        try:
            number = float(value)
            if np.isfinite(number) and number > 0:
                return number
        except (TypeError, ValueError):
            continue
    return 0.0
