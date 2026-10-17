// Map page: draws listings on a Leaflet map, collects each roommate's priorities,
// and shows the fair pick that the backend's own scoring code computes.
// Nothing here scores a listing; the per-person rent is only for the marker colors and cards.

const CAMPUS = { name: "UCLA", latlng: [34.0699182, -118.4438495] };
const WALK_CIRCLE_MINUTES = 35;
const WALK_METERS_PER_MINUTE = 80; // ~3 mph, so 35 min is about 2.8 km (1.75 mi), as in the earlier map
// Must match CRITERIA in app/scoring.py.
const FACTORS = ["rent", "commute", "laundry", "parking", "bedrooms"];

// Per-person rent tiers for marker colors (upper bound in dollars, inclusive).
const TIERS = [
  { max: 1300, color: "#2e9e5b", label: "≤ $1,300" },
  { max: 1550, color: "#2b7fd4", label: "$1,301–$1,550" },
  { max: Infinity, color: "#e8893b", label: "$1,551+" },
];
const UNKNOWN_COLOR = "#8a94a6";

// Readable labels for both the current field values and the ones in the brief's schema.
const LABELS = {
  in_unit: "In-unit", in_building: "Shared in building", shared: "Shared", none: "None",
  included: "Included", extra_cost: "Extra cost", paid: "Paid", unknown: null,
};

let listings = [];
let roommates = [
  { name: "Alex", budget: 1500, weights: { rent: 5, commute: 2, laundry: 3, parking: 1, bedrooms: 2 } },
  { name: "Sam", budget: 1900, weights: { rent: 2, commute: 5, laundry: 3, parking: 4, bedrooms: 3 } },
  { name: "Jordan", budget: 1700, weights: { rent: 3, commute: 3, laundry: 5, parking: 2, bedrooms: 3 } },
];
let markers = {};
let lastDecision = null;

// ---------- Map ----------
const map = L.map("map", { scrollWheelZoom: true }).setView(CAMPUS.latlng, 14);
// Standard OpenStreetMap tiles. The CARTO tiles from the earlier map now need an API key.
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors", maxZoom: 19,
}).addTo(map);

L.circle(CAMPUS.latlng, {
  radius: WALK_CIRCLE_MINUTES * WALK_METERS_PER_MINUTE,
  color: "#2b5fa3", weight: 1.5, dashArray: "6 6", fill: true, fillColor: "#2b5fa3", fillOpacity: 0.05,
  interactive: false,
}).addTo(map);

L.marker(CAMPUS.latlng, {
  icon: L.divIcon({ className: "", html: `<div class="campus-badge">${CAMPUS.name}</div>`, iconSize: [50, 22], iconAnchor: [25, 11] }),
  keyboard: false,
}).addTo(map).bindTooltip(`${CAMPUS.name} campus center`, { direction: "top" });

const legend = L.control({ position: "bottomright" });
legend.onAdd = () => {
  const d = L.DomUtil.create("div", "legend");
  d.innerHTML = "<b>Rent per person</b>" +
    TIERS.map(t => `<span class="dot" style="background:${t.color}"></span>${t.label}<br>`).join("") +
    `<span class="dot" style="background:${UNKNOWN_COLOR}"></span>Unknown<br>` +
    `<span class="dot pick"></span>Fairest pick<br>` +
    `<span class="walk-key"></span>~${WALK_CIRCLE_MINUTES}-min walk`;
  return d;
};
legend.addTo(map);

// ---------- Helpers ----------
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const unknown = '<span class="tip-unknown">unknown</span>';
const money = n => "$" + Math.round(n).toLocaleString("en-US");
const label = v => LABELS[v] === undefined ? esc(v) : (LABELS[v] ?? unknown);

// Whole-unit monthly rent, from either the current shape (price + price_type) or the brief's (rent_total_monthly).
function totalRent(l) {
  if (l.rent_total_monthly != null) return l.rent_total_monthly;
  if (l.price != null && l.price_type === "whole_unit") return l.price;
  return null;
}

function rentPerPerson(l) {
  const total = totalRent(l);
  if (total != null) return Math.round(total / Math.max(roommates.length, 1));
  if (l.price != null && (l.price_type === "per_room" || l.price_type === "per_bed")) return l.price;
  return null; // Price missing or unclear how it splits: show unknown, never guess.
}

