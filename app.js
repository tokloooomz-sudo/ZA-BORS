const storageKey = "za-bors-listings-v1";

const sampleListings = [
  {
    title: "משרד שקט ליד תחנת סבידור",
    address: "מנחם בגין, מתחם הבורסה",
    monthlyRent: 7800,
    sqm: 52,
    walkToTrain: 6,
    floor: 12,
    parking: 1,
    availableFrom: "2026-06-01",
    contractMonths: 12,
    conditionScore: 82,
    fitScore: 88,
    notes: "מחולק טוב, מתאים לצוות קטן, מעליות מהירות."
  },
  {
    title: "חלל פתוח עם נוף עירוני",
    address: "ז'בוטינסקי, רמת גן",
    monthlyRent: 11200,
    sqm: 85,
    walkToTrain: 9,
    floor: 18,
    parking: 2,
    availableFrom: "2026-07-15",
    contractMonths: 24,
    conditionScore: 91,
    fitScore: 79,
    notes: "מרשים ללקוחות, פחות אינטימי לפגישות."
  },
  {
    title: "קליניקה/משרד קטן במחיר נמוך",
    address: "תובל, מתחם הבורסה",
    monthlyRent: 5200,
    sqm: 31,
    walkToTrain: 4,
    floor: 5,
    parking: 0,
    availableFrom: "2026-05-30",
    contractMonths: 6,
    conditionScore: 70,
    fitScore: 76,
    notes: "חסכוני וגמיש, דורש קצת שיפוץ."
  }
];

let listings = loadListings();

const elements = {
  budget: document.querySelector("#budget"),
  targetSqm: document.querySelector("#targetSqm"),
  maxWalk: document.querySelector("#maxWalk"),
  moveIn: document.querySelector("#moveIn"),
  priceWeight: document.querySelector("#priceWeight"),
  locationWeight: document.querySelector("#locationWeight"),
  qualityWeight: document.querySelector("#qualityWeight"),
  flexWeight: document.querySelector("#flexWeight"),
  rows: document.querySelector("#listingRows"),
  recommendation: document.querySelector("#recommendation"),
  bestScore: document.querySelector("#bestScore"),
  averageRent: document.querySelector("#averageRent"),
  listingCount: document.querySelector("#listingCount"),
  form: document.querySelector("#listingForm"),
  importFile: document.querySelector("#importFile"),
  resetData: document.querySelector("#resetData")
};

Object.values(elements)
  .filter((element) => element && ["INPUT", "TEXTAREA"].includes(element.tagName))
  .forEach((input) => input.addEventListener("input", render));

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(elements.form);
  listings.push(normalizeListing(Object.fromEntries(data.entries())));
  persist();
  elements.form.reset();
  elements.form.availableFrom.valueAsDate = new Date();
  render();
});

elements.importFile.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;

  const text = await file.text();
  const imported = file.name.toLowerCase().endsWith(".json")
    ? JSON.parse(text)
    : parseCsv(text);

  listings = imported.map(normalizeListing).filter((listing) => listing.title);
  persist();
  event.target.value = "";
  render();
});

elements.resetData.addEventListener("click", () => {
  listings = sampleListings.map(normalizeListing);
  persist();
  render();
});

function loadListings() {
  const saved = localStorage.getItem(storageKey);
  if (!saved) return sampleListings.map(normalizeListing);

  try {
    return JSON.parse(saved).map(normalizeListing);
  } catch {
    return sampleListings.map(normalizeListing);
  }
}

function persist() {
  localStorage.setItem(storageKey, JSON.stringify(listings));
}

function normalizeListing(raw) {
  return {
    title: String(raw.title || "").trim(),
    address: String(raw.address || "").trim(),
    monthlyRent: number(raw.monthlyRent),
    sqm: number(raw.sqm),
    walkToTrain: number(raw.walkToTrain),
    floor: number(raw.floor),
    parking: number(raw.parking),
    availableFrom: String(raw.availableFrom || todayIso()).slice(0, 10),
    contractMonths: number(raw.contractMonths || 12),
    conditionScore: clamp(number(raw.conditionScore || 70), 0, 100),
    fitScore: clamp(number(raw.fitScore || 70), 0, 100),
    notes: String(raw.notes || "").trim()
  };
}

