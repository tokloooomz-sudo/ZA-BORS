const statusEl = document.querySelector("#status");
const signalsEl = document.querySelector("#signals");
const watchlistEl = document.querySelector("#watchlist");
const sellAlertsEl = document.querySelector("#sellAlerts");

document.querySelector("#scanButton").addEventListener("click", scan);
document.querySelector("#refreshWatchlist").addEventListener("click", loadWatchlist);
document.querySelector("#watchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await fetch("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticker: document.querySelector("#watchTicker").value,
      buy_price: Number(document.querySelector("#watchBuyPrice").value || 0),
      owned: document.querySelector("#watchOwned").checked,
      notes: document.querySelector("#watchNotes").value
    })
  });
  event.target.reset();
  await loadWatchlist();
});

async function scan() {
  statusEl.textContent = "סורק...";
  const payload = {
    tickers: Number(document.querySelector("#tickerCount").value || 100),
    min_market_cap: Number(document.querySelector("#marketCap").value),
    min_investment: Number(document.querySelector("#minInvestment").value || 100),
    max_investment: Number(document.querySelector("#maxInvestment").value || 1000)
  };
  const res = await fetch("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  renderSignals(data.rows);
  statusEl.textContent = `נסרקו ${data.rows.length} מניות`;
}

function renderSignals(rows) {
  signalsEl.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>+</th><th>סימול</th><th>מחיר</th><th>החלטת יועץ</th><th>ציון</th>
          <th>RSI</th><th>מרחק משיא</th><th>קטליזטור</th><th>סיבה</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(row => `
          <tr class="${isWatched(row.ticker) ? "watched" : ""}">
            <td><button onclick="addTicker('${row.ticker}', ${row.price})" ${isWatched(row.ticker) ? "disabled" : ""}>+</button></td>
            <td>${row.ticker}</td>
            <td class="${priceClass(row.change)}">${money(row.price)}</td>
            <td class="${verdictClass(row.verdict)}">${row.verdict}</td>
            <td>${row.score}</td>
            <td>${num(row.rsi)}</td>
            <td>${num(row.distance)}%</td>
            <td>${row.positiveCatalyst ? "כן" : "לא"}</td>
            <td>${row.reason}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

async function addTicker(ticker, price) {
  await fetch("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, buy_price: price, owned: false, notes: "Added from scan" })
  });
  await loadWatchlist();
  await scan();
}

let watchedTickers = new Set();

async function loadWatchlist() {
  const res = await fetch("/api/watchlist");
  const data = await res.json();
  watchedTickers = new Set(data.items.map(item => item.Ticker));
  renderAlerts(data);
  renderWatchlist(data.items);
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
        <tr><th>-</th><th>V</th><th>סימול</th><th>מחיר</th><th>שינוי</th><th>מחיר קנייה</th><th>רווח/הפסד חי</th><th>הערה</th></tr>
      </thead>
      <tbody>
      ${items.map(item => {
        const q = item.quote;
        const pl = livePL(item, q);
        return `
          <tr>
            <td><button onclick="removeTicker('${item.Ticker}')">-</button></td>
            <td><input type="checkbox" ${item.Owned ? "checked" : ""} onchange="updateTicker('${item.Ticker}', this.checked, ${item.BuyPrice || 0}, '${escapeAttr(item.Notes || "")}')" /></td>
            <td>${item.Ticker}</td>
            <td class="${priceClass(q.change)}">${money(q.price)}</td>
            <td class="${priceClass(q.change)}">${q.change >= 0 ? "▲" : "▼"} ${money(q.change)} (${num(q.changePct)}%)</td>
            <td><input type="number" value="${item.BuyPrice || 0}" min="0" step="0.01" onchange="updateTicker('${item.Ticker}', ${item.Owned ? "true" : "false"}, this.value, '${escapeAttr(item.Notes || "")}')" /></td>
            <td class="${priceClass(pl.amount)}">${pl.text}</td>
            <td>${item.Notes || ""}</td>
          </tr>
        `;
      }).join("")}
      </tbody>
    </table>
  `;
}

async function updateTicker(ticker, owned, buyPrice, notes) {
  await fetch(`/api/watchlist/${ticker}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, owned, buy_price: Number(buyPrice || 0), notes })
  });
  await loadWatchlist();
}

async function removeTicker(ticker) {
  await fetch(`/api/watchlist/${ticker}`, { method: "DELETE" });
  await loadWatchlist();
}

function livePL(item, quote) {
  const buy = Number(item.BuyPrice || 0);
  const price = Number(quote.price || 0);
  if (!item.Owned || !buy || !price) return { amount: 0, text: "-" };
  const amount = price - buy;
  const pct = (amount / buy) * 100;
  return { amount, text: `${amount >= 0 ? "▲" : "▼"} ${money(amount)} (${num(pct)}%)` };
}

function verdictClass(v) {
  if (v === "כדאי מאוד") return "verdict-strong";
  if (v === "כדאי לעקוב") return "verdict-watch";
  return "verdict-avoid";
}
function priceClass(change) {
  if (change > 0) return "price-up";
  if (change < 0) return "price-down";
  return "price-flat";
}
function money(value) { return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`; }
function num(value) { return Number(value || 0).toFixed(2); }
function isWatched(ticker) { return watchedTickers.has(ticker); }
function escapeAttr(value) { return String(value).replaceAll("'", "&#39;").replaceAll('"', "&quot;"); }

loadWatchlist();
setInterval(loadWatchlist, 15000);