function tierColor(l) {
  const rpp = rentPerPerson(l);
  return rpp == null ? UNKNOWN_COLOR : TIERS.find(t => rpp <= t.max).color;
}

function minutes(v, what) {
  return v == null ? null : `${Math.round(v)} min ${what}`;
}

// ---------- Cards ----------
function cardHtml(l, inPopup) {
  const rpp = rentPerPerson(l);
  const total = totalRent(l);
  const isPick = lastDecision?.pick.listing_id === l.id;
  const commute = [minutes(l.walk_minutes, "walk"), minutes(l.bike_minutes, "bike")].filter(Boolean).join(" / ");
  const rooms = [l.bedrooms != null ? `${l.bedrooms} bd` : null, l.bathrooms != null ? `${l.bathrooms} ba` : null]
    .filter(Boolean).join(" / ");

  let html = `${isPick ? '<div class="tip-pick">★ Fairest pick</div>' : ""}
    <div class="tip-name">${esc(l.title || l.address || "Listing")}</div>
    <div class="tip-price">${rpp == null ? `Rent per person: ${unknown}` : `<b>${money(rpp)}</b>/person`}
      ${total != null ? ` &middot; ${money(total)}/mo whole unit` : ""}</div>
    <div class="tip-row"><span class="lab">🏠</span>${rooms || unknown}</div>
    <div class="tip-row"><span class="lab">🚶</span>${commute ? esc(commute) + " to campus" : unknown}</div>
    <div class="tip-row"><span class="lab">🧺</span>Laundry: ${label(l.laundry)}</div>
    <div class="tip-row"><span class="lab">🅿️</span>Parking: ${label(l.parking)}</div>
    <div class="tip-row"><span class="lab">🛒</span>Groceries: ${l.grocery_walk_minutes == null ? unknown : esc(minutes(l.grocery_walk_minutes, "walk"))}</div>
    ${l.available_from ? `<div class="tip-row"><span class="lab">📅</span>Move-in: ${esc(l.available_from)}</div>` : ""}`;

  for (const f of l.red_flags || []) html += `<div class="tip-flag">⚠ ${esc(f)}</div>`;

  const ranked = lastDecision?.ranking.find(r => r.listing_id === l.id);
  if (ranked) {
    const unknownFactors = ranked.per_roommate[0].breakdown.filter(b => b.unknown).map(b => b.factor);
    html += `<div class="tip-scores"><table>
      <tr><th>Roommate</th><th>Score</th><th>Loses most on</th></tr>
      ${ranked.per_roommate.map(p => {
        const worst = p.breakdown.reduce((a, b) => (b.points_lost > a.points_lost ? b : a));
        return `<tr><td>${esc(p.roommate)}</td><td>${p.score}</td><td>${esc(worst.factor)} (−${worst.points_lost})</td></tr>`;
      }).join("")}
      </table>
      ${unknownFactors.length ? `<div class="tip-hint">Not known for this place: ${esc(unknownFactors.join(", "))}</div>` : ""}
    </div>`;
  } else if (!inPopup) {
    html += `<div class="tip-hint">Press "Find the fairest pick" to see each roommate's score.</div>`;
  }
  return html;
}

