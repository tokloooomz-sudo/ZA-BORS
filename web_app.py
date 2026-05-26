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
SESSION_COOKIE = "za_bors_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7

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
    min_investment: float = 100
    max_investment: float = 1000


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

    username = verify_session(request.cookies.get(SESSION_COOKIE))
    if username:
        return username

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Login required",
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    expected_username, expected_password = auth_settings()
    if expected_username and expected_password and not verify_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    template = templates.get_template("index.html")
    return template.render(app_name="ZA-BORS")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    expected_username, expected_password = auth_settings()
    if expected_username and expected_password and verify_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    template = templates.get_template("login.html")
    return template.render(app_name="ZA-BORS", error="")


@app.post("/api/login")
async def login(request: Request) -> JSONResponse:
    expected_username, expected_password = auth_settings()
    if not expected_username or not expected_password:
        response = JSONResponse({"ok": True})
        response.set_cookie(
            SESSION_COOKIE,
            sign_session("local"),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=SESSION_MAX_AGE,
        )
        return response

    payload = await request.json()
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    username_ok = secrets.compare_digest(username, expected_username)
    password_ok = secrets.compare_digest(password, expected_password)
    if not username_ok or not password_ok:
        return JSONResponse({"ok": False, "message": "שם משתמש או סיסמה לא נכונים"}, status_code=401)

    response = JSONResponse({"ok": True})
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(username),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )
    return response


@app.post("/api/logout")
def logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/api/universe")
def universe(_: str = Depends(require_login)) -> dict[str, Any]:
    df = pd.read_csv(BLINK_UNIVERSE_PATH)
    return {"tickers": df.head(100).to_dict(orient="records")}


@app.get("/api/watchlist")
def get_watchlist(_: str = Depends(require_login)) -> dict[str, Any]:
    rows = load_watchlist()
    enriched = []
    for row in rows:
        quote = fetch_quote(row["Ticker"])
        enriched.append({**row, "quote": quote, "alerts": item_alerts(row, quote)})
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
    universe_df = pd.read_csv(BLINK_UNIVERSE_PATH).head(min(max(req.tickers, 1), 100))
    rows = []
    for ticker in universe_df["ticker"].tolist():
        try:
            rows.append(scan_one(str(ticker), req))
        except Exception as exc:
            rows.append(
                {
                    "ticker": ticker,
                    "price": 0,
                    "verdict": "לא כדאי עכשיו",
                    "score": 0,
                    "reason": f"שגיאה בנתונים: {exc}",
                    "positiveCatalyst": False,
                }
            )
    rows.sort(key=lambda row: (verdict_order(row["verdict"]), -row["score"]))
    return JSONResponse({"rows": rows})


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
    affordable = price > 0 and int(req.max_investment // price) >= 1
    catalyst = keyword_catalyst(stock.news if hasattr(stock, "news") else [])
    score = score_stock(rsi, distance, market_cap, catalyst, affordable)
    verdict = "כדאי מאוד" if score >= 80 else "כדאי לעקוב" if score >= 65 else "לא כדאי עכשיו"
    if not exchange_ok or not cap_ok or not affordable:
        verdict = "לא כדאי עכשיו"
    reason = reason_text(exchange_ok, cap_ok, affordable, catalyst, rsi, distance)
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
        "reason": reason,
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


def keyword_catalyst(news_items: list[dict[str, Any]]) -> bool:
    text = " ".join(str(item.get("title", "")) for item in news_items[:6]).lower()
    return any(term in text for term in ["beat", "beats", "approval", "contract", "partnership", "launch", "guidance", "surge"])


def score_stock(rsi: float, distance: float, market_cap: float, catalyst: bool, affordable: bool) -> int:
    rsi_score = max(0, min(100, 100 - max(0, rsi - 35) * 2))
    dip_score = max(0, min(100, distance * 3))
    cap_score = max(0, min(100, market_cap / 1_000_000_000 * 10))
    score = rsi_score * 0.25 + dip_score * 0.3 + cap_score * 0.15 + (25 if catalyst else 0) + (10 if affordable else -25)
    return int(max(0, min(100, round(score))))


def reason_text(exchange_ok: bool, cap_ok: bool, affordable: bool, catalyst: bool, rsi: float, distance: float) -> str:
    if not exchange_ok:
        return "לא נסחרת בבורסה מתאימה."
    if not cap_ok:
        return "שווי שוק נמוך מהרף שבחרת."
    if not affordable:
        return "מחיר המניה לא מתאים לטווח ההשקעה שלך."
    if not catalyst:
        return "לא נמצא קטליזטור חיובי ממשי."
    if rsi > 45:
        return "RSI גבוה יחסית, לא מספיק buy-low."
    if distance < 10:
        return "המחיר לא רחוק מספיק משיא 52 שבועות."
    return "עבר את כל הסינונים."


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
