// Map page: draws listings on a Leaflet map, collects each roommate's priorities,
// and shows the fair pick that the backend's own scoring code computes.
// Nothing here scores a listing; the per-person rent is only for the marker colors and cards.

// Where the group heads most days (a campus, an office, a neighborhood). Anyone can type their own.
// The demo starts at UCLA because DEFAULT_DESTINATION in app/maps_lookup.py is Royce Hall, so the demo
// listings' saved walk and bike times apply. Any other place is sent as each roommate's place.
const DEFAULT_HOME = { name: "UCLA", latlng: [34.0699182, -118.4438495] };
let home = { ...DEFAULT_HOME };
const WALK_CIRCLE_MINUTES = 35;
const WALK_METERS_PER_MINUTE = 80; // ~3 mph, so 35 min is about 2.8 km (1.75 mi), as in the earlier map
// Must match CRITERIA in app/scoring.py.
const FACTORS = ["rent", "commute", "laundry", "parking", "bedrooms"];
const FACTOR_LABELS = { rent: "Rent", commute: "Commute", laundry: "Laundry", parking: "Parking", bedrooms: "Bedrooms" };
// Shown when hovering a rating button.
const RATING_WORDS = ["don't care", "a little", "somewhat", "matters", "a lot", "deal-breaker"];
// Must match TravelMode in app/models.py. The words are used in sentences like "31 min by bike".
const TRAVEL_MODES = { WALK: "walking", BICYCLE: "by bike", TRANSIT: "by transit", DRIVE: "driving" };

// Marker colors for rent per person, measured against the group's own budgets (so it works in any city).
// Colors match the --tier-* tokens in styles.css.
const TIER_COLORS = { fits: "#2e9e5b", some: "#e8a23b", none: "#d0573f" };
const UNKNOWN_COLOR = "#8a94a6";
const PICK_RING = "#1e3a5f", PICK_GLOW = "#ffc72c", MARKER_EDGE = "#ffffff", WALK_CIRCLE = "#2774ae";

// Readable labels for field values (old and current names).
const LABELS = {
  in_unit: "In-unit", in_building: "Shared in building", shared: "Shared", none: "None",
  included: "Included", extra_cost: "Extra cost", paid: "Paid", unknown: null,
};

// Shown one after another while a pasted listing is processed (one request does all of these).
const PARSE_STEPS = ["Reading the listing…", "Checking each fact against the text…",
                     "Finding it on the map…", "Looking up walk and bike times…", "Finding groceries nearby…"];

let listings = [];
let roommates = [
  { name: "Alex", budget: 1500, place: "", travel_mode: "WALK", weights: { rent: 5, commute: 2, laundry: 3, parking: 1, bedrooms: 2 } },
  { name: "Sam", budget: 1900, place: "", travel_mode: "WALK", weights: { rent: 2, commute: 5, laundry: 3, parking: 4, bedrooms: 3 } },
  { name: "Jordan", budget: 1700, place: "", travel_mode: "WALK", weights: { rent: 3, commute: 3, laundry: 5, parking: 2, bedrooms: 3 } },
];
let demoIds = new Set(); // The pre-loaded UCLA listings, so "Start fresh" can remove them.
let markers = {};
let homeLayers = [];
let pickHalo = null;
let lastDecision = null;

// ---------- Map ----------
const map = L.map("map", { scrollWheelZoom: true }).setView(home.latlng, 14);
// The listing card opened by a click, if any. Hover cards stay hidden until it's closed.
let openPopup = null;
map.on("popupopen", e => {
  openPopup = e.popup;
  map.eachLayer(layer => layer.closeTooltip && layer.closeTooltip());
});
map.on("popupclose", e => { if (openPopup === e.popup) openPopup = null; });
// Standard OpenStreetMap tiles. The CARTO tiles from the earlier map now need an API key.
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors", maxZoom: 19,
}).addTo(map);