function scoreListing(listing, preferences) {
  const priceScore = clamp(100 - ((listing.monthlyRent - preferences.budget) / preferences.budget) * 100, 0, 100);
  const sizeScore = clamp(100 - Math.abs(listing.sqm - preferences.targetSqm) * 2, 0, 100);
  const walkScore = clamp(100 - Math.max(0, listing.walkToTrain - preferences.maxWalk) * 12, 0, 100);
  const availabilityScore = availability(listing.availableFrom, preferences.moveIn);
  const qualityScore = (listing.conditionScore * 0.55) + (listing.fitScore * 0.45);
  const flexScore = clamp(100 - Math.max(0, listing.contractMonths - 12) * 3 + listing.parking * 6, 0, 100);

  const locationScore = (walkScore * 0.75) + (sizeScore * 0.25);
  const weightsTotal = preferences.priceWeight + preferences.locationWeight + preferences.qualityWeight + preferences.flexWeight || 1;
  const weighted =
    (priceScore * preferences.priceWeight) +
    (locationScore * preferences.locationWeight) +
    (qualityScore * preferences.qualityWeight) +
    (((availabilityScore * 0.55) + (flexScore * 0.45)) * preferences.flexWeight);

  return Math.round(weighted / weightsTotal);
}

function availability(availableFrom, moveIn) {
  const available = new Date(availableFrom).getTime();
  const target = new Date(moveIn).getTime();
  const diffDays = Math.round((available - target) / 86400000);
  if (diffDays <= 0) return 100;
  return clamp(100 - diffDays * 2, 0, 100);
}

function getPreferences() {
  return {
    budget: number(elements.budget.value),
    targetSqm: number(elements.targetSqm.value),
    maxWalk: number(elements.maxWalk.value),
    moveIn: elements.moveIn.value || todayIso(),
    priceWeight: number(elements.priceWeight.value),
    locationWeight: number(elements.locationWeight.value),
    qualityWeight: number(elements.qualityWeight.value),
    flexWeight: number(elements.flexWeight.value)
  };
}

function render() {
  const preferences = getPreferences();
  const ranked = listings
    .map((listing) => ({ ...listing, score: scoreListing(listing, preferences) }))
    .sort((a, b) => b.score - a.score);

  const best = ranked[0];
  elements.listingCount.textContent = ranked.length;
  elements.bestScore.textContent = best ? best.score : 0;
  elements.averageRent.textContent = formatMoney(average(ranked.map((listing) => listing.monthlyRent)));

  elements.recommendation.innerHTML = best
    ? `<strong>${escapeHtml(best.title)}</strong><p>${decisionText(best, preferences)}</p>`
    : "<strong>אין נכסים במעקב</strong><p>הוסף נכס ידנית או ייבא קובץ מ-BLINK.</p>";

  elements.rows.innerHTML = ranked.map(rowTemplate).join("");
}

function decisionText(listing, preferences) {
  const reasons = [];
  if (listing.monthlyRent <= preferences.budget) reasons.push("בתוך התקציב");
  if (listing.walkToTrain <= preferences.maxWalk) reasons.push("קרוב לרכבת");
  if (listing.sqm >= preferences.targetSqm * 0.9) reasons.push("שטח מתאים");
  if (listing.fitScore >= 80) reasons.push("התאמה אישית גבוהה");
  if (reasons.length === 0) reasons.push("הכי מאוזן ביחס לשאר האפשרויות");
  return `ההמלצה כרגע היא לבדוק קודם את הנכס הזה: ${reasons.join(", ")}.`;
}

function rowTemplate(listing) {
  const scoreClass = listing.score >= 80 ? "high" : listing.score >= 60 ? "mid" : "low";
  return `
    <tr>
      <td><span class="score ${scoreClass}">${listing.score}</span></td>
      <td>
        <span class="property-title">${escapeHtml(listing.title)}</span>
        <span class="property-address">${escapeHtml(listing.address)}</span>
      </td>
      <td>${formatMoney(listing.monthlyRent)}</td>
      <td>${listing.sqm} מ"ר</td>
      <td>${listing.walkToTrain} דק'</td>
      <td>${formatDate(listing.availableFrom)}</td>
      <td class="muted">${escapeHtml(listing.notes)}</td>
    </tr>
  `;
}

function parseCsv(text) {
  const [headerLine, ...lines] = text.trim().split(/\r?\n/);
  const headers = splitCsvLine(headerLine);
  return lines.filter(Boolean).map((line) => {
    const values = splitCsvLine(line);
    return Object.fromEntries(headers.map((header, index) => [header, values[index] || ""]));
  });
}

function splitCsvLine(line) {
  const matches = line.match(/("([^"]|"")*"|[^,]+)/g) || [];
  return matches.map((value) => value.replace(/^"|"$/g, "").replaceAll('""', '"').trim());
}

function number(value) {
  return Number.parseFloat(value) || 0;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function average(values) {
  const valid = values.filter((value) => Number.isFinite(value));
  if (!valid.length) return 0;
  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

function formatMoney(value) {
  return new Intl.NumberFormat("he-IL", {
    style: "currency",
    currency: "ILS",
    maximumFractionDigits: 0
  }).format(value || 0);
}

function formatDate(value) {
  return new Intl.DateTimeFormat("he-IL").format(new Date(value));
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  })[char]);
}

elements.form.availableFrom.valueAsDate = new Date();
render();
