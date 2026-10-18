// "Find real listings near here": live rentals around the group's place, from RentCast (POST /api/search).
// Results are added to the map next to the demo and pasted listings (a new search replaces the old results).
// Uses app.js's shared state: `listings`, `roommates`, `drawListings()`, `showEmptyResult()`, `map`.
// RentCast has no laundry or parking data, so those show as unknown. Listings whose price looks like one
// room in a shared house come back flagged with a warning and an unknown rent per person; never split.
(function () {
  const el = id => document.getElementById(id);
  const h = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Returns the search result, or null if it failed (the reason is shown under the button).
  async function findListings() {
    let found = null;
    const btn = el("searchBtn"), status = el("searchStatus");
    const place = (el("homeBase").value || "").trim() || "UCLA";
    const budgets = roommates.map(r => +r.budget).filter(b => b > 0);
    const body = {
      place,
      radius_miles: +el("searchRadius").value || 2,
      min_bedrooms: groupSize(),  // Enough bedrooms for everyone the group expects (app.js).
      max_rent_per_person: budgets.length ? Math.max(...budgets) : null,  // Skip places over every budget.
    };
    btn.disabled = true;
    status.className = "status";
    status.innerHTML = `<span class="spinner"></span>Looking for rentals within ${body.radius_miles} mi of ${h(place)}…`;
    try {
      const r = await fetch("/api/search", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "The search didn't work.");
      found = data;
      listings = listings.filter(l => l.source !== "rentcast").concat(data.listings);
      window.saveListings?.();  // So the bot picks from the same places.
      lastDecision = null;
      showEmptyResult();
      const bounds = drawListings();
      if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
      status.className = "status ok";
      status.innerHTML = `Showing the ${data.shown} nearest of ${data.matching} rentals with ${body.min_bedrooms}+ bedrooms` +
        (body.max_rent_per_person ? ` within $${body.max_rent_per_person.toLocaleString("en-US")} each` : "") +
        ` (${data.found} active near ${h(data.place.name)}). Laundry and parking aren't in this data, so they show as unknown.` +
        (data.usage ? ` <span class="search-usage">New-area searches this month: ${data.usage.requests} of ${data.usage.cap}.</span>` : "") +
        (data.flagged_per_room ? ` <span class="search-flag">⚠ ${data.flagged_per_room} may be priced for one room, not the whole place. Their rent per person is left unknown until you check the listing.</span>` : "");
    } catch (e) {
      status.className = "status error";
      status.textContent = e.message;
    } finally {
      btn.disabled = false;
    }
    return found;
  }

  el("searchBtn").addEventListener("click", findListings);
  window.findListings = findListings;  // Used by the welcome screen (welcome.js).
})();