// The group's destination: a badge and a dashed walk circle. Skipped when we don't know where it is.
function drawHome() {
  homeLayers.forEach(l => l.remove());
  homeLayers = [];
  if (!home.latlng) return;
  homeLayers.push(L.circle(home.latlng, {
    radius: WALK_CIRCLE_MINUTES * WALK_METERS_PER_MINUTE,
    color: WALK_CIRCLE, weight: 1.5, dashArray: "6 6", fill: true, fillColor: WALK_CIRCLE, fillOpacity: 0.05,
    interactive: false,
  }).addTo(map));
  homeLayers.push(L.marker(home.latlng, {
    icon: L.divIcon({ className: "", html: `<div class="campus-badge">${esc(home.name)}</div>`, iconSize: [0, 0] }),
    keyboard: false,
  }).addTo(map).bindTooltip(`Where the group needs to get to: ${esc(home.name)}`, { direction: "top" }));
}

const legend = L.control({ position: "bottomright" });
legend.onAdd = () => L.DomUtil.create("div", "legend");
legend.addTo(map);

function renderLegend() {
  legend.getContainer().innerHTML = "<b>Rent per person</b>" +
    tiers().map(t => `<span class="dot" style="background:${t.color}"></span>${t.label}<br>`).join("") +
    `<span class="dot" style="background:${UNKNOWN_COLOR}"></span>Unknown<br>` +
    `<span class="dot pick"></span>Fairest pick` +
    (home.latlng ? `<br><span class="walk-key"></span>~${WALK_CIRCLE_MINUTES}-min walk` : "");
}

// ---------- Helpers ----------
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const unknown = '<span class="tip-unknown">unknown</span>';
const money = n => "$" + Math.round(n).toLocaleString("en-US");
const label = v => LABELS[v] === undefined ? esc(v) : (LABELS[v] ?? unknown);
const score = s => (s == null ? "—" : s); // A score can be missing when too many facts are unknown.

// Same rule as rent_per_person() in app/scoring.py: split the whole-unit rent, else use the listed
// per-bed or per-room price as is (each person pays it), else unknown. Never guess.
function rentPerPerson(l) {
  if (l.rent_total_monthly != null) return Math.round(l.rent_total_monthly / Math.max(roommates.length, 1));
  if (l.rent_per_person_listed != null) return l.rent_per_person_listed;
  return null;
}

// Green: within everyone's budget. Amber: over someone's. Red: over everyone's.
function tiers() {
  const budgets = roommates.map(r => r.budget).filter(b => b > 0);
  if (!budgets.length) return [{ max: Infinity, color: TIER_COLORS.fits, label: "Known" }];
  const lo = Math.min(...budgets), hi = Math.max(...budgets);
  const t = [{ max: lo, color: TIER_COLORS.fits, label: `Up to ${money(lo)}: fits every budget` }];
  if (hi > lo) t.push({ max: hi, color: TIER_COLORS.some, label: `Up to ${money(hi)}: over someone's budget` });
  t.push({ max: Infinity, color: TIER_COLORS.none, label: `Over ${money(hi)}: over every budget` });
  return t;
}

function tierColor(l) {
  const rpp = rentPerPerson(l);
  return rpp == null ? UNKNOWN_COLOR : tiers().find(t => rpp <= t.max).color;
}

// The place sent for a roommate: their own, else the group's (null = the backend's default, UCLA).
function placeFor(r) {
  if (r.place) return r.place;
  return home.name.trim().toLowerCase() === DEFAULT_HOME.name.toLowerCase() ? null : home.name;
}

function minutes(v, what) {
  return v == null ? null : `${Math.round(v)} min ${what}`;
}

// One "why" line for the least happy roommate, using the listing's real facts.
function reasonText(r) {
  const name = (FACTOR_LABELS[r.criterion] || r.criterion).toLowerCase();
  let fact = r.raw_value;
  if (r.criterion === "rent" && typeof fact === "number") fact = money(fact) + "/person";
  else if (r.criterion === "commute" && typeof fact === "number") fact = commuteText(fact, r.commute_to, r.travel_mode);
  else if (r.criterion === "bedrooms" && fact != null) fact = `${fact} bd`;
  else fact = LABELS[fact] ?? fact;
  return `${esc(name)}${fact != null ? ` (${esc(fact)})` : ""}, −${r.points_lost} pts`;
}

