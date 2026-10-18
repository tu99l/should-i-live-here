// Welcome screen: "What are you looking for?" in your own words -> the map with real listings and the fair pick.
// 1. Your text goes to /api/wishes (Gemini sorts it, our code checks every quote; nothing is scored here).
// 2. What we understood becomes the first roommate's priorities, wishes and budget.
// 3. Real listings near your place come from /api/search (RentCast), then the fair pick runs as usual.
// Uses app.js's shared state: roommates, renderRoommates, setHome, enterApp, runDecision, budgetsChanged.
(function () {
  const el = id => document.getElementById(id);
  const h = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const DEFAULT_WEIGHTS = { rent: 3, commute: 3, laundry: 3, parking: 3, bedrooms: 3 };
  const CRITERIA_WORDS = { rent: "low rent", commute: "short commute", laundry: "laundry", parking: "parking", bedrooms: "enough bedrooms" };

  // Same words as the bot's replies (LEVEL_NAMES in app/wishes.py).
  function level(w) {
    if (w >= 5) return "must";
    if (w >= 4.5) return "important";
    if (w >= 3) return "wanted";
    if (w > 0) return "nice to have";
    return "don't care";
  }

  function wantLabel(w) {
    if (w.kind === "near") return `near ${w.what}`;
    return w.what;  // "gas included", "own bathroom"
  }

  // Chips for one roommate's own wishes (also shown on their card).
  function wishChips(r) {
    const wants = r.wants || [];
    const strict = r.strict || [];
    const chips = [];
    if (strict.includes("in_unit_laundry")) chips.push(["in-unit laundry", r.weights.laundry]);
    if (strict.includes("included_parking")) chips.push(["free parking", r.weights.parking]);
    for (const w of wants) chips.push([wantLabel(w), w.weight, w.quote]);
    if (!chips.length) return "";
    return `<div class="wish-chips card-wishes">${chips.map(([label, weight, quote]) =>
      `<span class="wish-chip ${weight >= 5 ? "must" : ""}" title="${h(quote ? `"${quote}"` : "")}">${h(label)} · ${level(weight)}</span>`).join("")}</div>`;
  }
  window.wishChips = wishChips;  // app.js's roommate cards call this when it exists.

  // Make the group the size they picked: keep the first people, add blank ones as needed.
  function setGroupSize(n) {
    roommates.splice(n);
    while (roommates.length < n) {
      roommates.push({ name: `Roommate ${roommates.length + 1}`, budget: 1500, place: "", travel_mode: "WALK",
                       weights: { ...DEFAULT_WEIGHTS } });
    }
  }

  function applyWishes(me, w) {
    for (const [c, v] of Object.entries(w.weights || {})) me.weights[c] = Math.floor(v);  // The grid shows whole numbers.
    me.wants = w.wants || [];
    me.strict = w.strict || [];
    if (w.budget) me.budget = w.budget;
    if (w.place) { me.place = w.place; if (w.travel_mode) me.travel_mode = w.travel_mode; }
  }

  function showAskedFor(name, w, note) {
    const box = el("askedFor");
    const parts = [];
    if (w) {
      for (const [c, v] of Object.entries(w.weights || {})) {
        const label = c === "laundry" && (w.strict || []).includes("in_unit_laundry") ? "in-unit laundry"
          : c === "parking" && (w.strict || []).includes("included_parking") ? "free parking" : CRITERIA_WORDS[c];
        parts.push(`<span class="wish-chip ${v >= 5 ? "must" : ""}" title="${h(`"${w.evidence?.[c] || ""}"`)}">${h(label)} · ${level(v)}</span>`);
      }
      for (const x of w.wants || []) parts.push(`<span class="wish-chip ${x.weight >= 5 ? "must" : ""}" title="${h(`"${x.quote || ""}"`)}">${h(wantLabel(x))} · ${level(x.weight)}</span>`);
      if (w.budget) parts.push(`<span class="wish-chip">up to $${Math.round(w.budget).toLocaleString("en-US")}/mo</span>`);
      if (w.place) parts.push(`<span class="wish-chip">commute to ${h(w.place)}</span>`);
    }
    let html = `<b>${h(name)} asked for</b>`;
    html += parts.length ? `<div class="wish-chips">${parts.join("")}</div>` : `<div class="asked-none">Nothing specific yet: the 0–5 ratings below decide.</div>`;
    if (w?.cannot_check?.length) html += `<div class="asked-note">Can't check ${w.cannot_check.map(q => `"${h(q)}"`).join(", ")}: no listing or map shows that, so it isn't scored.</div>`;
    if (w?.not_understood?.length) html += `<div class="asked-note">Didn't catch ${w.not_understood.map(q => `"${h(q)}"`).join(", ")}.</div>`;
    if (note) html += `<div class="asked-note">${h(note)}</div>`;
    box.innerHTML = html;
    box.hidden = false;
  }

  function say(text, spin = true) {
    el("welcomeStatus").innerHTML = (spin ? '<span class="spinner"></span>' : "") + h(text);
  }

  async function start(event) {
    event.preventDefault();
    const btn = el("welcomeStart");
    const text = el("welcomeWants").value.trim();
    const place = el("welcomePlace").value.trim() || "UCLA";
    const name = el("welcomeName").value.trim() || "You";
    btn.disabled = true;

    let w = null, note = "";
    if (text) {
      say("Reading what you want…");
      try {
        const r = await fetch("/api/wishes", { method: "POST", headers: { "Content-Type": "application/json" },
                                               body: JSON.stringify({ text }) });
        if (r.ok) w = await r.json();
        else note = "Couldn't read your wishes just now, so the 0–5 ratings decide. You can text them in later.";
      } catch {
        note = "Couldn't reach the server to read your wishes.";
      }
    }

    setGroupSize(+el("welcomePeople").value || 1);
    const me = roommates[0];
    me.name = name;
    if (w) applyWishes(me, w);
    el("homeBase").value = place;
    say(`Finding ${place} on the map…`);
    await setHome(place);
    if (typeof budgetsChanged === "function") budgetsChanged();
    renderRoommates();
    showAskedFor(name, w, note);

    say(`Looking for real rentals near ${place}…`);
    const found = await window.findListings();
    btn.disabled = false;
    el("welcomeStatus").textContent = "";
    enterApp();
    // Show the fair pick right away (the listings searched above plus any already on the map).
    if (listings.length) setTimeout(runDecision, found ? 500 : 0);
  }

  el("welcomeForm").addEventListener("submit", start);
  el("welcomeSkip").addEventListener("click", e => { e.preventDefault(); enterApp(); });
})();