function drawListings() {
  Object.values(markers).forEach(m => m.remove());
  markers = {};
  const bounds = [CAMPUS.latlng];
  for (const l of listings) {
    if (l.lat == null || l.lng == null) continue;
    const isPick = lastDecision?.pick.listing_id === l.id;
    const color = tierColor(l);
    const m = L.circleMarker([l.lat, l.lng], {
      radius: isPick ? 13 : 9, color: isPick ? "#1d1d1b" : "#fff", weight: isPick ? 3 : 2,
      fillColor: color, fillOpacity: 0.95,
    }).addTo(map);
    m.bindTooltip(() => cardHtml(l, false), { className: "apt-tip", sticky: true, direction: "top", offset: [0, -4] });
    m.on("tooltipopen", e => { e.tooltip.getElement().style.borderTopColor = color; });
    // Click opens the same card as a popup, so it also works on phones where there is no hover.
    m.bindPopup(() => cardHtml(l, true), { maxWidth: 290 });
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
        <input type="number" value="${r.budget}" min="1" aria-label="Max rent per month" title="Max rent per month" onchange="roommates[${i}].budget=+this.value">
        ${roommates.length > 1 ? `<button class="remove" title="Remove roommate" onclick="removeRoommate(${i})">×</button>` : ""}
      </div>
      <div class="muted" style="margin:4px 0">How much each thing matters (0–5)</div>
      ${FACTORS.map(f => `
        <div class="slider"><span>${f}</span>
          <input type="range" min="0" max="5" value="${r.weights[f]}" aria-label="${esc(r.name)} ${f} weight"
                 oninput="roommates[${i}].weights.${f}=+this.value; this.nextElementSibling.textContent=this.value">
          <span>${r.weights[f]}</span></div>`).join("")}
    </div>`).join("");
}

// The group size changes rent per person, so the old decision and marker colors are stale.
function roommatesChanged() {
  lastDecision = null;
  document.getElementById("result").innerHTML = "";
  renderRoommates();
  drawListings();
}

function addRoommate() {
  roommates.push({ name: "Roommate " + (roommates.length + 1), budget: 1500,
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
  out.innerHTML = '<span class="muted">Scoring every place for every roommate…</span>';
  const res = await fetch("/api/decide", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ listings, roommates }),
  });
  if (!res.ok) { out.textContent = "Error: " + (await res.json()).detail; return; }
  lastDecision = await res.json();
  const d = lastDecision;
  out.innerHTML = `<div class="result">
      <b>Fairest pick: ${esc(d.pick.title)}</b><br>
      ${esc(d.least_happy.roommate)} gives up the most (score ${d.least_happy.score}, mostly on ${esc(d.least_happy.gives_up_most_on)}).
      ${d.conflicts.length ? `<br><span class="flag">Roommates disagree on: ${d.conflicts.map(c => esc(c.title)).join(", ")}</span>` : ""}
      <div id="explain" class="muted" style="margin-top:6px"></div>
    </div>
    <table><tr><th>Listing</th><th>Lowest</th><th>Average</th></tr>
      ${d.ranking.map(r => `<tr class="clickable" onclick="focusListing('${esc(r.listing_id)}')"><td>${esc(r.title)}${r.red_flags.length ? ' <span class="flag" title="Has red flags, so it can only win if every listing has one">⚠</span>' : ""}</td><td>${r.min_score}</td><td>${r.avg_score}</td></tr>`).join("")}
    </table>
    <div class="muted" style="margin-top:4px">Click a row to find it on the map.</div>`;
  drawListings();
  focusListing(d.pick.listing_id);
  // Gemini only writes the summary; the decision above is already made by our own code.
  fetch("/api/explain", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pick: d.pick, least_happy: d.least_happy, favorites: d.favorites,
                           ranking: d.ranking.map(r => ({ title: r.title, min: r.min_score, avg: r.avg_score })) }),
  })
    .then(r => (r.ok ? r.json() : null))
    .then(j => { if (j) document.getElementById("explain").textContent = j.text; })
    .catch(() => {});
}

async function parseListing() {
  const status = document.getElementById("parseStatus");
  const text = document.getElementById("paste").value.trim();
  if (!text) { status.textContent = "Paste a listing first."; return; }
  status.textContent = "Reading the listing…";
  const res = await fetch("/api/parse", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
  });
  const body = await res.json();
  if (!res.ok) { status.textContent = "Error: " + body.detail; return; }
  listings.push(body);
  lastDecision = null;
  drawListings();
  status.textContent = `Added "${body.title || "listing"}".` +
    (body.lat == null ? " It isn't on the map yet: finding its location comes with the Google Maps step." : "");
  if (body.lat != null) focusListing(body.id);
}

// ---------- Start ----------
renderRoommates();
fetch("/api/demo")
  .then(r => r.json())
  .then(data => {
    listings = data;
    map.fitBounds(drawListings(), { padding: [40, 40] });
  })
  .catch(() => { document.getElementById("result").textContent = "Could not load the demo listings. Is the server running?"; });