// "31 min by bike to Santa Monica Pier". A blank place means the backend's default (UCLA).
function commuteText(mins, place, mode) {
  return `${Math.round(mins)} min ${TRAVEL_MODES[mode] || TRAVEL_MODES.WALK} to ${place || DEFAULT_HOME.name}`;
}

// ---------- Cards ----------
function groceryText(l) {
  if (l.nearest_grocery == null && l.grocery_walk_minutes == null) return unknown;
  const parts = [];
  if (l.nearest_grocery) parts.push(esc(l.nearest_grocery));
  if (l.grocery_walk_minutes != null) parts.push(esc(minutes(l.grocery_walk_minutes, "walk")));
  let text = parts.join(", ");
  if (l.grocery_count != null) text += ` · ${l.grocery_count} within 1 km`;
  return text;
}

function cardHtml(l, inPopup) {
  const rpp = rentPerPerson(l);
  const total = l.rent_total_monthly;
  const isPick = lastDecision?.pick.listing_id === l.id;
  const commute = [minutes(l.walk_minutes, "walk"), minutes(l.bike_minutes, "bike")].filter(Boolean).join(" / ");
  const rooms = [l.bedrooms != null ? `${l.bedrooms} bd` : null, l.bathrooms != null ? `${l.bathrooms} ba` : null]
    .filter(Boolean).join(" / ");

  let html = `${isPick ? '<div class="tip-pick">★ Fairest pick</div>' : ""}
    <div class="tip-name">${esc(l.title || l.address || "Listing")}</div>
    <div class="tip-price">${rpp == null ? `Rent per person: ${unknown}` : `<b>${money(rpp)}</b>/person`}
      ${total != null ? ` &middot; ${money(total)}/mo whole unit` : rpp != null ? " (listed per bed or room)" : ""}</div>
    <div class="tip-row"><span class="lab">🏠</span>${rooms || unknown}</div>
    <div class="tip-row"><span class="lab">🚶</span>${commute ? `${esc(commute)} to ${esc(l.commute_to || DEFAULT_HOME.name)}` : unknown}</div>
    <div class="tip-row"><span class="lab">🧺</span>Laundry: ${label(l.laundry)}</div>
    <div class="tip-row"><span class="lab">🅿️</span>Parking: ${label(l.parking)}</div>
    <div class="tip-row"><span class="lab">🛒</span>${groceryText(l)}</div>
    ${l.available_from ? `<div class="tip-row"><span class="lab">📅</span>Move-in: ${esc(l.available_from)}</div>` : ""}`;

  for (const f of l.red_flags || []) html += `<div class="tip-flag">⚠ ${esc(f)}</div>`;

  const ranked = lastDecision?.ranking.find(r => r.listing_id === l.id);
  if (ranked) {
    html += `<div class="tip-scores"><table>
      <tr><th>Roommate</th><th class="num">Score</th><th>Loses most on</th></tr>
      ${ranked.per_roommate.map(p => {
        const known = p.breakdown.filter(b => !b.unknown);
        const worst = known.length ? known.reduce((a, b) => (b.points_lost > a.points_lost ? b : a)) : null;
        // Show each roommate's own commute when it isn't the default walk to campus.
        const c = p.breakdown.find(b => b.criterion === "commute");
        const own = (p.commute_to || (p.travel_mode && p.travel_mode !== "WALK")) && c && !c.unknown && typeof c.raw_value === "number"
          ? `<div class="tip-sub">${esc(commuteText(c.raw_value, p.commute_to, p.travel_mode))}</div>` : "";
        return `<tr><td>${esc(p.roommate)}${own}</td><td class="num">${score(p.score)}</td>
          <td>${worst && worst.points_lost > 0 ? `${esc(FACTOR_LABELS[worst.factor] || worst.factor)} (−${worst.points_lost})` : "—"}</td></tr>`;
      }).join("")}
      </table>
      ${ranked.unknown?.length ? `<div class="tip-hint">Not scored, unknown for this place: ${esc(ranked.unknown.join(", "))}</div>` : ""}
    </div>`;
  } else if (!inPopup) {
    html += `<div class="tip-hint">Press "Find the fairest pick" to see each roommate's score.</div>`;
  }
  return html;
}

