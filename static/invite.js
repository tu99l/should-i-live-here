// "Invite by text": add a roommate's phone to the iMessage bot (app/photon_bot.py) from the page.
// Our free shared line can't text first, so the roommate sends one pre-filled text and the bot
// replies with a hello. The group list below polls the backend to show who has texted in and
// what they asked for. Kept separate from app.js so the map code stays untouched.
(function () {
  const POLL_MS = 4000;
  const h = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const el = id => document.getElementById(id);
  let lastGroup = "";

  // "+16283166196" -> "+1 (628) 316-6196"; other countries are shown as given.
  function prettyPhone(p) {
    const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(p || "");
    return m ? `+1 (${m[1]}) ${m[2]}-${m[3]}` : (p || "");
  }

  function weightWord(w) {
    // Same words as the bot's replies (LEVEL_NAMES in app/wishes.py).
    if (w >= 5) return "must";
    if (w >= 4.5) return "important";
    if (w >= 3) return "wanted";
    if (w > 0) return "nice to have";
    return "don't care";
  }

  function wishLabel(w) {
    return w.kind === "near" ? `near ${w.what}` : w.what;
  }

  async function invite(event) {
    event.preventDefault();
    const btn = el("inviteBtn"), status = el("inviteStatus"), next = el("inviteNext");
    const body = {
      name: el("inviteName").value.trim(),
      phone: el("invitePhone").value.trim(),
      email: el("inviteEmail").value.trim() || null,
      budget: Number(el("inviteBudget").value) || null,
    };
    btn.disabled = true;
    status.className = "status";
    status.innerHTML = '<span class="spinner"></span>Adding them to the iMessage line…';
    next.hidden = true;
    try {
      const r = await fetch("/api/roommates/invite", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Could not add them.");
      status.className = "status ok";
      status.textContent = `${data.name} is on the line.` +
        (data.email_invite ? " Photon also emailed them an invite." : "");
      showNext(data);
      el("inviteForm").reset();
      refreshGroup();
    } catch (e) {
      status.className = "status error";
      status.textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  }

  function showNext(data) {
    const next = el("inviteNext");
    next.innerHTML = `
      <b>Last step: ${h(data.name)} sends one text.</b> The bot can't text first, so ask them to text
      <div class="line-number">${h(prettyPhone(data.line))}</div>
      with this message (the button fills it in on a phone):
      <span class="starter">${h(data.starter_text)}</span>
      <div class="invite-actions">
        <a href="${h(data.text_link)}">Open in Messages</a>
        <button type="button" id="copyInvite">Copy number and message</button>
      </div>`;
    next.hidden = false;
    el("copyInvite").onclick = async () => {
      const text = `Text ${prettyPhone(data.line)}: "${data.starter_text}"`;
      try {
        await navigator.clipboard.writeText(text);
        el("copyInvite").textContent = "Copied";
      } catch {
        el("copyInvite").textContent = "Select the text above to copy";
      }
    };
  }

  function renderGroup(group) {
    const list = el("groupList");
    if (!group.length) {
      list.innerHTML = '<div class="empty">Nobody added yet. Add a roommate above and they can text their wishes in.</div>';
      return;
    }
    list.innerHTML = group.map(r => {
      const status = !r.line ? '<span class="chip-status none">Not added</span>'
        : r.connected ? '<span class="chip-status in">Texting</span>'
        : '<span class="chip-status waiting">Waiting for first text</span>';
      const wishes = (r.wants || []).map(w =>
        `<span class="wish-chip ${w.weight >= 5 ? "must" : ""}" title="${h(w.quote || "")}">${h(wishLabel(w))} · ${weightWord(w.weight)}</span>`).join("");
      const resend = r.line && !r.connected ? `<a class="resend" href="${h(r.text_link)}">Text link for ${h(r.name)}</a>` : "";
      return `<div class="group-row">
        <div class="group-row-head">
          <span class="who">${h(r.name)}</span>
          ${r.phone_last4 ? `<span class="digits">•••• ${h(r.phone_last4)}</span>` : ""}
          ${status}
        </div>
        ${wishes ? `<div class="wish-chips">${wishes}</div>` : ""}
        ${resend}
      </div>`;
    }).join("");
  }

  async function refreshGroup() {
    try {
      const r = await fetch("/api/roommates");
      if (!r.ok) return;
      const group = await r.json();
      const key = JSON.stringify(group);
      if (key !== lastGroup) {  // Only redraw when something changed, so nothing flickers.
        lastGroup = key;
        renderGroup(group);
      }
    } catch { /* Offline or server restarting: keep what is shown. */ }
  }

  el("inviteForm").addEventListener("submit", invite);
  refreshGroup();
  setInterval(() => { if (!document.hidden) refreshGroup(); }, POLL_MS);
})();
