(() => {
  const BTN_ID = "jm-action-btn";

  // ── Debug capture (toggle off for production) ───────────────────
  // Records every URL change, page-mode classification, link click,
  // and company-DOM probe to data/debug-log.jsonl via POST /api/debug/log.
  // Used to diagnose which LinkedIn paths Tally misses. NEVER captures
  // cookies, auth tokens, page text, or anything LinkedIn would consider
  // a privacy concern — only public URL + selector hit/miss + element
  // text snippets that the user could copy themselves.
  const DEBUG_CAPTURE = true;
  let _lastLoggedUrl = null;

  function debugLog(event, extra) {
    if (!DEBUG_CAPTURE) return;
    try {
      // Use apiCall directly — apiPost is a const arrow defined later,
      // so it'd be in TDZ if debugLog fires from a top-level listener.
      apiCall("POST", "/api/debug/log", {
        event,
        url: location.href,
        path: location.pathname + location.search,
        ...(extra || {}),
      });
    } catch (e) { /* never break the page on a debug write */ }
  }

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
    // Per-page context for the sidebar. `pageMode` is "list" | "view" |
    // "other"; `currentJob` is {jobId, title, saved} on view pages and
    // null otherwise; `saveStatus` is {label, state, working} during and
    // after a manual Save ("Save to vault" in the sidebar's Current
    // Vacancy section).
    pageMode:          "other",
    currentJob:        null,
    saveStatus:        null,
    // Full settings object (mode, daily_cap, randomize_delays, delays_ms)
    // as returned by GET /api/settings. Populated lazily on first
    // sidebar.ready and refreshed after each save/preset apply so the
    // settings panel always renders the latest server truth.
    settings:          null,
    // Events for the vacancy currently open at location.href (empty
    // list on non-view pages). Refetched from /api/events whenever the
    // user opens a different vacancy or adds / removes a timeline event.
    timeline:          [],
    // On /company/<slug> pages, the canonical name extracted from the
    // DOM plus an aggregated per-vacancy summary of every touch at this
    // company (from /api/company-history).
    currentCompany:    null,  // { slug, name }
    companyHistory:    [],    // [{ job_id, title, status, last_at, event_count }]
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

  // Page context = what the sidebar should show. On /jobs/view/<id> we
  // surface a "Current Vacancy" + Timeline section; on list pages we
  // surface Autopilot; on /company/<slug> we surface Company History;
  // elsewhere everything is hidden.
  function getPageMode() {
    if (isJobViewPage()) return "view";
    if (isJobListPage()) return "list";
    if (isCompanyPage()) return "company";
    return "other";
  }

  function currentCompanyInfo() {
    const m = location.href.match(/\/company\/([^/?#]+)/);
    const slug = m ? m[1] : null;
    if (!slug) return null;
    // LinkedIn renders the company name in the org top-card h1.
    // Probe a list of selectors and report what we found so the debug
    // log can guide future selector additions.
    const selectors = [
      "h1.org-top-card-summary__title",
      ".org-top-card-summary h1",
      ".org-top-card__primary-content h1",
      "main h1",
    ];
    const probes = [];
    let name = "";
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      const hit = !!(el && el.innerText && el.innerText.trim());
      probes.push({ sel, hit, sample: hit ? el.innerText.trim().slice(0, 80) : null });
      if (hit && !name) name = el.innerText.trim();
    }
    let usedFallback = false;
    if (!name) {
      const parts = (document.title || "").split(" | ").map((p) => p.trim());
      name = parts[0] || slug;
      usedFallback = true;
    }
    // Strip LinkedIn's "verified" badge text that sometimes leaks in
    name = name.replace(/\s*\(verified\)\s*$/i, "").trim();
    debugLog("company_dom_probe", {
      slug,
      probes,
      finalName: name,
      usedTitleFallback: usedFallback,
    });
    return { slug, name };
  }

  function currentJobInfo() {
    const jobId = jobIdFromUrl(location.href);
    if (!jobId) return null;
    const panel = getDetailPanel();
    const titleEl = panel.querySelector(
      '.job-details-jobs-unified-top-card__job-title, ' +
      '.jobs-unified-top-card__job-title, h1.t-24, h2.t-24'
    );
    let title = titleEl && titleEl.innerText ? titleEl.innerText.trim() : "";
    if (!title) {
      const parts = (document.title || "").split(" | ").map((p) => p.trim());
      title = (parts[0] || "Unknown role").replace(/^\(\d+\)\s*/, "");
    }
    return { jobId, title, saved: savedIds.has(jobId) };
  }

  function publishPageContext() {
    const mode = getPageMode();
    if (location.href !== _lastLoggedUrl) {
      debugLog("url_change", { mode, prev: _lastLoggedUrl });
      _lastLoggedUrl = location.href;
    }
    sidebarState.pageMode = mode;
    // Current job is visible whenever the URL points at *some* vacancy —
    // either a dedicated /jobs/view/<id> page OR a list page with a
    // ?currentJobId selected. In LinkedIn's actual workflow the latter
    // is the common case (user clicks cards in /jobs/search; URL keeps
    // its list path, only currentJobId changes). Don't gate Current
    // Vacancy + Timeline behind pageMode === "view" — derive from URL.
    const job = jobIdFromUrl(location.href) ? currentJobInfo() : null;
    sidebarState.currentJob     = job;
    sidebarState.currentCompany = mode === "company" ? currentCompanyInfo() : null;
    if (!job)               sidebarState.timeline       = [];
    if (mode !== "company") sidebarState.companyHistory = [];
    publishStateToSidebar();
    // Fire-and-forget data refreshes; each helper publishes state again
    // when its fetch completes.
    if (job && job.jobId) refreshTimeline(job.jobId);
    if (mode === "company") {
      const name = sidebarState.currentCompany && sidebarState.currentCompany.name;
      if (name) refreshCompanyHistory(name);
    }
  }

  async function refreshTimeline(jobId) {
    const r = await apiGet(`/api/events?job_id=${encodeURIComponent(jobId)}`);
    // Guard against the user having navigated away while the request was in flight
    const current = sidebarState.currentJob;
    if (!current || current.jobId !== jobId) return;
    sidebarState.timeline = (r.ok && r.data && Array.isArray(r.data.events)) ? r.data.events : [];
    publishStateToSidebar();
  }

  async function refreshCompanyHistory(companyName) {
    const r = await apiGet(`/api/company-history?company=${encodeURIComponent(companyName)}`);
    const current = sidebarState.currentCompany;
    if (!current || current.name !== companyName) return;  // navigated away
    sidebarState.companyHistory = (r.ok && r.data && Array.isArray(r.data.items)) ? r.data.items : [];
    publishStateToSidebar();
  }

  function setSaveStatus(status) {
    sidebarState.saveStatus = status;
    publishStateToSidebar();
  }

  // ── Settings wiring ─────────────────────────────────────────────
  // Sidebar's gear panel reflects whatever GET /api/settings returns.
  // User actions post {settings.save|settings.preset} messages; we
  // hit the API, update state, and echo {settings.result} back so the
  // panel can show "Saved ✓" or an error.

  async function refreshSettings() {
    const r = await apiGet("/api/settings");
    if (r.ok && r.data) {
      sidebarState.settings = r.data;
      publishStateToSidebar();
    }
  }

  function postSettingsResult(ok, error) {
    const iframe = document.getElementById(SIDEBAR_ID);
    if (!iframe || !iframe.contentWindow) return;
    iframe.contentWindow.postMessage(
      { to: "tally-sidebar", type: "settings.result", payload: { ok, error } },
      "*"
    );
  }

  async function saveSettingsViaApi(payload) {
    const r = await apiPut("/api/settings", payload || {});
    if (!r.ok) { postSettingsResult(false, "API offline"); return; }
    const body = r.data || {};
    if (body.error) { postSettingsResult(false, body.message || body.error); return; }
    sidebarState.settings = body;
    publishStateToSidebar();
    refreshDashboard();   // cap might have changed — update today counter
    postSettingsResult(true);
  }

  async function applyPresetViaApi(name) {
    const r = await apiPost(`/api/settings/preset/${encodeURIComponent(name)}`, {});
    if (!r.ok) { postSettingsResult(false, "API offline"); return; }
    const body = r.data || {};
    if (body.error) { postSettingsResult(false, body.message || body.error); return; }
    sidebarState.settings = body;
    publishStateToSidebar();
    refreshDashboard();
    postSettingsResult(true);
  }

  function postEventResult(ok, error) {
    const iframe = document.getElementById(SIDEBAR_ID);
    if (!iframe || !iframe.contentWindow) return;
    iframe.contentWindow.postMessage(
      { to: "tally-sidebar", type: "event.result", payload: { ok, error } },
      "*"
    );
  }

  async function addEventViaApi(payload) {
    // Timeline events are per-vacancy — require a view-page context.
    const job = sidebarState.currentJob;
    if (!job || !job.jobId) {
      postEventResult(false, "Open a vacancy first");
      return;
    }
    const body = {
      job_id: job.jobId,
      kind:   (payload && payload.kind) || "note",
    };
    if (payload && payload.note) body.note = payload.note;
    const r = await apiPost("/api/events", body);
    if (!r.ok) { postEventResult(false, "API offline"); return; }
    const res = r.data || {};
    if (res.error) { postEventResult(false, res.message || res.error); return; }
    // Refresh timeline + dashboard so counts stay in sync
    await refreshTimeline(job.jobId);
    refreshDashboard();
    postEventResult(true);
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
  // Only accept messages whose origin matches this extension. This
  // blocks LinkedIn scripts from spoofing {from:"tally-sidebar",...}
  // while staying robust across LinkedIn SPA re-renders (the prior
  // `event.source === iframe.contentWindow` check silently dropped
  // legitimate messages whenever the iframe's WindowProxy lost its
  // identity — e.g. right after DOM mutations).
  const _EXTENSION_ORIGIN = new URL(chrome.runtime.getURL("")).origin;
  window.addEventListener("message", (event) => {
    if (event.origin !== _EXTENSION_ORIGIN) return;
    const data = event.data;
    if (!data || data.from !== "tally-sidebar") return;
    if (data.type === "sidebar.ready") {
      refreshDashboard();
      publishPageContext();
      refreshSettings();
    } else if (data.type === "autopilot.toggle") {
      runAutopilot();
    } else if (data.type === "job.save") {
      saveCurrentJob();
    } else if (data.type === "settings.open") {
      refreshSettings();
    } else if (data.type === "settings.save") {
      saveSettingsViaApi(data.payload);
    } else if (data.type === "settings.preset") {
      const name = data.payload && data.payload.name;
      if (name) applyPresetViaApi(name);
    } else if (data.type === "event.add") {
      addEventViaApi(data.payload || {});
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

  const apiGet  = (path)       => apiCall("GET",  path);
  const apiPost = (path, body) => apiCall("POST", path, body);
  const apiPut  = (path, body) => apiCall("PUT",  path, body);

  // ── helpers ──────────────────────────────────────────────────────

  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
  function randomDelay(lo, hi) { return sleep(lo + Math.random() * (hi - lo)); }

  // Autopilot reads user settings once at the top of each run. All
  // mid-run delays flow through autopilotDelay(kind) which respects
  // the fetched min/max pair + randomise flag. Falls back to the
  // historical "regular" preset if the API is unreachable.
  const _AUTOPILOT_FALLBACK = {
    randomize_delays: true,
    delays_ms: {
      click_min:           2500, click_max:           5000,
      between_saves_min:   8000, between_saves_max:  20000,
      page_transition_min: 4000, page_transition_max: 9000,
    },
  };
  let autopilotSettings = null;

  async function loadAutopilotSettings() {
    const r = await apiGet("/api/settings");
    autopilotSettings = (r.ok && r.data && r.data.delays_ms) ? r.data : _AUTOPILOT_FALLBACK;
  }

  function autopilotDelay(kind) {
    const s = autopilotSettings || _AUTOPILOT_FALLBACK;
    const lo = s.delays_ms[`${kind}_min`];
    const hi = s.delays_ms[`${kind}_max`];
    return s.randomize_delays ? randomDelay(lo, hi) : sleep(lo);
  }

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
  function isCompanyPage() { return /\/company\//.test(location.href); }

  // LinkedIn redirects to /help/, /authwall, /checkpoint, /challenge, or
  // /uas/login when its anti-bot heuristics trip. Autopilot must detect
  // this and stop immediately — continuing to click/extract against a
  // safety page trains LinkedIn's detector and risks account restriction.
  function isOnLinkedInSafetyPage() {
    return /linkedin\.com\/(help\/|authwall|checkpoint|challenge|uas\/(login|authorize))/
      .test(location.href);
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
    if (!jobId) {
      updateBtn("No job ID", "error");
      setSaveStatus({ state: "error", label: "No job ID on this page", working: false });
      return;
    }

    // Skip if we already have it
    if (savedIds.has(jobId)) {
      updateBtn("Already saved", "exists");
      setSaveStatus({ state: "exists", label: "In vault already", working: false });
      publishPageContext();
      setTimeout(renderActionButton, 3000);
      return;
    }

    updateBtn("Extracting...", "working");
    setSaveStatus({ state: "working", label: "Extracting…", working: true });
    const data = await extractJob(url, jobId);
    updateBtn("Saving...", "working");
    setSaveStatus({ state: "working", label: "Saving…", working: true });
    const r = await apiPost("/api/parse", data);
    if (!r.ok) {
      updateBtn("API offline", "error");
      setSaveStatus({ state: "error", label: "API offline", working: false });
      setTimeout(renderActionButton, 4000);
      return;
    }
    const res = r.data;
    if (res.status === "saved") {
      savedIds.add(jobId);
      updateBtn(`Saved (${res.parsed_today}/${res.parsed_today + res.remaining_today})`, "success");
      setSaveStatus({
        state: "saved",
        label: `Saved (${res.parsed_today}/${res.parsed_today + res.remaining_today})`,
        working: false,
      });
      publishPageContext();
      refreshDashboard();
    } else if (res.status === "exists") {
      savedIds.add(jobId);
      updateBtn("Already saved", "exists");
      setSaveStatus({ state: "exists", label: "In vault already", working: false });
      publishPageContext();
    } else if (res.error === "daily_cap") {
      updateBtn("Daily cap reached", "error");
      setSaveStatus({ state: "error", label: "Daily cap reached", working: false });
    } else {
      updateBtn("Error: " + (res.error || "unknown"), "error");
      setSaveStatus({ state: "error", label: "Error: " + (res.error || "unknown"), working: false });
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
        await autopilotDelay("click");
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

      await autopilotDelay("between_saves");
    }
  }

  // Single writer for the running flag — also syncs sidebar state.
  // Every mutation of `autopilotRunning` must go through here, or the
  // sidebar button will fall out of sync with reality (see Phase 1
  // retro: button stuck on "Stop" after autopilot finished).
  function setAutopilotRunning(val) {
    autopilotRunning = val;
    sidebarState.autopilotRunning = val;
    publishStateToSidebar();
  }

  async function runAutopilot() {
    if (autopilotRunning) {
      autopilotAbort = true;
      updateBtn("Stopping...", "working");
      return;
    }
    setAutopilotRunning(true);
    autopilotAbort = false;

    await loadAutopilotSettings();
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
      if (isOnLinkedInSafetyPage()) {
        updateBtn("⚠️ LinkedIn safety page — autopilot stopped", "error");
        break;
      }
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
      await autopilotDelay("page_transition");
      if (autopilotAbort) break;

      try {
        window.history.pushState({}, "", nextUrl);
        window.dispatchEvent(new PopStateEvent("popstate"));
      } catch {
        location.href = nextUrl;
        return;
      }
      await sleep(3000);
      if (isOnLinkedInSafetyPage()) {
        updateBtn("⚠️ LinkedIn safety page — autopilot stopped", "error");
        break;
      }
    }

    setAutopilotRunning(false);
    autopilotAbort = false;
    updateBtn(
      `Done p.${stats.page}: ${stats.saved} saved, ${stats.skipped} skip, ${stats.failed} fail`,
      "success"
    );
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
      // Sidebar owns Save on view pages. Hide the floating button to
      // avoid duplicate UI. Fallback: if sidebar failed to inject, still
      // render the floating button so Save stays reachable.
      if (document.getElementById(SIDEBAR_CONTAINER_ID)) {
        btn.style.display = "none";
        return;
      }
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
      // Sidebar owns Autopilot on list pages. Hide the floating button to
      // avoid duplicate UI. Fallback: if sidebar failed to inject, still
      // render the floating button so Autopilot stays reachable.
      if (document.getElementById(SIDEBAR_CONTAINER_ID)) {
        btn.style.display = "none";
        return;
      }
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

  // ── Auto-save on view ───────────────────────────────────────────
  // When the user opens a vacancy (directly via /jobs/view/<id> or by
  // clicking a card in the list, which updates ?currentJobId=<id> via
  // pushState), the DOM is already populated with everything we need —
  // save it without requiring an extra click. Skips if Autopilot is
  // already running (no need to double-save) or if the vacancy is
  // already in the vault. One-shot per job_id per tab.
  //
  // Timing: rather than a fixed setTimeout (original implementation used
  // 2.5s as a heuristic "enough time for LinkedIn to lazy-load the JD"),
  // we POLL the DOM every 400ms up to a 6s cap and save as soon as the
  // description block is present with substantial text. Snappy on fast
  // networks, patient on slow ones, and the sidebar sees a visible
  // "Auto-saving…" status the whole time so the user isn't staring at
  // silence wondering what's going on.

  // jobs we've already attempted in this tab. Set ONLY after save fires
  // (success or known terminal failure) so a fast-scrub user who blew
  // past a job and returns to it later gets a retry instead of silence.
  const autoSaveAttempted = new Set();
  let autoSaveSeq = 0;
  const AUTO_SAVE_SETTLE_MS = 350;       // bare minimum for LinkedIn to swap detail pane
  const AUTO_SAVE_DESC_BONUS_MS = 1500;  // give description a bit longer if not yet there

  function isJobDomReady() {
    const panel = getDetailPanel();
    const desc = getJobDescription(panel);
    if (!desc) return false;
    return (desc.innerText || "").trim().length >= 200;
  }

  // No cooldown for manual auto-save — LinkedIn never sees /api/parse
  // calls (they go to localhost) and only sees the user's own click
  // rate, which Tally doesn't accelerate. The user is responsible for
  // their browsing pace. Autopilot keeps its own randomised cooldowns
  // because there the *clicks* are programmatic and visible.
  async function maybeAutoSaveCurrentView() {
    if (autopilotRunning) return;
    if (isOnLinkedInSafetyPage()) {
      setSaveStatus({ state: "error", label: "⚠️ LinkedIn safety page — auto-save paused", working: false });
      return;
    }
    const jid = jobIdFromUrl(location.href);
    if (!jid) return;
    if (savedIds.has(jid)) return;
    if (autoSaveAttempted.has(jid)) return;

    const mySeq = ++autoSaveSeq;
    setSaveStatus({ state: "working", label: "Auto-saving…", working: true });

    // Settle phase: wait the bare minimum for LinkedIn to swap the
    // detail pane to the new job's title/company. Without this we'd
    // sometimes capture the previous job's DOM under the new job_id.
    await sleep(AUTO_SAVE_SETTLE_MS);
    if (mySeq !== autoSaveSeq) return;
    if (autopilotRunning) return;
    if (jobIdFromUrl(location.href) !== jid) return;
    if (savedIds.has(jid)) return;

    // Bonus phase: wait up to ~1.5s for description to populate.
    // Bail at any point if the user moves on; the worst case is a
    // record with shallow description, recoverable by revisiting.
    const bonusEnd = Date.now() + AUTO_SAVE_DESC_BONUS_MS;
    while (Date.now() < bonusEnd && !isJobDomReady()) {
      await sleep(150);
      if (mySeq !== autoSaveSeq) return;
      if (autopilotRunning) return;
      if (jobIdFromUrl(location.href) !== jid) return;
      if (savedIds.has(jid)) return;
    }
    if (mySeq !== autoSaveSeq) return;
    if (autopilotRunning) return;
    if (jobIdFromUrl(location.href) !== jid) return;
    if (savedIds.has(jid)) return;

    autoSaveAttempted.add(jid);
    saveCurrentJob();
  }

  // ── init / observer ─────────────────────────────────────────────

  async function onPageUpdate() {
    await refreshSavedIds();
    markSavedCards();
    renderActionButton();
    maybeAutoSaveCurrentView();
  }

  const observer = new MutationObserver(() => {
    clearTimeout(observer._timer);
    observer._timer = setTimeout(() => {
      markSavedCards();
      renderActionButton();
      if (/\/(jobs|company|in)\//.test(location.href)) {
        injectSidebar();
        publishPageContext();
        maybeAutoSaveCurrentView();
      }
    }, 1200);
  });

  observer.observe(document.body, { childList: true, subtree: true });

  // Pre-load autopilot settings on init so the auto-save cooldown
  // honours the user's between_saves_min from the very first navigation,
  // not only after they manually fire Autopilot. Refreshed on every
  // /api/settings save so changes from the gear panel take effect
  // without waiting for a Tally restart.
  loadAutopilotSettings();
  setInterval(loadAutopilotSettings, 60000);

  // URL-change detection — pure polling, no history-method patching.
  //
  // Earlier versions monkey-patched history.pushState/replaceState to
  // get instant URL-change notifications. That works, but it's a
  // detectable client-side fingerprint: any defensive script can call
  // `history.pushState.toString()` and see our wrapper instead of
  // `[native code]`. Anti-bot systems do this routinely. Removed.
  //
  // What we use instead:
  //  - popstate event (back/forward — fires natively, no patching needed)
  //  - 200ms location.href poll (one string compare per tick — invisible
  //    to any fingerprinting, can't be blocked, fires within a frame
  //    of any URL change including pushState'd ones)
  //  - DOM MutationObserver (already wired below; catches LinkedIn's
  //    detail-pane swap with its own 1.2s debounce, as a third backup)
  let _lastSeenHref = location.href;
  setInterval(() => {
    if (location.href !== _lastSeenHref) {
      _lastSeenHref = location.href;
      window.dispatchEvent(new Event("tally:url"));
    }
  }, 200);
  window.addEventListener("popstate", () => {
    if (location.href !== _lastSeenHref) {
      _lastSeenHref = location.href;
      window.dispatchEvent(new Event("tally:url"));
    }
  });

  let _urlChangeDebounce = null;
  function _safePublishContextAndMaybeSave() {
    try {
      // markSavedCards on every tick — cheap querySelectorAll over the
      // visible card list, keeps the green "Saved" badges in sync as
      // LinkedIn re-renders the list (was previously gated behind the
      // 1.2s observer debounce and silently lost badges on fast nav).
      markSavedCards();
      if (/\/(jobs|company|in)\//.test(location.href)) {
        publishPageContext();
        maybeAutoSaveCurrentView();
      } else {
        publishPageContext();
      }
    } catch (e) { /* never break LinkedIn on a sidebar refresh */ }
  }

  window.addEventListener("tally:url", () => {
    clearTimeout(_urlChangeDebounce);
    // Tiny debounce — coalesces rapid bursts but doesn't delay each
    // card swap by more than a frame the user notices.
    _urlChangeDebounce = setTimeout(_safePublishContextAndMaybeSave, 80);
  });

  // Final safety net: re-publish + re-mark every 3s no matter what.
  setInterval(_safePublishContextAndMaybeSave, 3000);

  // Debug: log link clicks that navigate within /jobs/, /company/, /in/.
  // Captures destination href + visible text. NEVER captures cookies or
  // form data. Bounded volume — only the nav links we actually care about.
  if (DEBUG_CAPTURE) {
    document.addEventListener("click", (e) => {
      const a = e.target && e.target.closest && e.target.closest("a[href]");
      if (!a) return;
      const href = a.href || "";
      if (!/linkedin\.com\/(jobs\/|company\/|in\/)/.test(href)) return;
      debugLog("link_click", {
        href,
        text: (a.innerText || "").trim().slice(0, 80),
      });
    }, true);
    debugLog("session_start", {
      ua_lang: navigator.language,
      tally_v: "phase-A",
    });
  }

  setTimeout(() => {
    onPageUpdate();
    if (/\/jobs\//.test(location.href)) {
      injectSidebar();
      publishPageContext();
    }
  }, 2000);
  // Re-sync periodically in case the vault changes server-side
  setInterval(refreshSavedIds, 60000);
  setInterval(refreshDashboard, 60000);
})();