function drawListings() {
  Object.values(markers).forEach(m => m.remove());
  markers = {};
  if (pickHalo) { pickHalo.remove(); pickHalo = null; }
  const bounds = home.latlng ? [home.latlng] : [];
  for (const l of listings) {
    if (l.lat == null || l.lng == null) continue;
    const isPick = lastDecision?.pick.listing_id === l.id;
    const color = tierColor(l);
    if (isPick) {
      // Gold glow behind the fairest pick.
      pickHalo = L.circleMarker([l.lat, l.lng], { radius: 20, stroke: false, fillColor: PICK_GLOW, fillOpacity: 0.45, interactive: false }).addTo(map);
    }
    const m = L.circleMarker([l.lat, l.lng], {
      radius: isPick ? 12 : 9, color: isPick ? PICK_RING : MARKER_EDGE, weight: isPick ? 3 : 2,
      fillColor: color, fillOpacity: 0.95,
    }).addTo(map);
    m.bindTooltip(() => cardHtml(l, false), { className: "apt-tip", sticky: true, direction: "top", offset: [0, -4], opacity: 1 });
    m.on("tooltipopen", e => {
      // While a listing is open from a click, hovering other dots shows nothing, so they don't cover it.
      if (openPopup) { m.closeTooltip(); return; }
      e.tooltip.getElement().style.borderTopColor = isPick ? PICK_GLOW : color;
    });
    // Click opens the same card as a popup, so it also works on phones where there is no hover.
    m.bindPopup(() => cardHtml(l, true), { maxWidth: 300 });
    if (isPick) m.bringToFront();
    markers[l.id] = m;
    bounds.push([l.lat, l.lng]);
  }
  return bounds;
}

function focusListing(id) {
  const m = markers[id];
  if (!m) return;
  map.panTo(m.getLatLng());
  m.openPopup();
}

// ---------- Roommates ----------
function renderRoommates() {
  document.getElementById("roommates").innerHTML = roommates.map((r, i) => `
    <div class="roommate">
      <div class="roommate-head">
        <input type="text" value="${esc(r.name)}" aria-label="Roommate name" onchange="roommates[${i}].name=this.value">
        <span class="budget">max $<input type="number" value="${r.budget}" min="1" step="50" aria-label="${esc(r.name)} max rent per month" onchange="roommates[${i}].budget=+this.value; budgetsChanged()"></span>
        ${roommates.length > 1 ? `<button class="remove" title="Remove ${esc(r.name)}" aria-label="Remove ${esc(r.name)}" onclick="removeRoommate(${i})">×</button>` : ""}
      </div>
      <div class="roommate-commute">
        <input type="text" value="${esc(r.place || "")}" placeholder="Going to: ${esc(home.name || "our place")} (or type another)"
               aria-label="Where ${esc(r.name)} needs to get to" title="Type a specific place, e.g. Santa Monica Pier, Santa Monica, CA"
               onchange="roommates[${i}].place=this.value.trim()">
        <select aria-label="How ${esc(r.name)} gets there" onchange="roommates[${i}].travel_mode=this.value">
          ${Object.entries(TRAVEL_MODES).map(([m, w]) => `<option value="${m}"${(r.travel_mode || "WALK") === m ? " selected" : ""}>${w[0].toUpperCase() + w.slice(1)}</option>`).join("")}
        </select>
      </div>
      ${FACTORS.map(f => `
        <div class="rating"><span>${FACTOR_LABELS[f]}</span>
          <div class="rating-buttons" role="radiogroup" aria-label="How much ${esc(FACTOR_LABELS[f].toLowerCase())} matters to ${esc(r.name)}">
            ${[0, 1, 2, 3, 4, 5].map(v => `<button type="button" role="radio" aria-checked="${r.weights[f] === v}"
              class="${r.weights[f] === v ? "on" : ""}" title="${v}: ${RATING_WORDS[v]}"
              onclick="setWeight(${i}, '${f}', ${v}, this)">${v}</button>`).join("")}
          </div></div>`).join("")}
      ${typeof wishChips === "function" ? wishChips(r) : ""}
    </div>`).join("");
}

// Updates only the clicked row, so the rest of the panel doesn't redraw.
function setWeight(i, f, v, btn) {
  roommates[i].weights[f] = v;
  for (const b of btn.parentElement.children) {
    const on = b === btn;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on);
  }
}

