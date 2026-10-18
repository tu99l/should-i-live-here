// Welcome screen: "What are you looking for?" in your own words -> the map with real listings and the fair pick.
// 1. You, your words, where the group goes and how many of you go to POST /api/group/me. The backend reads
//    the words (Gemini sorts them, our code checks every quote) and saves you as the first card of the group.
// 2. Real listings near the place come from the search (search.js, RentCast), then the fair pick runs.
// Roommates join later: invited by text, or added by hand in "Your group" (group.js).
(function () {
  const el = id => document.getElementById(id);
  const h = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function say(text) {
    el("welcomeStatus").innerHTML = '<span class="spinner"></span>' + h(text);
  }

  function problem(text) {
    el("welcomeStatus").innerHTML = `<span class="welcome-error">${h(text)}</span>`;
  }

  async function start(event) {
    event.preventDefault();
    const btn = el("welcomeStart");
    const place = el("welcomePlace").value.trim() || "UCLA";
    const body = {
      name: el("welcomeName").value.trim() || "You",
      text: el("welcomeWants").value.trim() || null,
      place,
      size: +el("welcomePeople").value || 1,
    };
    btn.disabled = true;
    try {
      say(body.text ? "Reading what you want…" : "Setting up your group…");
      const r = await fetch("/api/group/me", { method: "POST", headers: { "Content-Type": "application/json" },
                                              body: JSON.stringify(body) });
      const data = await r.json();
      if (!r.ok) { problem(data.detail || "Couldn't save that. Try again."); return; }
      await window.loadGroup();

      el("homeBase").value = place;
      say(`Finding ${place} on the map…`);
      await setHome(place);

      say(`Looking for real rentals near ${place}…`);
      await window.findListings();
      el("welcomeStatus").textContent = "";
      enterApp();
      if (listings.length && roommates.length) setTimeout(runDecision, 400);
    } catch {
      problem("Couldn't reach the server. Is it still running?");
    } finally {
      btn.disabled = false;
    }
  }

  el("welcomeForm").addEventListener("submit", start);
  el("welcomeSkip").addEventListener("click", e => { e.preventDefault(); enterApp(); });
})();
