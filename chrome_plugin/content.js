(() => {
  const BTN_ID = "jm-action-btn";

  // ── Sidebar constants & state ────────────────────────────────────
  const SIDEBAR_ID            = "tally-sidebar-iframe";
  const SIDEBAR_CONTAINER_ID  = "tally-sidebar-container";
  const SIDEBAR_COLLAPSED_KEY = "tally-sidebar-collapsed";

  const sidebarState = {
    apiOnline:         null,
    totalVacancies:    null,
    totalCompanies:    null,
    parsedToday:       null,
    dailyCap:          null,
    autopilotRunning:  false,
    autopilotProgress: "",
  };

  function publishStateToSidebar() {
    const iframe = document.getElementById(SIDEBAR_ID);
    if (!iframe || !iframe.contentWindow) return;
    iframe.contentWindow.postMessage(
      { to: "tally-sidebar", type: "state", payload: { ...sidebarState } },
      "*"
    );
  }

  async function refreshDashboard() {
    const r = await apiGet("/api/dashboard");
    if (r.ok && r.data) {
      sidebarState.apiOnline      = true;
      sidebarState.totalVacancies = r.data.total_vacancies ?? null;
      sidebarState.totalCompanies = r.data.total_companies ?? null;
      sidebarState.parsedToday    = r.data.parsed_today    ?? null;
      sidebarState.dailyCap       = r.data.daily_cap       ?? null;
    } else {
      sidebarState.apiOnline      = false;
      sidebarState.totalVacancies = null;
      sidebarState.totalCompanies = null;
      sidebarState.parsedToday    = null;
      sidebarState.dailyCap       = null;
    }
    publishStateToSidebar();
  }

  function injectSidebar() {
    if (document.getElementById(SIDEBAR_CONTAINER_ID)) return;

    const container = document.createElement("div");
    container.id = SIDEBAR_CONTAINER_ID;

    const collapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
    if (collapsed) container.dataset.collapsed = "1";

    const iframe = document.createElement("iframe");
    iframe.id  = SIDEBAR_ID;
    iframe.src = chrome.runtime.getURL("sidebar.html");
    iframe.title = "Tally sidebar";

    const toggle = document.createElement("button");
    toggle.id = "tally-sidebar-toggle";
    toggle.textContent = collapsed ? "›" : "‹";
    toggle.setAttribute("aria-label", "Toggle Tally sidebar");
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.addEventListener("click", () => {
      const next = container.dataset.collapsed === "1" ? "0" : "1";
      if (next === "0") {
        delete container.dataset.collapsed;
        toggle.textContent = "‹";
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "0");
      } else {
        container.dataset.collapsed = "1";
        toggle.textContent = "›";
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "1");
      }
      toggle.setAttribute("aria-expanded", String(next !== "1"));
    });

    container.appendChild(toggle);
    container.appendChild(iframe);
    document.body.appendChild(container);
  }

  // ── Sidebar message handler ──────────────────────────────────────
  window.addEventListener("message", (event) => {
    const iframe = document.getElementById(SIDEBAR_ID);
    // Only accept messages from our own iframe's window
    if (!iframe || event.source !== iframe.contentWindow) return;
    const data = event.data;
    if (!data || data.from !== "tally-sidebar") return;
    if (data.type === "sidebar.ready") {
      refreshDashboard();
    } else if (data.type === "autopilot.toggle") {
      runAutopilot();
    } else if (data.type === "sidebar.close") {
      const container = document.getElementById(SIDEBAR_CONTAINER_ID);
      const toggle    = document.getElementById("tally-sidebar-toggle");
      if (container) {
        container.dataset.collapsed = "1";
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "1");
      }
      if (toggle) {
        toggle.textContent = "›";
        toggle.setAttribute("aria-expanded", "false");
      }
    }
  });

  let autopilotRunning = false;
  let autopilotAbort = false;
  let savedIds = new Set(); // job_ids already in vault

  // ── API proxy via background (avoids MV3 CORS quirks) ───────────

  function apiCall(method, path, body) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "api", method, path, body }, (res) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
        } else {
          resolve(res || { ok: false, error: "no response" });
        }
      });
    });
  }

  const apiGet = (path) => apiCall("GET", path);
  const apiPost = (path, body) => apiCall("POST", path, body);

  // ── helpers ──────────────────────────────────────────────────────

  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
  function randomDelay(lo, hi) { return sleep(lo + Math.random() * (hi - lo)); }

  function jobIdFromUrl(url) {
    const m = url.match(/\/jobs\/view\/(\d+)/);
    if (m) return m[1];
    const m2 = url.match(/currentJobId=(\d+)/);
    return m2 ? m2[1] : null;
  }

  function isJobViewPage() { return /\/jobs\/view\/\d+/.test(location.href); }
  function isJobListPage() {
    return /\/jobs\/collections\//.test(location.href) ||
           /\/jobs\/search/.test(location.href);
  }

  // ── parsed-ids sync ──────────────────────────────────────────────

  async function refreshSavedIds() {
    const r = await apiGet("/api/parsed-ids");
    if (r.ok && r.data && Array.isArray(r.data.ids)) {
      savedIds = new Set(r.data.ids);
    }
  }

  // ── "already saved" badge on list cards ──────────────────────────

  function markSavedCards() {
    if (!isJobListPage()) return;
    const cards = document.querySelectorAll(
      '[data-occludable-job-id], ' +
      '.job-card-container, ' +
      '.jobs-search-results__list-item, ' +
      'li.scaffold-layout__list-item'
    );
    for (const card of cards) {
      let id = card.dataset ? card.dataset.occludableJobId : null;
      if (!id) {
        const a = card.querySelector('a[href*="/jobs/view/"]');
        if (a) id = jobIdFromUrl(a.href);
      }
      if (!id) continue;

      const already = card.querySelector(".jm-saved-badge");
      if (savedIds.has(id)) {
        card.classList.add("jm-saved-card");
        if (!already) {
          const badge = document.createElement("span");
          badge.className = "jm-saved-badge";
          badge.title = "Already in your vault";
          badge.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg><span>Saved</span>';
          card.appendChild(badge);
        }
      } else {
        card.classList.remove("jm-saved-card");
        if (already) already.remove();
      }
    }
  }

  // ── DOM extraction (scoped to detail panel) ──────────────────────

  function getDetailPanel() {
    const selectors = [
      ".jobs-search__job-details",
      ".jobs-details",
      ".job-view-layout",
      ".scaffold-layout__detail",
      ".jobs-details__main-content",
      "main",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.innerText && el.innerText.length > 200) return el;
    }
    return document.body;
  }

  function getJobDescription(scope) {
    const root = scope || document;
    const selectors = [
      "#job-details",
      ".jobs-description__content",
      ".jobs-box__html-content",
      ".jobs-description-content__text",
      '[class*="description__text"]',
      "article",
    ];
    for (const sel of selectors) {
      const el = root.querySelector(sel);
      if (el && el.innerText.trim().length > 50) return el;
    }
    return null;
  }

  async function clickShowMore() {
    const selectors = [
      "button.jobs-description__footer-button",
      'button[aria-label="Show more"]',
      'button[aria-label*="more"]',
    ];
    for (const sel of selectors) {
      const btn = document.querySelector(sel);
      if (btn && btn.offsetParent !== null) {
        try { btn.click(); await sleep(1000); return true; }
        catch { continue; }
      }
    }
    return false;
  }

  function extractDescriptionFulltext(bodyText) {
    const startMarkers = ["About the job\n", "About the job\r\n"];
    let startIdx = 0;
    for (const m of startMarkers) {
      const i = bodyText.indexOf(m);
      if (i >= 0) { startIdx = i + m.length; break; }
    }
    if (startIdx === 0) {
      for (const m of ["Company Description\n", "Job Description\n"]) {
        const i = bodyText.indexOf(m);
        if (i >= 0) { startIdx = i; break; }
      }
    }
    const endMarkers = [
      "\nShow less", "\n\u2026 more", "\nSet alert",
      "\nAbout the company", "\nSimilar jobs",
      "\nPeople also viewed", "\nActivity on this job",
    ];
    let endIdx = bodyText.length;
    for (const m of endMarkers) {
      const i = bodyText.indexOf(m, startIdx);
      if (i >= 0 && i < endIdx) endIdx = i;
    }
    const desc = bodyText.slice(startIdx, endIdx).trim();
    return desc.length > 30 ? desc : "";
  }

  function parseTopCardFromBody(bodyText) {
    const dot = String.fromCharCode(183);
    const result = { location: "", reposted: "", applies: "", employment: "" };
    for (const line of bodyText.split("\n")) {
      if (line.includes(dot) && (line.includes("applicant") || line.includes("ago") || line.includes("clicked"))) {
        const ps = line.split(dot).map((p) => p.trim());
        result.location = ps[0] || "";
        for (const p of ps.slice(1)) {
          const pl = p.toLowerCase();
          if (pl.includes("reposted") || pl.includes("ago")) {
            result.reposted = p.replace(/^Reposted\s+/i, "");
          } else if (pl.includes("applicant") || pl.includes("clicked") || pl.includes("people")) {
            result.applies = p;
          }
        }
        break;
      }
    }
    for (const emp of ["Full-time", "Part-time", "Contract", "Internship", "Temporary", "Volunteer"]) {
      if (bodyText.includes(emp)) { result.employment = emp; break; }
    }
    if (!result.employment) result.employment = "Full-time";
    return result;
  }

  async function extractJob(url, jobId) {
    await clickShowMore();
    const panel = getDetailPanel();
    const pageTitle = document.title || "";

    const titleEl = panel.querySelector(
      '.job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, h1.t-24, h2.t-24'
    );
    let title;
    if (titleEl && titleEl.innerText.trim()) {
      title = titleEl.innerText.trim();
    } else {
      const parts = pageTitle.split(" | ").map((p) => p.trim());
      title = (parts[0] || "Unknown Role").replace(/^\(\d+\)\s*/, "");
      if (parts.length >= 3 && parts[parts.length - 1] === "LinkedIn") {
        title = parts.slice(0, -2).join(" | ");
      }
    }

    let compLink = panel.querySelector(
      '.job-details-jobs-unified-top-card__company-name a, ' +
      '.jobs-unified-top-card__company-name a, ' +
      'a[data-tracking-control-name="public_jobs_topcard-org-name"]'
    );
    if (!compLink) compLink = panel.querySelector('a[href*="/company/"]');
    const company = compLink ? compLink.innerText.trim() : "";
    const companyUrl = compLink ? compLink.href.split("?")[0] : "";

    const panelText = panel.innerText || "";
    const top = parseTopCardFromBody(panelText);

    const descEl = getJobDescription(panel);
    let descHtml = "", descText = "";
    if (descEl) {
      descHtml = descEl.innerHTML;
      descText = descEl.innerText.trim();
    }
    if (!descText || descText.length < 50) {
      const fallback = extractDescriptionFulltext(panelText);
      if (fallback) { descText = fallback; descHtml = ""; }
    }

    return {
      url, job_id: jobId, title, company, company_url: companyUrl,
      location: top.location, employment: top.employment,
      applies: top.applies, reposted: top.reposted,
      description_html: descHtml, description_text: descText,
    };
  }

  // ── Save single job ──────────────────────────────────────────────

  async function saveCurrentJob() {
    const url = location.href;
    const jobId = jobIdFromUrl(url);
    if (!jobId) { updateBtn("No job ID", "error"); return; }

    // Skip if we already have it
    if (savedIds.has(jobId)) {
      updateBtn("Already saved", "exists");
      setTimeout(renderActionButton, 3000);
      return;
    }

    updateBtn("Extracting...", "working");
    const data = await extractJob(url, jobId);
    updateBtn("Saving...", "working");
    const r = await apiPost("/api/parse", data);
    if (!r.ok) { updateBtn("API offline", "error"); setTimeout(renderActionButton, 4000); return; }
    const res = r.data;
    if (res.status === "saved") {
      savedIds.add(jobId);
      updateBtn(`Saved (${res.parsed_today}/${res.parsed_today + res.remaining_today})`, "success");
    } else if (res.status === "exists") {
      savedIds.add(jobId);
      updateBtn("Already saved", "exists");
    } else if (res.error === "daily_cap") {
      updateBtn("Daily cap reached", "error");
    } else {
      updateBtn("Error: " + (res.error || "unknown"), "error");
    }
    setTimeout(renderActionButton, 4000);
  }

  // ── Autopilot (skips already-saved cards) ────────────────────────

  function getJobCards() {
    const seen = new Set();
    const result = [];
    const candidates = document.querySelectorAll(
      '[data-occludable-job-id], ' +
      'a.job-card-container__link, a.job-card-list__title, ' +
      '.scaffold-layout__list a[href*="/jobs/view/"]'
    );
    for (const el of candidates) {
      let id = el.dataset && el.dataset.occludableJobId;
      let href = null;
      if (id) {
        const inner = el.querySelector('a[href*="/jobs/view/"]');
        href = inner ? inner.href : `https://www.linkedin.com/jobs/view/${id}/`;
      } else if (el.href) {
        id = jobIdFromUrl(el.href);
        href = el.href;
      }
      if (id && !seen.has(id)) {
        seen.add(id);
        result.push({ id, href, el });
      }
    }
    return result;
  }

  function getScrollContainer() {
    for (const sel of [
      '.scaffold-layout__list .jobs-search-results-list',
      '.scaffold-layout__list > div',
      '.scaffold-layout__list',
      '.jobs-search-results-list',
    ]) {
      const el = document.querySelector(sel);
      if (el && el.scrollHeight > el.clientHeight) return el;
    }
    return null;
  }

  function getClickableForId(id) {
    return document.querySelector(
      `a[href*="/jobs/view/${id}"], a[href*="currentJobId=${id}"], ` +
      `[data-occludable-job-id="${id}"] a[href*="/jobs/view/"]`
    );
  }

  function urlWithStart(n) {
    const u = new URL(location.href);
    u.searchParams.set("start", String(n));
    return u.toString();
  }

  async function processCurrentPage(stats) {
    // Scroll to load all cards
    let prev = 0;
    for (let i = 0; i < 20; i++) {
      if (autopilotAbort) return;
      const c = getScrollContainer();
      if (c) c.scrollBy(0, 600);
      await sleep(1500);
      markSavedCards(); // refresh badges as we scroll
      const n = getJobCards().length;
      updateBtn(`Loading... (${n} cards)`, "working");
      if (n === prev) break;
      prev = n;
    }

    const allCards = getJobCards();
    const pending = allCards.filter((c) => !savedIds.has(c.id));
    stats.seenOnPage = allCards.length;
    stats.skippedAlreadyOnPage = allCards.length - pending.length;
    updateBtn(
      `p.${stats.page}: ${allCards.length} cards, ${pending.length} new`,
      "working"
    );
    await sleep(800);

    for (let i = 0; i < pending.length; i++) {
      if (autopilotAbort) return;
      const card = pending[i];

      updateBtn(
        `[${i + 1}/${pending.length}] p.${stats.page} (saved ${stats.saved})`,
        "working"
      );

      try {
        const clickEl = getClickableForId(card.id) || card.el;
        clickEl.scrollIntoView({ behavior: "smooth", block: "center" });
        await sleep(500);
        clickEl.click();
        await randomDelay(2500, 5000);
        if (autopilotAbort) return;

        const data = await extractJob(card.href, card.id);
        if (!data.description_text && !data.description_html) {
          stats.failed++;
          continue;
        }

        const r = await apiPost("/api/parse", data);
        if (!r.ok) { stats.failed++; continue; }
        const res = r.data;
        if (res.status === "saved") {
          stats.saved++;
          savedIds.add(card.id);
          markSavedCards();
        } else if (res.status === "exists") {
          stats.skipped++;
          savedIds.add(card.id);
          markSavedCards();
        } else if (res.error === "daily_cap") {
          stats.capReached = true;
          return;
        } else {
          stats.failed++;
        }
      } catch { stats.failed++; }

      await randomDelay(8000, 20000);
    }
  }

  async function runAutopilot() {
    if (autopilotRunning) {
      autopilotAbort = true;
      updateBtn("Stopping...", "working");
      return;
    }
    autopilotRunning = true;
    autopilotAbort = false;

    await refreshSavedIds();
    markSavedCards();

    const pageSize = /\/jobs\/search/.test(location.href) ? 25 : 24;
    const startUrl = new URL(location.href);
    let start = parseInt(startUrl.searchParams.get("start") || "0");

    const stats = {
      saved: 0, skipped: 0, failed: 0, page: 1,
      seenOnPage: 0, skippedAlreadyOnPage: 0,
      capReached: false,
    };
    let consecutiveEmpty = 0;

    while (!autopilotAbort) {
      await processCurrentPage(stats);
      if (stats.capReached) { updateBtn(`Cap! ${stats.saved} saved`, "error"); break; }
      if (autopilotAbort) break;

      // Two consecutive pages where nothing new was saved → stop
      const addedOnThisPage = stats.saved + stats.skipped;
      if (addedOnThisPage === 0) {
        consecutiveEmpty++;
        if (consecutiveEmpty >= 2) {
          updateBtn(`Done: 2 empty pages → stop`, "success");
          break;
        }
      } else {
        consecutiveEmpty = 0;
      }

      start += pageSize;
      stats.page++;
      const nextUrl = urlWithStart(start);
      updateBtn(`Next page: start=${start}`, "working");
      await randomDelay(4000, 9000);
      if (autopilotAbort) break;

      try {
        window.history.pushState({}, "", nextUrl);
        window.dispatchEvent(new PopStateEvent("popstate"));
      } catch {
        location.href = nextUrl;
        return;
      }
      await sleep(3000);
    }

    updateBtn(
      `Done p.${stats.page}: ${stats.saved} saved, ${stats.skipped} skip, ${stats.failed} fail`,
      "success"
    );
    autopilotRunning = false;
    autopilotAbort = false;
    setTimeout(renderActionButton, 10000);
  }

  // ── floating action button ───────────────────────────────────────

  function updateBtn(text, state) {
    const btn = document.getElementById(BTN_ID);
    if (!btn) return;
    const t = btn.querySelector(".jm-btn-text");
    if (t) t.textContent = text;
    btn.className = `jm-action-btn jm-${state}`;
    sidebarState.autopilotProgress = text;
    sidebarState.autopilotRunning  = autopilotRunning;
    publishStateToSidebar();
  }

  function renderActionButton() {
    let btn = document.getElementById(BTN_ID);
    if (!btn) {
      btn = document.createElement("div");
      btn.id = BTN_ID;
      document.body.appendChild(btn);
    }

    if (isJobViewPage()) {
      const jid = jobIdFromUrl(location.href);
      const already = jid && savedIds.has(jid);
      btn.className = `jm-action-btn ${already ? "jm-exists" : "jm-ready"}`;
      btn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          ${already
            ? '<polyline points="20 6 9 17 4 12"/>'
            : '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>'}
        </svg>
        <span class="jm-btn-text">${already ? "Already in vault" : "Save to vault"}</span>`;
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

  // ── init / observer ─────────────────────────────────────────────

  async function onPageUpdate() {
    await refreshSavedIds();
    markSavedCards();
    renderActionButton();
  }

  const observer = new MutationObserver(() => {
    clearTimeout(observer._timer);
    observer._timer = setTimeout(() => {
      markSavedCards();
      renderActionButton();
      if (/\/jobs\//.test(location.href)) injectSidebar();
    }, 1200);
  });

  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(() => {
    onPageUpdate();
    if (/\/jobs\//.test(location.href)) injectSidebar();
  }, 2000);
  // Re-sync periodically in case the vault changes server-side
  setInterval(refreshSavedIds, 60000);
  setInterval(refreshDashboard, 60000);
})();
