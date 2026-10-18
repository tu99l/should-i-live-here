// View-only results page for roommates (opened from the link the bot texts). Reads /api/share/<code>:
// the group, the listings and the fair pick our code computed. Nothing here can change anything.
// Refreshes by itself when the group changes (someone texts the bot).
(function () {
  const POLL_MS = 8000;
  const code = location.pathname.split("/").filter(Boolean).pop();
  const h = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = n => n == null ? null : "$" + Math.round(n).toLocaleString("en-US");
  const el = id => document.getElementById(id);
  const COLORS = { good: "#1f7a4d", ok: "#e8a23b", bad: "#c2412d", unknown: "#8a94a6", pick: "#ffc72c", navy: "#1e3a5f" };
  const CRITERIA = { rent: "low rent", commute: "short commute", laundry: "laundry", parking: "parking", bedrooms: "own bedroom each" };
  const MODES = { WALK: "walking", BICYCLE: "by bike", TRANSIT: "by transit", DRIVE: "driving" };
  const PLAIN = { "laundry|shared": "shared laundry", "laundry|none": "no laundry", "parking|paid": "paid parking", "parking|none": "no parking" };

  let version = null, map = null, markers = {}, fitted = false;

  function level(w, asked) {
    if (w >= 5) return "must";
    if (w >= 4.5) return "important";
    if (w >= 4 || (asked && w >= 3)) return "wanted";
    if (w > 0) return "nice to have";
    return "don't care";
  }

  function reason(r) {
    const c = r.criterion, v = r.raw_value;
    if (r.kind === "near") return `${Math.round(v)} min walk to ${r.place_name || c.replace("near: ", "the nearest ")}`;
    if (r.kind === "feature") return `no ${c.replace("has: ", "")}`;
    if (r.kind === "bathroom") return `${v} bathrooms for ${r.needed} needed`;
    if (c === "rent") return `rent ${money(v)} each`;
    if (c === "commute") return `${Math.round(v)} min commute`;
    if (c === "bedrooms") return `only ${v} bedrooms`;
    return PLAIN[`${c}|${v}`] || `${c}: ${v}`;
  }

  function colorFor(row) {
    if (!row || row.min_score == null) return COLORS.unknown;
    if (row.red_flags?.length) return COLORS.unknown;
    return row.min_score >= 70 ? COLORS.good : row.min_score >= 50 ? COLORS.ok : COLORS.bad;
  }

  function renderPick(d, people, listingsById) {
    const box = el("pick");
    if (!d) { box.innerHTML = '<div class="sh-muted">No pick yet: nobody has said what they want.</div>'; return; }
    const row = d.ranking.find(r => r.listing_id === d.pick.listing_id);
    const l = listingsById[d.pick.listing_id] || {};
    const lh = d.least_happy;
    const why = (lh.reasons || []).map(reason).join(" and ");
    box.innerHTML = `
      <div class="label">The fairest pick for all of you</div>
      <div class="title">★ ${h(d.pick.title)}</div>
      <div class="rent">${row?.rent_per_person != null ? `<b>${money(row.rent_per_person)}</b> each` : "Rent each: unknown"}
        · ${l.bedrooms ?? "?"} bd, ${l.bathrooms ?? "?"} ba${l.walk_minutes != null ? ` · ${Math.round(l.walk_minutes)} min walk` : ""}</div>
      <div class="why">${d.everyone_agrees ? "It's everyone's favorite."
        : `<b>${h(lh.roommate)}</b> gives up the most here (${lh.score ?? "?"}/100)${why ? `: ${h(why)}` : ""}. Every other place leaves someone worse off.`}</div>
      ${d.pick.unknown?.length ? `<div class="sh-small sh-muted">Unknown for this place: ${h(d.pick.unknown.join(", "))}.</div>` : ""}`;
  }

  function renderScores(d) {
    if (!d) { el("scores").innerHTML = ""; return; }
    const row = d.ranking.find(r => r.listing_id === d.pick.listing_id);
    el("scores").innerHTML = row.per_roommate.map(p => {
      const lost = p.breakdown.filter(b => !b.unknown && b.points_lost > 0).sort((a, b) => b.points_lost - a.points_lost).slice(0, 2);
      return `<div class="score-row"><span class="name">${h(p.roommate)}</span>
          <span class="bar"><span style="width:${Math.max(0, Math.min(100, p.score ?? 0))}%"></span></span>
          <span class="num">${p.score ?? "?"}</span></div>
        ${lost.length ? `<div class="score-why">Gives up: ${lost.map(b => h(reason(b))).join(", ")}</div>` : ""}`;
    }).join("");
  }

  function renderRanking(d) {
    if (!d) { el("ranking").innerHTML = ""; return; }
    el("ranking").innerHTML = `<tr><th>#</th><th>Place</th><th class="num">Each</th><th class="num">Lowest</th><th class="num">Avg</th></tr>` +
      d.ranking.map(r => `<tr class="row${r.listing_id === d.pick.listing_id ? " is-pick" : ""}" data-id="${h(r.listing_id)}">
        <td class="num">${r.rank}</td><td>${h(r.title)}${r.red_flags?.length ? ' <span class="sh-flag" title="Check this listing">⚠</span>' : ""}</td>
        <td class="num">${money(r.rent_per_person) || "?"}</td><td class="num">${r.min_score ?? "—"}</td><td class="num">${r.avg_score ?? "—"}</td></tr>`).join("");
  }

  function renderPeople(data) {
    el("people").innerHTML = data.people.map(p => {
      const r = p.roommate, out = [];
      const strict = r.strict || [];
      for (const [c, label] of Object.entries(CRITERIA)) {
        const w = r.weights[c];
        if (c === "laundry" && strict.includes("in_unit_laundry")) { out.push(["in-unit laundry", w]); continue; }
        if (c === "parking" && strict.includes("included_parking")) { out.push(["free parking", w]); continue; }
        if (w >= 4 || w === 0) out.push([label, w]);
      }
      for (const x of r.wants || []) out.push([x.kind === "near" ? `near ${x.what}` : x.what, x.weight, true]);
      const chips = out.map(([label, w, asked]) =>
        `<span class="chip ${w >= 5 ? "must" : w === 0 ? "dontcare" : ""}">${h(label)} · ${level(w, asked)}</span>`).join("");
      return `<div class="person"><div class="who">${h(p.name)}</div>
        <div class="facts">Up to ${money(r.budget)}/mo · ${h(r.place || data.place)}, ${MODES[r.travel_mode] || "walking"}</div>
        <div class="chips">${chips || '<span class="sh-muted sh-small">Hasn\'t said anything yet.</span>'}</div>
        ${p.last_text ? `<div class="said">“${h(p.last_text)}”</div>` : ""}</div>`;
    }).join("");
  }

  function popup(l, row, isPick) {
    const lines = [];
    lines.push(row?.rent_per_person != null ? `<b>${money(row.rent_per_person)}</b> each` : (l.listed_price ? `Listed ${money(l.listed_price)} (per person unknown)` : "Rent unknown"));
    lines.push(`${l.bedrooms ?? "?"} bd · ${l.bathrooms ?? "?"} ba${l.walk_minutes != null ? ` · ${Math.round(l.walk_minutes)} min walk` : ""}`);
    const lp = [l.laundry && l.laundry !== "unknown" ? `laundry: ${l.laundry.replace("_", "-")}` : '<span class="pop-unknown">laundry unknown</span>',
                l.parking && l.parking !== "unknown" ? `parking: ${l.parking}` : '<span class="pop-unknown">parking unknown</span>'];
    lines.push(lp.join(" · "));
    if (row) lines.push(row.per_roommate.map(p => `${h(p.roommate)} ${p.score ?? "?"}`).join(" · "));
    for (const f of l.red_flags || []) lines.push(`<span class="sh-flag">⚠ ${h(f)}</span>`);
    return `${isPick ? '<span class="pop-pick">Fairest pick</span><br>' : ""}<div class="pop-title">${h(l.title || l.address)}</div>${lines.join("<br>")}`;
  }

  function renderMap(data) {
    const d = data.decision;
    const rows = Object.fromEntries((d?.ranking || []).map(r => [r.listing_id, r]));
    if (!map) {
      map = L.map("map", { scrollWheelZoom: false }).setView([34.0699, -118.4438], 14);  // Moved to the listings below.
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap contributors", maxZoom: 19 }).addTo(map);
    }
    Object.values(markers).forEach(m => m.remove());
    markers = {};
    const bounds = [];
    let pickMarker = null;
    for (const l of data.listings) {
      if (l.lat == null || l.lng == null) continue;
      const isPick = d?.pick.listing_id === l.id;
      const m = L.circleMarker([l.lat, l.lng], {
        radius: isPick ? 12 : 8, weight: isPick ? 3 : 2, color: isPick ? COLORS.navy : "#fff",
        fillColor: isPick ? COLORS.pick : colorFor(rows[l.id]), fillOpacity: 0.95,
      }).addTo(map).bindPopup(popup(l, rows[l.id], isPick), { maxWidth: 280 });
      if (isPick) pickMarker = m;
      markers[l.id] = m;
      bounds.push([l.lat, l.lng]);
    }
    if (!fitted && bounds.length) { map.fitBounds(bounds, { padding: [24, 24], maxZoom: 15 }); fitted = true; }
    pickMarker?.bringToFront();  // After the map has a view (Leaflet can't layer markers before that).
    el("legend").innerHTML = `<span><span class="dot" style="background:${COLORS.pick}"></span>Fairest pick</span>
      <span><span class="dot" style="background:${COLORS.good}"></span>Good for everyone (70+)</span>
      <span><span class="dot" style="background:${COLORS.ok}"></span>OK (50–70)</span>
      <span><span class="dot" style="background:${COLORS.bad}"></span>Someone unhappy (under 50)</span>
      <span><span class="dot" style="background:${COLORS.unknown}"></span>Not enough facts or ⚠</span>`;
  }

  async function load() {
    try {
      const r = await fetch(`/api/share/${encodeURIComponent(code)}`);
      if (!r.ok) { el("pick").innerHTML = '<div class="sh-flag">This link isn\'t working right now. Ask the person who sent it.</div>'; return; }
      const data = await r.json();
      if (data.version === version) return;
      version = data.version;
      const names = data.people.map(p => p.name);
      el("who").textContent = (names.length ? names.slice(0, -1).join(", ") + (names.length > 1 ? " & " : "") + names.slice(-1) : "Your group")
        + ` · near ${data.place}`;
      const byId = Object.fromEntries(data.listings.map(l => [l.id, l]));
      renderPick(data.decision, data.people, byId);
      renderMap(data);
      renderScores(data.decision);
      renderRanking(data.decision);
      renderPeople(data);
      el("updated").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.`;
    } catch (e) {
      console.error(e);
      el("updated").textContent = "Can't reach the app right now; it'll try again.";
    }
  }

  el("ranking").addEventListener("click", e => {
    const tr = e.target.closest("tr.row");
    const m = tr && markers[tr.dataset.id];
    if (m) { map.setView(m.getLatLng(), 16); m.openPopup(); el("map").scrollIntoView({ behavior: "smooth", block: "center" }); }
  });

  load();
  setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
})();
