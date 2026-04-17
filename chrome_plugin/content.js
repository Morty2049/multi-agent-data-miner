(() => {
  const API = "http://127.0.0.1:8000";
  const PANEL_ID = "jm-skill-panel";
  const BTN_ID = "jm-action-btn";
  let detected = [];
  let autopilotRunning = false;
  let autopilotAbort = false;

  // ── helpers ──────────────────────────────────────────────────────

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function randomDelay(lo, hi) {
    return sleep(lo + Math.random() * (hi - lo));
  }

  function jobIdFromUrl(url) {
    const m = url.match(/\/jobs\/view\/(\d+)/);
    if (m) return m[1];
    const m2 = url.match(/currentJobId=(\d+)/);
    return m2 ? m2[1] : null;
  }

  function isJobViewPage() {
    return /\/jobs\/view\/\d+/.test(location.href);
  }

  function isJobListPage() {
    return (
      /\/jobs\/collections\//.test(location.href) ||
      /\/jobs\/search\//.test(location.href)
    );
  }

  // ── skill detection (original feature) ───────────────────────────

  function getJobDescription() {
    const selectors = [
      ".jobs-description__content",
      ".jobs-box__html-content",
      ".jobs-description-content__text",
      '[class*="description__text"]',
      "#job-details",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.innerText.trim().length > 50) return el;
    }
    return null;
  }

  function createPanel() {
    let panel = document.getElementById(PANEL_ID);
    if (panel) return panel;
    panel = document.createElement("div");
    panel.id = PANEL_ID;
    document.body.appendChild(panel);
    return panel;
  }

  function renderPanel(skills) {
    const panel = createPanel();
    if (!skills.length) {
      panel.style.display = "none";
      return;
    }
    const sorted = [...skills].sort((a, b) => b.mentions - a.mentions);
    panel.innerHTML = `
      <div class="jm-header">
        <span class="jm-logo">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
          </svg>
          Job Miner
        </span>
        <span class="jm-count">${skills.length} skills</span>
        <button class="jm-close" id="jm-close">&times;</button>
      </div>
      <div class="jm-skills">
        ${sorted.map((s) => `
          <div class="jm-skill" title="${s.about || ""}">
            <span class="jm-skill-name">${s.name}</span>
            <span class="jm-skill-jobs">${s.mentions} jobs</span>
          </div>`).join("")}
      </div>`;
    panel.style.display = "block";
    document.getElementById("jm-close").addEventListener("click", () => {
      panel.style.display = "none";
    });
  }

  function highlightSkills(descEl, skills) {
    if (!descEl || !skills.length) return;
    const names = skills.map((s) => s.name).sort((a, b) => b.length - a.length);
    const walker = document.createTreeWalker(descEl, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const textNode of nodes) {
      let html = textNode.textContent;
      let changed = false;
      for (const name of names) {
        const esc = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const re = new RegExp(`\\b(${esc})\\b`, "gi");
        if (re.test(html)) {
          html = html.replace(re, '<span class="jm-highlight" title="Tracked skill">$1</span>');
          changed = true;
        }
      }
      if (changed) {
        const span = document.createElement("span");
        span.innerHTML = html;
        textNode.parentNode.replaceChild(span, textNode);
      }
    }
  }

  async function scanSkills() {
    const descEl = getJobDescription();
    if (!descEl) return;
    const text = descEl.innerText;
    if (text.length < 30) return;
    try {
      const r = await fetch(`${API}/api/detect?text=${encodeURIComponent(text.slice(0, 5000))}`);
      if (!r.ok) return;
      const data = await r.json();
      detected = data.detected || [];
      renderPanel(detected);
      highlightSkills(descEl, detected);
    } catch { /* API offline */ }
  }

  // ── extract current job from DOM ─────────────────────────────────

  function extractCurrentJob() {
    const url = location.href;
    const jobId = jobIdFromUrl(url);
    if (!jobId) return null;

    const pageTitle = document.title || "";
    const parts = pageTitle.split(" | ").map((p) => p.trim());
    let title = parts[0] || "Unknown Role";
    title = title.replace(/^\(\d+\)\s*/, "");
    if (parts.length >= 3 && parts[parts.length - 1] === "LinkedIn") {
      title = parts.slice(0, -2).join(" | ");
    }

    const compLink = document.querySelector('a[href*="/company/"]');
    const company = compLink ? compLink.innerText.trim() : "";
    const companyUrl = compLink ? compLink.href.split("?")[0] : "";

    let location_ = "", reposted = "", applies = "", employment = "Full-time";
    const dot = String.fromCharCode(183);
    const bodyText = document.body.innerText;
    for (const line of bodyText.split("\n")) {
      if (line.includes(dot) && (line.includes("applicant") || line.includes("ago") || line.includes("clicked"))) {
        const ps = line.split(dot).map((p) => p.trim());
        location_ = ps[0] || "";
        for (const p of ps.slice(1)) {
          const pl = p.toLowerCase();
          if (pl.includes("reposted") || pl.includes("ago")) reposted = p.replace("Reposted ", "");
          else if (pl.includes("applicant") || pl.includes("clicked") || pl.includes("people")) applies = p;
        }
        break;
      }
    }
    for (const emp of ["Full-time", "Part-time", "Contract", "Internship", "Temporary"]) {
      if (bodyText.includes(emp)) { employment = emp; break; }
    }

    const descEl = getJobDescription();

    return {
      url, job_id: jobId, title, company, company_url: companyUrl,
      location: location_, employment, applies, reposted,
      description_html: descEl ? descEl.innerHTML : "",
      description_text: descEl ? descEl.innerText.trim() : "",
    };
  }

  // ── save single job ──────────────────────────────────────────────

  async function saveCurrentJob() {
    const data = extractCurrentJob();
    if (!data) { updateBtn("No job ID", "error"); return; }
    updateBtn("Saving...", "working");
    try {
      const r = await fetch(`${API}/api/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const res = await r.json();
      if (res.status === "saved") updateBtn(`Saved (${res.parsed_today}/${res.parsed_today + res.remaining_today})`, "success");
      else if (res.status === "exists") updateBtn("Already saved", "exists");
      else if (res.error === "daily_cap") updateBtn("Daily cap reached", "error");
      else updateBtn("Error: " + (res.error || "unknown"), "error");
    } catch { updateBtn("API offline", "error"); }
    setTimeout(renderActionButton, 4000);
  }

  // ── autopilot: scroll list, click cards, parse each ──────────────

  async function runAutopilot() {
    if (autopilotRunning) {
      autopilotAbort = true;
      updateBtn("Stopping...", "working");
      return;
    }
    autopilotRunning = true;
    autopilotAbort = false;
    let saved = 0, skipped = 0, failed = 0;

    const getCards = () => {
      const links = document.querySelectorAll(
        '.scaffold-layout__list a[href*="/jobs/view/"], ' +
        '.jobs-search-results-list a[href*="/jobs/view/"], ' +
        'a.job-card-container__link, a.job-card-list__title'
      );
      const seen = new Set();
      const result = [];
      for (const a of links) {
        const id = jobIdFromUrl(a.href);
        if (id && !seen.has(id)) { seen.add(id); result.push({ el: a, id, href: a.href }); }
      }
      return result;
    };

    const scrollList = () => {
      for (const sel of [
        '.scaffold-layout__list .jobs-search-results-list',
        '.scaffold-layout__list > div',
        '.scaffold-layout__list',
      ]) {
        const el = document.querySelector(sel);
        if (el && el.scrollHeight > el.clientHeight) { el.scrollBy(0, 600); return true; }
      }
      return false;
    };

    updateBtn("Loading cards...", "working");

    // Scroll to load all visible cards
    let prevCount = 0;
    for (let i = 0; i < 20; i++) {
      scrollList();
      await sleep(1500);
      const cards = getCards();
      updateBtn(`Loading... (${cards.length} cards)`, "working");
      if (cards.length === prevCount) break;
      prevCount = cards.length;
      if (autopilotAbort) break;
    }

    const allCards = getCards();
    updateBtn(`${allCards.length} jobs found`, "working");
    await sleep(1000);

    for (let i = 0; i < allCards.length; i++) {
      if (autopilotAbort) break;
      const card = allCards[i];
      updateBtn(`[${i + 1}/${allCards.length}] Parsing... (${saved} saved)`, "working");

      try {
        card.el.scrollIntoView({ behavior: "smooth", block: "center" });
        await sleep(500);
        card.el.click();
        await randomDelay(2500, 5000);

        // Extract from the now-loaded detail panel
        const descEl = getJobDescription();
        if (!descEl) { failed++; continue; }

        const titleEl = document.querySelector(
          '.job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, h1.t-24, h2.t-24'
        );
        const title = titleEl ? titleEl.innerText.trim() : "Unknown Role";

        const compLink = document.querySelector('a[href*="/company/"]');
        const company = compLink ? compLink.innerText.trim() : "";
        const companyUrl = compLink ? compLink.href.split("?")[0] : "";

        let location_ = "";
        const topCardEl = document.querySelector(
          '.job-details-jobs-unified-top-card__primary-description-container, ' +
          '.jobs-unified-top-card__subtitle-primary-grouping'
        );
        if (topCardEl) {
          const dot = String.fromCharCode(183);
          const topText = topCardEl.innerText;
          if (topText.includes(dot)) location_ = topText.split(dot)[0].trim();
        }

        const data = {
          url: card.href, job_id: card.id, title, company, company_url: companyUrl,
          location: location_, employment: "Full-time", applies: "", reposted: "",
          description_html: descEl.innerHTML, description_text: descEl.innerText.trim(),
        };

        const r = await fetch(`${API}/api/parse`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
        const res = await r.json();
        if (res.status === "saved") saved++;
        else if (res.status === "exists") skipped++;
        else if (res.error === "daily_cap") { updateBtn(`Cap! ${saved} saved`, "error"); break; }
        else failed++;
      } catch { failed++; }

      await randomDelay(3000, 8000);
    }

    autopilotRunning = false;
    autopilotAbort = false;
    updateBtn(`Done: ${saved} saved, ${skipped} skip, ${failed} fail`, "success");
    setTimeout(renderActionButton, 8000);
  }

  // ── floating action button ───────────────────────────────────────

  function updateBtn(text, state) {
    const btn = document.getElementById(BTN_ID);
    if (!btn) return;
    btn.querySelector(".jm-btn-text").textContent = text;
    btn.className = `jm-action-btn jm-${state}`;
  }

  function renderActionButton() {
    let btn = document.getElementById(BTN_ID);
    if (!btn) {
      btn = document.createElement("div");
      btn.id = BTN_ID;
      document.body.appendChild(btn);
    }

    if (isJobViewPage()) {
      btn.className = "jm-action-btn jm-ready";
      btn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
        </svg>
        <span class="jm-btn-text">Save to vault</span>`;
      btn.onclick = saveCurrentJob;
    } else if (isJobListPage()) {
      btn.className = `jm-action-btn ${autopilotRunning ? "jm-working" : "jm-ready"}`;
      btn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          ${autopilotRunning
            ? '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>'
            : '<polygon points="5 3 19 12 5 21 5 3"/>'}
        </svg>
        <span class="jm-btn-text">${autopilotRunning ? "Stop" : "Autopilot"}</span>`;
      btn.onclick = runAutopilot;
    } else {
      btn.style.display = "none";
      return;
    }
    btn.style.display = "flex";
  }

  // ── init ─────────────────────────────────────────────────────────

  const observer = new MutationObserver(() => {
    clearTimeout(observer._timer);
    observer._timer = setTimeout(() => {
      scanSkills();
      renderActionButton();
    }, 1500);
  });

  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(() => { scanSkills(); renderActionButton(); }, 2000);
})();
