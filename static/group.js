// "Your group": one card per person, from the group the backend shares with the iMessage bot.
// - You come from the welcome screen; others are invited by text or added here (for people without a phone).
// - A card shows what that person asked for, in chips (hover for their exact words), their budget and commute.
//   There is no 0–5 grid to fill in: their words set the weights; "See the math" shows them.
// - The page checks the group every few seconds. When someone texts the bot, their card fills in and the
//   fair pick updates by itself.
// Uses app.js's shared state: roommates (kept in step with the group), listings, home, runDecision,
// lastDecision, renderLegend, drawListings, showEmptyResult.
(function () {
  const POLL_MS = 3000;
  const el = id => document.getElementById(id);
  const h = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = encodeURIComponent;
  const CRITERIA = { rent: "low rent", commute: "short commute", laundry: "laundry", parking: "parking", bedrooms: "own bedroom each" };
  const MODES = { WALK: "walking", BICYCLE: "by bike", TRANSIT: "by transit", DRIVE: "driving" };
  let group = null;
  let busy = false;          // An edit is in flight: don't redraw over the person typing.
  const notes = {};          // Per-person note after adding wishes ("Can't check 'quiet street'").

  // Same words as the bot's replies (LEVEL_NAMES in app/wishes.py). Something a person asked for
  // ("near a gym") is never "neutral": 3 was "wanted" before weights moved up on Oct 17.
  function level(w, asked = false) {
    if (w >= 5) return "must";
    if (w >= 4.5) return "important";
    if (w >= 4 || (asked && w >= 3)) return "wanted";
    if (w >= 3) return "neutral";
    if (w > 0) return "nice to have";
    return "don't care";
  }

  function prettyPhone(p) {
    const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(p || "");
    return m ? `+1 (${m[1]}) ${m[2]}-${m[3]}` : (p || "");
  }

  async function api(method, url, body) {
    const r = await fetch(url, { method, headers: { "Content-Type": "application/json" },
                                 body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || "Something went wrong.");
    return data;
  }

  // ---------- Cards ----------

  function chips(r) {
    const out = [];
    const strict = r.strict || [];
    for (const [c, label] of Object.entries(CRITERIA)) {
      const w = r.weights[c];
      if (c === "laundry" && strict.includes("in_unit_laundry")) { out.push(["in-unit laundry", w]); continue; }
      if (c === "parking" && strict.includes("included_parking")) { out.push(["free parking", w]); continue; }
      if (w >= 4 || w === 0) out.push([w === 0 ? `${label}` : label, w]);  // Only what they feel strongly about.
    }
    for (const x of r.wants || []) out.push([x.kind === "near" ? `near ${x.what}` : x.what, x.weight, x.quote, true]);
    return out.map(([label, w, quote, asked]) =>
      `<span class="wish-chip ${w >= 5 ? "must" : w === 0 ? "dontcare" : ""}"${quote ? ` title="${h(`"${quote}"`)}"` : ""}>${h(label)} · ${level(w, asked)}</span>`).join("");
  }

  function status(p) {
    if (p.me) return '<span class="chip-status me">You</span>';
    if (p.line && p.connected) return '<span class="chip-status in">Texting</span>';
    if (p.line) return '<span class="chip-status waiting">Waiting for first text</span>';
    return '<span class="chip-status none">Added here</span>';
  }

  function card(p, i) {
    const r = p.roommate;
    const name = h(p.name);
    const placeholder = `Going to: ${h(group.place)} (or type another)`;
    const wishes = chips(r);
    const math = Object.keys(CRITERIA).map(c => `<tr><td>${CRITERIA[c]}</td><td class="num">${r.weights[c]}</td></tr>`).join("") +
      (r.wants || []).map(x => `<tr><td>${h(x.kind === "near" ? "near " + x.what : x.what)}</td><td class="num">${x.weight}</td></tr>`).join("");
    return `<div class="person" data-i="${i}">
      <div class="person-head">
        <span class="person-name">${name}</span>
        ${p.phone_last4 ? `<span class="digits">•••• ${h(p.phone_last4)}</span>` : ""}
        ${status(p)}
        <button class="remove" title="Remove ${name}" aria-label="Remove ${name}" data-act="remove">×</button>
      </div>
      <div class="person-facts">
        <label class="budget">up to $<input type="number" min="1" step="any" value="${r.budget}" data-act="budget" aria-label="${name}'s max rent per month"></label>
        <input type="text" class="person-place" value="${h(r.place || "")}" placeholder="${placeholder}" data-act="place" aria-label="Where ${name} needs to get to">
        <select data-act="mode" aria-label="How ${name} gets there">
          ${Object.entries(MODES).map(([m, w]) => `<option value="${m}"${r.travel_mode === m ? " selected" : ""}>${w[0].toUpperCase() + w.slice(1)}</option>`).join("")}
        </select>
      </div>
      ${wishes ? `<div class="wish-chips">${wishes}</div>` : `<div class="person-empty">${p.line && !p.connected
          ? `Nothing yet. They text ${h(prettyPhone(p.line))} to start. <a href="${h(p.text_link)}">Text link</a>`
          : "Nothing yet. Add what they want below."}</div>`}
      ${p.last_text ? `<div class="person-said">“${h(p.last_text)}”</div>` : ""}
      ${notes[p.name] ? `<div class="person-note">${notes[p.name]}</div>` : ""}
      <form class="person-ask" data-act="wishes">
        <input type="text" maxlength="600" placeholder="${p.me ? "Add more of what you want" : `What does ${name} want?`}" aria-label="What ${name} wants">
        <button class="secondary" type="submit">Add</button>
      </form>
      <details class="person-math"><summary>See the math</summary>
        <table><tr><th>What</th><th class="num">Weight (0–5)</th></tr>${math}</table>
        <div class="hint">Weights come from their words: must 5, important 4.5, wanted 4, neutral 3, nice to have 2, don't care 0.</div>
      </details>
    </div>`;
  }

  function renderGroup() {
    const box = el("roommates");
    if (!group) return;
    if (!group.people.length) {
      box.innerHTML = '<div class="empty">Nobody in the group yet. Start from the welcome screen, invite someone below, or load the demo group.</div>';
      return;
    }
    box.innerHTML = group.people.map(card).join("");
  }
  window.renderGroup = renderGroup;

  // Keep app.js's `roommates` in step with the group (it uses them for colors, rent per person and the pick).
  function adopt(view, { rerunPick = false } = {}) {
    const changed = !group || group.version !== view.version;
    group = view;
    roommates = view.people.map(p => p.roommate);
    window.groupInfo = { size: view.size, place: view.place };
    // Don't redraw the cards under someone typing in one; the next check (or leaving the box) catches up.
    if (!el("roommates").contains(document.activeElement) || !changed) renderGroup();
    else el("roommates").addEventListener("focusout", renderGroup, { once: true });
    if (changed) {
      renderLegend();
      drawListings();
      if (rerunPick && listings.length && roommates.length) runDecision();
    }
  }

  async function loadGroup(opts) {
    try { adopt(await api("GET", "/api/group"), opts); } catch { /* Server restarting: try again next time. */ }
  }
  window.loadGroup = loadGroup;

  // ---------- Card actions ----------

  function understoodNote(u) {
    if (!u) return "";
    const parts = [];
    if (u.cannot_check?.length) parts.push(`Can't check ${u.cannot_check.map(q => `"${h(q)}"`).join(", ")}: no listing or map shows that, so it isn't scored.`);
    if (u.not_understood?.length) parts.push(`Didn't catch ${u.not_understood.map(q => `"${h(q)}"`).join(", ")}.`);
    return parts.join(" ");
  }

  async function act(i, action, value, form) {
    const p = group.people[i];
    const url = `/api/group/people/${enc(p.name)}`;
    busy = true;
    try {
      if (action === "remove") adopt(await api("DELETE", url), { rerunPick: true });
      if (action === "budget") adopt(await api("PATCH", url, { budget: +value }), { rerunPick: true });
      if (action === "place") adopt(await api("PATCH", url, { place: value.trim() }), { rerunPick: true });
      if (action === "mode") adopt(await api("PATCH", url, { travel_mode: value }), { rerunPick: true });
      if (action === "wishes") {
        const input = form.querySelector("input");
        const text = input.value.trim();
        if (!text) return;
        form.querySelector("button").disabled = true;
        input.disabled = true;
        const res = await api("POST", `${url}/wishes`, { text });
        notes[p.name] = understoodNote(res.understood);
        adopt(res.group, { rerunPick: true });
      }
    } catch (e) {
      notes[p.name] = h(e.message);
      renderGroup();
    } finally {
      busy = false;
    }
  }

  el("roommates").addEventListener("change", e => {
    const t = e.target, cardEl = t.closest(".person");
    if (!cardEl || !t.dataset.act) return;
    act(+cardEl.dataset.i, t.dataset.act, t.value);
  });
  el("roommates").addEventListener("click", e => {
    const t = e.target.closest("[data-act=remove]");
    if (t) act(+t.closest(".person").dataset.i, "remove");
  });
  el("roommates").addEventListener("submit", e => {
    e.preventDefault();
    const form = e.target.closest("form[data-act=wishes]");
    if (form) act(+form.closest(".person").dataset.i, "wishes", null, form);
  });

  // ---------- Adding people ----------

  async function addWithoutPhone(e) {
    e.preventDefault();
    const s = el("addStatus");
    try {
      s.className = "status";
      s.innerHTML = '<span class="spinner"></span>Adding…';
      const res = await api("POST", "/api/group/people", { name: el("addName").value.trim(), text: el("addWants").value.trim() || null });
      const name = el("addName").value.trim();
      notes[name] = understoodNote(res.understood);
      el("addForm").reset();
      s.className = "status ok";
      s.textContent = `${name} is in the group.`;
      adopt(res.group, { rerunPick: true });
    } catch (err) {
      s.className = "status error";
      s.textContent = err.message;
    }
  }

  async function invite(e) {
    e.preventDefault();
    const btn = el("inviteBtn"), s = el("inviteStatus"), next = el("inviteNext");
    btn.disabled = true;
    s.className = "status";
    s.innerHTML = '<span class="spinner"></span>Adding them to the iMessage line…';
    next.hidden = true;
    try {
      const data = await api("POST", "/api/roommates/invite", {
        name: el("inviteName").value.trim(), phone: el("invitePhone").value.trim(),
        email: el("inviteEmail").value.trim() || null, budget: Number(el("inviteBudget").value) || null,
      });
      s.className = "status ok";
      s.textContent = `${data.name} is on the line.` + (data.email_invite ? " Photon also emailed them an invite." : "");
      next.innerHTML = `<b>Last step: ${h(data.name)} sends one text.</b> The bot can't text first, so ask them to text
        <div class="line-number">${h(prettyPhone(data.line))}</div>with this message (the button fills it in on a phone):
        <span class="starter">${h(data.starter_text)}</span>
        <div class="invite-actions"><a href="${h(data.text_link)}">Open in Messages</a>
          <button type="button" id="copyInvite">Copy number and message</button></div>`;
      next.hidden = false;
      el("copyInvite").onclick = async () => {
        try { await navigator.clipboard.writeText(`Text ${prettyPhone(data.line)}: "${data.starter_text}"`); el("copyInvite").textContent = "Copied"; }
        catch { el("copyInvite").textContent = "Select the text above to copy"; }
      };
      el("inviteForm").reset();
      loadGroup();
    } catch (err) {
      s.className = "status error";
      s.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  }

  async function loadDemo(e) {
    e.preventDefault();
    adopt(await api("POST", "/api/group/demo"));
    listings = await api("GET", "/api/group/listings");
    demoIds = new Set(listings.map(l => l.id));
    el("homeBase").value = "UCLA";
    await setHome("UCLA");
    runDecision();
  }

  async function startOver(e) {
    e.preventDefault();
    if (el("startOver").dataset.sure !== "yes") {  // Two clicks, no pop-up.
      el("startOver").dataset.sure = "yes";
      el("startOver").textContent = "Click again to remove everyone";
      setTimeout(() => { el("startOver").dataset.sure = ""; el("startOver").textContent = "Start over"; }, 4000);
      return;
    }
    adopt(await api("POST", "/api/group/reset"));
    listings = await api("GET", "/api/group/listings");
    demoIds = new Set(listings.map(l => l.id));
    lastDecision = null;
    showEmptyResult();
    drawListings();
    location.hash = "";  // Back to the welcome screen.
  }

  // The page's map listings, saved so the bot picks from the same places.
  window.saveListings = () => api("PUT", "/api/group/listings", { listings }).catch(() => {});

  el("addForm").addEventListener("submit", addWithoutPhone);
  el("inviteForm").addEventListener("submit", invite);
  el("loadDemo").addEventListener("click", loadDemo);
  el("startOver").addEventListener("click", startOver);

  loadGroup();
  // Someone texting the bot changes the group: pick that up and update the pick.
  setInterval(() => { if (!document.hidden && !busy) loadGroup({ rerunPick: !!lastDecision }); }, POLL_MS);
})();
