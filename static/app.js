const statusEl = document.querySelector("#status");
const signalsEl = document.querySelector("#signals");
const watchlistEl = document.querySelector("#watchlist");
const sellAlertsEl = document.querySelector("#sellAlerts");
const loadingBar = document.querySelector("#loadingBar");
const searchForm = document.querySelector("#stockSearchForm");
const searchResultsEl = document.querySelector("#stockSearchResults");
const watchlistStatusEl = document.querySelector("#watchlistStatus");
let authToken = sessionStorage.getItem("zaBorsToken");
const WATCHLIST_BACKUP_KEY = "zaBorsWatchlistBackup";
let watchlistRequestInFlight = false;

if (!authToken) {
  window.location.href = "/";
  throw new Error("Login required");
}

sessionStorage.setItem("zaBorsToken", authToken);

document.querySelector("#scanButton").addEventListener("click", scan);
document.querySelector("#refreshWatchlist").addEventListener("click", () => loadWatchlist(true));
document.querySelector("#logoutButton").addEventListener("click", logout);
searchForm.addEventListener("submit", searchStocks);
document.querySelector("#watchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await withLoading(async () => {
    await apiFetch("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: document.querySelector("#watchTicker").value,
        buy_price: Number(document.querySelector("#watchBuyPrice").value || 0),
        invested_amount: Number(document.querySelector("#watchInvestedAmount").value || 0),
        target_buy_min: Number(document.querySelector("#watchTargetBuyMin").value || 0),
        target_exit_max: Number(document.querySelector("#watchTargetExitMax").value || 0),
        owned: document.querySelector("#watchOwned").checked,
        notes: document.querySelector("#watchNotes").value
      })
    });
    event.target.reset();
    await loadWatchlist(false, true);
  });
});

async function scan() {
  await withLoading(async () => {
    statusEl.textContent = "סורק...";
    const payload = {
      tickers: Number(document.querySelector("#tickerCount").value || 100),
      min_market_cap: Number(document.querySelector("#marketCap").value),
      min_investment: Number(document.querySelector("#minInvestment").value || 5),
      max_investment: Number(document.querySelector("#maxInvestment").value || 100)
    };
    const res = await apiFetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    renderSignals(data.rows);
    statusEl.textContent = `נמצאו ${data.rows.length} מניות שכדאי לקנות היום, כולל ממונפות אם עברו את בדיקת הקנייה, מתוך ${data.scanned || data.rows.length} שנסרקו`;
  });
}

async function searchStocks(event) {
  event.preventDefault();
  await withLoading(async () => {
    const query = document.querySelector("#stockSearchInput").value.trim();
    if (!query) {
      searchResultsEl.innerHTML = "";
      return;
    }

    const params = new URLSearchParams({ q: query });
    const res = await apiFetch(`/api/search?${params.toString()}`);
    const data = await res.json();
    renderSearchResults(data.results || [], data);
  });
}

function renderSearchResults(results, meta = {}) {
  if (!results.length) {
    const checked = meta.checked || 0;
    searchResultsEl.innerHTML = `
      <p class="search-empty">
        לא נמצאה מניה לפי החיפוש הזה. נבדקו ${checked} תוצאות.
      </p>
    `;
    return;
  }

  searchResultsEl.innerHTML = `
    <div class="search-results-list">
      ${results.map(item => `
        <div class="search-result ${item.isLeveraged ? "leveraged-result" : ""}">
          <div>
            <strong>${item.ticker}</strong>
            <span>${item.name || ""}</span>
            <small>${item.category || ""}${item.quoteType ? ` | ${item.quoteType}` : ""}${item.exchange ? ` | ${item.exchange}` : ""}</small>
            <small>${item.isLeveraged ? "מוצר ממונף: רווח והפסד יכולים להיות מוכפלים. " : ""}הוסף לרשימת המעקב כדי להפעיל את בדיקות המחיר, הסיכון והתוכנית.</small>
          </div>
          <button type="button" onclick="addTicker('${item.ticker}', 0)" ${isWatched(item.ticker) ? "disabled" : ""}>+</button>
        </div>
      `).join("")}
    </div>
  `;
}