// Budgets set the marker colors.
function budgetsChanged() {
  renderLegend();
  drawListings();
}

// The group's destination changed: find it on the map (if the backend can) and clear the old pick.
async function setHome(text) {
  const name = text.trim() || DEFAULT_HOME.name;
  home = name.toLowerCase() === DEFAULT_HOME.name.toLowerCase() ? { ...DEFAULT_HOME } : { name, latlng: null };
  if (!home.latlng) {
    try {
      // Needs a geocode route on the backend (see TASKS.md, "For Freddy: make it work anywhere"). Until then the
      // pick still uses this place for everyone's commute; the map just has no badge for it.
      const r = await fetch("/api/place?q=" + encodeURIComponent(name));
      const p = r.ok ? await r.json() : null;
      if (p?.lat != null && p?.lng != null && home.name === name) home.latlng = [p.lat, p.lng];
    } catch { /* No geocoder: keep going without the badge. */ }
  }
  lastDecision = null;
  showEmptyResult();
  renderRoommates();
  renderLegend();
  drawHome();
  const bounds = drawListings();
  if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
}

// For people who aren't near UCLA: drop the demo listings and paste their own.
function clearDemo() {
  listings = listings.filter(l => !demoIds.has(l.id));
  demoIds.clear();
  document.getElementById("startFresh").hidden = true;
  lastDecision = null;
  showEmptyResult();
  drawListings();
  const s = document.getElementById("parseStatus");
  s.className = "status";
  s.textContent = "Demo listings removed. Paste a listing from anywhere to add it.";
  document.getElementById("paste").focus();
}

function showEmptyResult() {
  document.getElementById("result").innerHTML =
    '<div class="empty">No pick yet. Set everyone\'s priorities, then press the button.</div>';
}

// The group size changes rent per person, so the old decision and marker colors are stale.
function roommatesChanged() {
  lastDecision = null;
  showEmptyResult();
  renderRoommates();
  renderLegend();
  drawListings();
}

function addRoommate() {
  roommates.push({ name: "Roommate " + (roommates.length + 1), budget: 1500, place: "", travel_mode: "WALK",
                   weights: { rent: 3, commute: 3, laundry: 3, parking: 3, bedrooms: 3 } });
  roommatesChanged();
}

function removeRoommate(i) {
  roommates.splice(i, 1);
  roommatesChanged();
}

// ---------- Backend calls ----------
async function runDecision() {
  const out = document.getElementById("result");
  const btn = document.getElementById("decideBtn");
  if (!listings.length) {
    out.innerHTML = '<div class="status error">No listings yet. Paste one in step 3 first.</div>';
    return;
  }
  btn.disabled = true;
  out.innerHTML = '<div class="status"><span class="spinner"></span>Scoring every place for every roommate…</div>';
  try {
    const res = await fetch("/api/decide", {
      method: "POST", headers: { "Content-Type": "application/json" },
      // A blank place uses the group's; null means the backend's default (UCLA).
      body: JSON.stringify({ listings, roommates: roommates.map(r => ({ ...r, place: placeFor(r) })) }),
    });
    const d = await res.json();
    if (!res.ok) { out.innerHTML = `<div class="status error">Couldn't decide: ${esc(d.detail)}</div>`; return; }
    lastDecision = d;
    const lh = d.least_happy;
    out.innerHTML = `<div class="result">
        <div class="pick">★ ${esc(d.pick.title)}</div>
        <div class="why">${d.everyone_agrees
          ? "Everyone's favorite is the same place."
          : `<b>${esc(lh.roommate)}</b> gives up the most (score ${score(lh.score)})${lh.reasons?.length
              ? ": " + lh.reasons.map(reasonText).join("; ") : ""}.`}</div>
        ${d.pick.unknown?.length ? `<div class="why tip-unknown">Some facts are unknown for this place: ${esc(d.pick.unknown.join(", "))}.</div>` : ""}
        <div class="explain" id="explain"><span class="spinner"></span>Writing a plain-English summary…</div>
      </div>
      ${d.conflicts.length ? `<div class="conflict">Roommates disagree most on: ${d.conflicts.map(c => esc(c.title)).join(", ")}</div>` : ""}
      <table><tr><th>Place</th><th class="num">Lowest</th><th class="num">Average</th></tr>
        ${d.ranking.map(r => `<tr class="clickable${r.listing_id === d.pick.listing_id ? " is-pick" : ""}" onclick="focusListing('${esc(r.listing_id)}')">
          <td>${esc(r.title)}${r.red_flags.length ? ' <span class="flag" title="Has red flags, so it can only win if every listing has one">⚠</span>' : ""}</td>
          <td class="num">${score(r.min_score)}</td><td class="num">${score(r.avg_score)}</td></tr>`).join("")}
      </table>
      <div class="status">"Lowest" is the least happy roommate's score. Click a row to find it on the map.</div>`;
    drawListings();
    focusListing(d.pick.listing_id);
    // On a laptop screen the result is below the roommate cards, so bring it into view.
    out.scrollIntoView({ behavior: "smooth", block: "start" });
    explainDecision(d);
  } catch {
    out.innerHTML = '<div class="status error">Couldn\'t reach the server. Is it still running?</div>';
  } finally {
    btn.disabled = false;
  }
}

