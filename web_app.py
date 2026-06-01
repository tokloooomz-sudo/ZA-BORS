from __future__ import annotations

import json
import os
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
BLINK_UNIVERSE_PATH = DATA_DIR / "blink_universe.csv"
SESSION_MAX_AGE = 60 * 60 * 12

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


@app.get("/api/universe")
def universe(_: str = Depends(require_login)) -> dict[str, Any]:
    df = pd.read_csv(BLINK_UNIVERSE_PATH)
    return {"tickers": df.head(100).to_dict(orient="records")}


@app.get("/api/watchlist")
def get_watchlist(_: str = Depends(require_login)) -> dict[str, Any]:
    rows = load_watchlist()
    enriched = []
    for row in rows:
        try:
            quote = fetch_quote(row["Ticker"])
            alerts = item_alerts(row, quote)
        except Exception as exc:
            quote = {"price": 0, "change": 0, "changePct": 0, "updatedAt": "N/A", "error": str(exc)}
            alerts = [f"{row['Ticker']}: לא הצלחתי להביא מחיר כרגע, אבל המניה נשארת ברשימת המעקב."]
        enriched.append({**row, "quote": quote, "alerts": alerts})
    return {"items": enriched, "market": market_risk()}


@app.post("/api/watchlist")
def add_watchlist(item: WatchItem, _: str = Depends(require_login)) -> dict[str, Any]:
    rows = load_watchlist()
    ticker = item.ticker.upper().strip()
    if not ticker:
        return {"ok": False, "message": "Missing ticker"}
    if any(row["Ticker"] == ticker for row in rows):
        return {"ok": False, "message": f"{ticker} already exists"}
    rows.append(
        {
            "Ticker": ticker,
            "Notes": item.notes,
            "Added": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "BuyPrice": float(item.buy_price or 0),
            "Owned": bool(item.owned),
        }
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
            row["Owned"] = bool(item.owned)
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

    universe_df = pd.read_csv(BLINK_UNIVERSE_PATH).head(min(max(req.tickers, 1), 100))
    rows = []
    for ticker in universe_df["ticker"].tolist():
        try:
            row = scan_one(str(ticker), req)
            if row["priceInRange"]:
                rows.append(row)
        except Exception as exc:
            continue
    rows.sort(key=lambda row: (verdict_order(row["verdict"]), -row["score"]))
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
    distance = ((high_52 - price) / high_52) * 100 if high_52 else 0
    rsi = compute_rsi(close)
    market_cap = first_number(info.get("marketCap"))
    exchange = str(info.get("exchange") or info.get("fullExchangeName") or "")
    exchange_ok = any(code in exchange.upper() for code in ["NMS", "NYQ", "NGM", "NCM", "NASDAQ", "NYSE"])
    cap_ok = req.min_market_cap <= 0 or market_cap >= req.min_market_cap
    price_in_range = price > 0 and req.min_investment <= price <= req.max_investment
    news_signal = analyze_news(stock.news if hasattr(stock, "news") else [])
    technical_risk = crash_risk(close, price, high_52, change_pct, rsi)
    catalyst = news_signal["positive"] and not news_signal["negative"]
    score = score_stock(rsi, distance, market_cap, news_signal, technical_risk, price_in_range)
    verdict = "כדאי מאוד" if score >= 80 else "כדאי לעקוב" if score >= 65 else "לא כדאי עכשיו"
    if not exchange_ok or not cap_ok or not price_in_range or technical_risk["avoid"]:
        verdict = "לא כדאי עכשיו"
    reason = reason_text(exchange_ok, cap_ok, price_in_range, news_signal, technical_risk, rsi, distance)
    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "price": price,
        "change": change,
        "changePct": change_pct,
        "exchange": exchange or "N/A",
        "marketCap": market_cap,
        "rsi": rsi,
        "distance": distance,
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
        "scoreExplanation": score_explanation(rsi, distance, news_signal, technical_risk, price_in_range),
    }


def load_watchlist() -> list[dict[str, Any]]:
    if not WATCHLIST_PATH.exists():
        return []
    try:
        data = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    for row in data if isinstance(data, list) else []:
        if isinstance(row, dict) and row.get("Ticker"):
            rows.append(
                {
                    "Ticker": str(row.get("Ticker", "")).upper().strip(),
                    "Notes": str(row.get("Notes", "")),
                    "Added": str(row.get("Added", "")),
                    "BuyPrice": float(row.get("BuyPrice") or 0),
                    "Owned": bool(row.get("Owned", False)),
                }
            )
    return rows


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
    return {"price": price, "change": change, "changePct": pct, "updatedAt": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")}


def item_alerts(row: dict[str, Any], quote: dict[str, Any]) -> list[str]:
    alerts = []
    buy = float(row.get("BuyPrice") or 0)
    price = float(quote.get("price") or 0)
    if row.get("Owned") and buy > 0 and price > 0:
        profit = ((price - buy) / buy) * 100
        if profit >= 50:
            alerts.append(f"{row['Ticker']} ברווח {profit:.2f}% ממחיר הקנייה. שקול מימוש רווח.")
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


def score_stock(rsi: float, distance: float, market_cap: float, news_signal: dict[str, Any], technical_risk: dict[str, Any], price_in_range: bool) -> int:
    rsi_score = max(0, min(100, 100 - max(0, rsi - 35) * 2))
    dip_score = max(0, min(100, distance * 3))
    cap_score = max(0, min(100, market_cap / 1_000_000_000 * 10))
    news_score = float(news_signal.get("score") or 0)
    risk_score = float(technical_risk.get("score") or 0)
    score = (
        rsi_score * 0.2
        + dip_score * 0.25
        + cap_score * 0.1
        + max(-35, min(35, news_score))
        - risk_score * 0.45
        + (10 if price_in_range else -35)
    )
    return int(max(0, min(100, round(score))))


def reason_text(exchange_ok: bool, cap_ok: bool, price_in_range: bool, news_signal: dict[str, Any], technical_risk: dict[str, Any], rsi: float, distance: float) -> str:
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
    if not news_signal.get("positive"):
        return "לא נמצא קטליזטור חיובי ממשי לפי החדשות האחרונות."
    if rsi > 45:
        return "RSI גבוה יחסית, לא מספיק buy-low."
    if distance < 10:
        return "המחיר לא רחוק מספיק משיא 52 שבועות."
    return f"הזדמנות אפשרית: ירידה במחיר יחד עם קטליזטור חדשות חיובי. {news_signal.get('summary')}"


def score_explanation(rsi: float, distance: float, news_signal: dict[str, Any], technical_risk: dict[str, Any], price_in_range: bool) -> str:
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
    return {"כדאי מאוד": 0, "כדאי לעקוב": 1, "לא כדאי עכשיו": 2}.get(verdict, 3)


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