function renderSignals(rows) {
  if (!rows.length) {
    signalsEl.innerHTML = `
      <div class="empty-state">
        <h3>לא נמצאו מניות שכדאי לקנות היום</h3>
        <p>כל המניות שנסרקו, כולל ממונפות 2X Long, לא היו מספיק נמוכות ביחס לעצמן, לא הראו סיכוי ברור לעלייה קרובה, או היו בסיכון גבוה.</p>
      </div>
    `;
    return;
  }

  signalsEl.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>+</th><th>סימול</th><th>מחיר</th><th>שפל 3 חודשים</th><th>ממוצע 3 חודשים</th><th>שיא 3 חודשים</th><th>מעל שפל 3</th><th>מתחת לשיא 3</th><th>החלטת יועץ</th><th>ציון</th>
          <th>RSI</th><th>מרחק משיא</th><th>קטליזטור</th><th>סיכון התרסקות</th><th>חדשה אחרונה</th><th>הסבר ציון</th><th>סיבה</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(row => `
          <tr data-ticker="${row.ticker}" class="${row.isLeveraged ? "leveraged-row" : ""} ${isWatched(row.ticker) ? "watched" : ""}">
            <td><button onclick="addTicker('${row.ticker}', ${row.price})" ${isWatched(row.ticker) ? "disabled" : ""}>+</button></td>
            <td>${row.ticker}</td>
            <td class="${priceClass(row.change)}">${money(row.price)}</td>
            <td>${money(row.low5m)}</td>
            <td>${money(row.avg5m)}</td>
            <td>${money(row.high5m)}</td>
            <td>${num(row.nearLow5mPct)}%</td>
            <td>${num(row.belowHigh5mPct)}%</td>
            <td class="${verdictClass(row.verdict)}">${row.verdict}</td>
            <td>${row.score}</td>
            <td>${num(row.rsi)}</td>
            <td>${num(row.distance)}%</td>
            <td>${row.positiveCatalyst ? "כן" : "לא"}</td>
            <td class="${riskClass(row.riskScore)}">${row.riskScore || 0}/100<br><small>${row.riskText || ""}</small></td>
            <td>${row.latestNews || ""}</td>
            <td><small>${row.scoreExplanation || ""}</small></td>
            <td>${row.isLeveraged ? `<strong>${row.leverageWarning || "מוצר ממונף בסיכון גבוה."}</strong><br>` : ""}${row.reason}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

async function addTicker(ticker, price) {
  await withLoading(async () => {
    await apiFetch("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, buy_price: price, invested_amount: 0, target_buy_min: 0, target_exit_max: 0, owned: false, notes: "Added from search" })
    });
    await loadWatchlist(false, true);
  });

  const row = document.querySelector(`[data-ticker="${ticker}"]`);
  if (row) {
    row.classList.add("watched");
    const button = row.querySelector("button");
    if (button) button.disabled = true;
  }
}

let watchedTickers = new Set();

async function loadWatchlist(showLoading = false, restoreFromBackup = true) {
  if (watchlistRequestInFlight) return;
  watchlistRequestInFlight = true;
  if (showLoading) startLoading();
  try {
    const res = await apiFetch("/api/watchlist");
    let data = await res.json();
    const backup = readWatchlistBackup();

    if (restoreFromBackup && shouldRestoreWatchlistBackup(data.items || [], backup)) {
      await restoreWatchlistBackup(backup);
      const restoredRes = await apiFetch("/api/watchlist");
      data = await restoredRes.json();
      statusEl.textContent = "רשימת המעקב שוחזרה מהגיבוי המקומי";
    }

    data.items = mergeWatchlistDisplayItems(data.items || [], backup);
    watchedTickers = new Set(data.items.map(item => item.Ticker));
    saveWatchlistBackup(data.items, false);
    renderAlerts(data);
    if (!isEditingWatchlist()) {
      renderWatchlist(data.items);
    }
    updateWatchlistStatus(data.items);
  } finally {
    watchlistRequestInFlight = false;
    if (showLoading) finishLoading();
  }
}

function renderAlerts(data) {
  const alerts = [];
  if (data.market.triggered) {
    alerts.push(`התראת שוק: SPY ירד ${data.market.drop.toFixed(2)}% מהשיא האחרון. שקול הקטנת סיכון.`);
  }
  for (const item of data.items) alerts.push(...item.alerts);
  sellAlertsEl.innerHTML = `<h3>התראות מכירה</h3>${alerts.length ? alerts.map(a => `<div class="alert">${a}</div>`).join("") : "<p>אין כרגע התראות מכירה.</p>"}`;
}

function renderWatchlist(items) {
  if (!items.length) {
    watchlistEl.innerHTML = "<p>רשימת המעקב ריקה.</p>";
    return;
  }
  watchlistEl.innerHTML = `
    <table>
      <thead>
        <tr><th>-</th><th>V</th><th>סימול</th><th>מחיר</th><th>שינוי</th><th>עודכן</th><th>שפל 3 חודשים</th><th>ממוצע 3 חודשים</th><th>שיא 3 חודשים</th><th>מחיר קנייה</th><th>כמה קניתי ($)</th><th>קנייה כדאי מינימום</th><th>יציאה כדאי מקסימום</th><th>מצב יעד</th><th>שמירה</th><th>רווח/הפסד אם מוכר עכשיו</th><th>הערה</th></tr>
      </thead>
      <tbody>
      ${items.map(item => {
        const q = item.quote;
        const buyPrice = Number(item.BuyPrice || 0);
        const investedAmount = Number(item.InvestedAmount || 0);
        const isOwned = Boolean(item.Owned) && buyPrice > 0 && investedAmount > 0;
        const pl = livePL(item, q);
        const target = targetPlan(item, q);
        const targetBuyValue = Number(item.TargetBuyMin || 0) || Number(q.suggestedBuyMin || 0);
        const targetExitValue = Number(item.TargetExitMax || 0) || Number(q.suggestedExitMax || 0);
        const notes = escapeAttr(item.Notes || "");
        return `
          <tr>
            <td><button onclick="removeTicker('${item.Ticker}')">-</button></td>
            <td><input id="owned-${item.Ticker}" type="checkbox" ${isOwned ? "checked" : ""} onchange="saveWatchRow('${item.Ticker}', '${notes}')" /></td>
            <td>${item.Ticker}</td>
            <td class="${priceClass(q.change)}">${money(q.price)}</td>
            <td class="${priceClass(q.change)}">${q.change >= 0 ? "▲" : "▼"} ${money(q.change)} (${num(q.changePct)}%)</td>
            <td><small>${q.updatedAt || ""}</small></td>
            <td>${money(q.low5m)}</td>
            <td>${money(q.avg5m)}</td>
            <td>${money(q.high5m)}</td>
            <td><input id="buy-${item.Ticker}" class="buy-price-input" type="number" value="${isOwned ? buyPrice : 0}" min="0" step="0.01" inputmode="decimal" placeholder="0.00" /></td>
            <td><input id="invested-${item.Ticker}" class="buy-price-input" type="number" value="${isOwned ? investedAmount : 0}" min="0" step="0.01" inputmode="decimal" placeholder="1000" /></td>
            <td><input id="target-buy-${item.Ticker}" class="buy-price-input" title="${q.planNote || ""}" type="number" value="${targetBuyValue || 0}" min="0" step="0.01" inputmode="decimal" placeholder="0.00" /></td>
            <td><input id="target-exit-${item.Ticker}" class="buy-price-input" title="${q.planNote || ""}" type="number" value="${targetExitValue || 0}" min="0" step="0.01" inputmode="decimal" placeholder="0.00" /></td>
            <td class="${target.className}">${target.text}</td>
            <td><button type="button" class="save-row-button" onclick="saveWatchRow('${item.Ticker}', '${notes}')">שמור</button></td>
            <td class="${priceClass(pl.amount)}">${pl.text}</td>
            <td>${item.Notes || ""}</td>
          </tr>
        `;
      }).join("")}
      </tbody>
    </table>
  `;
}

function isEditingWatchlist() {
  return Boolean(document.activeElement && watchlistEl.contains(document.activeElement));
}

function updateWatchlistStatus(items) {
  const now = new Date().toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const count = items ? items.length : 0;
  watchlistStatusEl.textContent = `נשמרו ${count} מניות | רענון ידני בלבד | עודכן ${now}`;
}

async function saveWatchRow(ticker, notes) {
  let owned = document.querySelector(`#owned-${ticker}`).checked;
  let buyPrice = Number(document.querySelector(`#buy-${ticker}`).value || 0);
  let investedAmount = Number(document.querySelector(`#invested-${ticker}`).value || 0);
  const targetBuyMin = document.querySelector(`#target-buy-${ticker}`).value;
  const targetExitMax = document.querySelector(`#target-exit-${ticker}`).value;
  if (!owned || buyPrice <= 0 || investedAmount <= 0) {
    owned = false;
    buyPrice = 0;
    investedAmount = 0;
    document.querySelector(`#owned-${ticker}`).checked = false;
    document.querySelector(`#buy-${ticker}`).value = 0;
    document.querySelector(`#invested-${ticker}`).value = 0;
  }
  await updateTicker(ticker, owned, buyPrice, investedAmount, targetBuyMin, targetExitMax, notes);
  statusEl.textContent = `תוכנית הכניסה והיציאה של ${ticker} נשמרה`;
}

async function updateTicker(ticker, owned, buyPrice, investedAmount, targetBuyMin, targetExitMax, notes) {
  updateTickerInWatchlistBackup({
    Ticker: ticker,
    Notes: notes,
    BuyPrice: Number(buyPrice || 0),
    InvestedAmount: Number(investedAmount || 0),
    TargetBuyMin: Number(targetBuyMin || 0),
    TargetExitMax: Number(targetExitMax || 0),
    Owned: Boolean(owned)
  });
  await withLoading(async () => {
    await apiFetch(`/api/watchlist/${ticker}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker,
        owned,
        buy_price: Number(buyPrice || 0),
        invested_amount: Number(investedAmount || 0),
        target_buy_min: Number(targetBuyMin || 0),
        target_exit_max: Number(targetExitMax || 0),
        notes
      })
    });
    await loadWatchlist(false, false);
  });
}

async function removeTicker(ticker) {
  await withLoading(async () => {
    removeTickerFromWatchlistBackup(ticker);
    await apiFetch(`/api/watchlist/${ticker}`, { method: "DELETE" });
    await loadWatchlist(false, false);
  });
}

function readWatchlistBackup() {
  try {
    const rows = JSON.parse(localStorage.getItem(WATCHLIST_BACKUP_KEY) || "[]");
    return Array.isArray(rows) ? rows.filter(row => row && row.Ticker) : [];
  } catch {
    return [];
  }
}

function shouldRestoreWatchlistBackup(serverItems, backupItems) {
  const serverTickers = new Set((serverItems || []).map(item => String(item.Ticker || "").toUpperCase()).filter(Boolean));
  const missingBackupItems = (backupItems || []).filter(item => item.Ticker && !serverTickers.has(String(item.Ticker).toUpperCase()));
  return backupItems.length > serverItems.length && missingBackupItems.length > 0;
}

function normalizeWatchlistItems(items) {
  return (items || []).map(item => {
    const buyPrice = Number(item.BuyPrice || 0);
    const investedAmount = Number(item.InvestedAmount || 0);
    const owned = Boolean(item.Owned) && buyPrice > 0 && investedAmount > 0;
    return {
      Ticker: String(item.Ticker || "").toUpperCase(),
      Notes: item.Notes || "",
      BuyPrice: owned ? buyPrice : 0,
      InvestedAmount: owned ? investedAmount : 0,
      TargetBuyMin: Number(item.TargetBuyMin || 0),
      TargetExitMax: Number(item.TargetExitMax || 0),
      Owned: owned
    };
  }).filter(item => item.Ticker);
}

function mergeWatchlistDisplayItems(serverItems, backupItems) {
  const backupByTicker = new Map(normalizeWatchlistItems(backupItems).map(item => [item.Ticker, item]));
  return (serverItems || []).map(item => {
    const ticker = String(item.Ticker || "").toUpperCase();
    const backup = backupByTicker.get(ticker);
    return backup ? { ...item, ...backup, quote: item.quote, alerts: item.alerts } : item;
  });
}

function saveWatchlistBackup(items, merge = false) {
  const clean = normalizeWatchlistItems(items);
  const rows = merge ? mergeWatchlistItems(readWatchlistBackup(), clean) : clean;
  localStorage.setItem(WATCHLIST_BACKUP_KEY, JSON.stringify(rows));
}

function mergeWatchlistItems(existingItems, newItems) {
  const merged = new Map();
  for (const item of normalizeWatchlistItems(existingItems)) merged.set(item.Ticker, item);
  for (const item of normalizeWatchlistItems(newItems)) merged.set(item.Ticker, { ...(merged.get(item.Ticker) || {}), ...item });
  return Array.from(merged.values());
}

function removeTickerFromWatchlistBackup(ticker) {
  const target = String(ticker || "").toUpperCase();
  const rows = readWatchlistBackup().filter(item => item.Ticker !== target);
  saveWatchlistBackup(rows, false);
}

function updateTickerInWatchlistBackup(item) {
  const ticker = String(item.Ticker || "").toUpperCase();
  if (!ticker) return;
  const rows = mergeWatchlistItems(readWatchlistBackup(), [{ ...item, Ticker: ticker }]);
  saveWatchlistBackup(rows, false);
}

async function restoreWatchlistBackup(items) {
  for (const item of normalizeWatchlistItems(items)) {
    await apiFetch("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: item.Ticker,
        buy_price: Number(item.BuyPrice || 0),
        invested_amount: Number(item.InvestedAmount || 0),
        target_buy_min: Number(item.TargetBuyMin || 0),
        target_exit_max: Number(item.TargetExitMax || 0),
        owned: Boolean(item.Owned),
        notes: item.Notes || "Restored from local backup"
      })
    });
  }
}

function livePL(item, quote) {
  const buy = Number(item.BuyPrice || 0);
  const invested = Number(item.InvestedAmount || 0);
  const price = Number(quote.price || 0);
  if (!item.Owned || !buy || !price || !invested) return { amount: 0, text: "-" };
  const pct = ((price - buy) / buy) * 100;
  const amount = invested * (pct / 100);
  return { amount, text: `${amount >= 0 ? "▲" : "▼"} ${money(amount)} (${num(pct)}%)` };
}

function targetPlan(item, quote) {
  const price = Number(quote.price || 0);
  const buyTarget = Number(item.TargetBuyMin || 0) || Number(quote.suggestedBuyMin || 0);
  const exitTarget = Number(item.TargetExitMax || 0) || Number(quote.suggestedExitMax || 0);

  if (!price) return { text: "-", className: "price-flat" };
  if (exitTarget && price >= exitTarget) return { text: "▲ הגיע למחיר יציאה", className: "price-up" };
  if (buyTarget && price <= buyTarget) return { text: "▼ הגיע למחיר קנייה", className: "price-down" };
  if (buyTarget || exitTarget) return { text: "ממתין ליעד", className: "price-flat" };
  return { text: "-", className: "price-flat" };
}

async function withLoading(task) {
  startLoading();
  try {
    return await task();
  } finally {
    finishLoading();
  }
}

async function apiFetch(url, options) {
  const mergedOptions = {
    ...(options || {}),
    cache: "no-store",
    headers: {
      ...((options && options.headers) || {}),
      Authorization: `Bearer ${authToken}`
    }
  };
  const response = await fetch(url, mergedOptions);
  if (response.status === 401) {
    localStorage.removeItem("zaBorsToken");
    sessionStorage.removeItem("zaBorsToken");
    window.location.href = "/";
    throw new Error("Login required");
  }
  return response;
}

async function logout() {
  localStorage.removeItem("zaBorsToken");
  sessionStorage.removeItem("zaBorsToken");
  await fetch("/api/logout", { method: "POST" });
  window.location.href = "/";
}

function startLoading() {
  loadingBar.classList.remove("done");
  loadingBar.classList.add("active");
}

function finishLoading() {
  loadingBar.classList.remove("active");
  loadingBar.classList.add("done");
  setTimeout(() => loadingBar.classList.remove("done"), 300);
}

function verdictClass(v) {
  if (v === "כדאי לקנות") return "verdict-strong";
  return "verdict-avoid";
}
function priceClass(change) {
  if (change > 0) return "price-up";
  if (change < 0) return "price-down";
  return "price-flat";
}
function riskClass(score) {
  if (Number(score || 0) >= 65) return "price-down";
  if (Number(score || 0) >= 35) return "price-flat";
  return "price-up";
}
function money(value) { return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`; }
function num(value) { return Number(value || 0).toFixed(2); }
function isWatched(ticker) { return watchedTickers.has(ticker); }
function escapeAttr(value) { return String(value).replaceAll("'", "&#39;").replaceAll('"', "&quot;"); }

loadWatchlist();