// Gemini only writes the summary; the decision is already made by our own code.
function explainDecision(d) {
  fetch("/api/explain", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pick: d.pick, least_happy: d.least_happy, favorites: d.favorites,
                           ranking: d.ranking.map(r => ({ title: r.title, min: r.min_score, avg: r.avg_score })) }),
  })
    .then(r => (r.ok ? r.json() : null))
    .then(j => {
      const el = document.getElementById("explain");
      if (!el) return;
      if (j) el.textContent = j.text; else el.remove();
    })
    .catch(() => document.getElementById("explain")?.remove());
}

async function parseListing() {
  const status = document.getElementById("parseStatus");
  const btn = document.getElementById("parseBtn");
  const text = document.getElementById("paste").value.trim();
  if (!text) { status.className = "status error"; status.textContent = "Paste a listing first."; return; }

  btn.disabled = true;
  status.className = "status";
  let step = 0;
  const showStep = () => { status.innerHTML = `<span class="spinner"></span>${PARSE_STEPS[step]}`; };
  showStep();
  const timer = setInterval(() => { if (step < PARSE_STEPS.length - 1) { step++; showStep(); } }, 1800);

  try {
    const res = await fetch("/api/parse", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    const body = await res.json();
    if (!res.ok) { status.className = "status error"; status.textContent = "Couldn't read that listing: " + body.detail; return; }
    listings.push(body);
    lastDecision = null;
    showEmptyResult();
    drawListings();
    document.getElementById("paste").value = "";
    status.className = "status ok";
    if (body.lat != null) {
      status.textContent = `Added "${body.title || "listing"}" to the map. Press "Find the fairest pick" to include it.`;
      focusListing(body.id);
    } else {
      status.className = "status error";
      status.textContent = `Added "${body.title || "listing"}", but we couldn't place it on the map: the listing has no address we could find.`;
    }
  } catch {
    status.className = "status error";
    status.textContent = "Couldn't reach the server. Is it still running?";
  } finally {
    clearInterval(timer);
    btn.disabled = false;
  }
}

// ---------- Welcome screen ----------
function enterApp() {
  const w = document.getElementById("welcome");
  w.classList.add("leaving");
  setTimeout(() => { w.hidden = true; map.invalidateSize(); }, 450);
  if (location.hash !== "#app") history.replaceState(null, "", "#app");
}
// Skip the welcome screen when the URL ends in #app (handy while working on the page).
if (location.hash === "#app") document.getElementById("welcome").hidden = true;
else document.getElementById("welcomeStart").focus();

// ---------- Start ----------
renderRoommates();
renderLegend();
drawHome();
fetch("/api/demo")
  .then(r => r.json())
  .then(data => {
    listings = data;
    demoIds = new Set(data.map(l => l.id));
    map.fitBounds(drawListings(), { padding: [40, 40] });
  })
  .catch(() => {
    document.getElementById("result").innerHTML = '<div class="status error">Couldn\'t load the demo listings. Is the server running?</div>';
  });
