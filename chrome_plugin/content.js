(() => {
  const PANEL_ID = "jm-skill-panel";
  const BTN_ID = "jm-action-btn";
  let detected = [];
  let autopilotRunning = false;
  let autopilotAbort = false;

  // ── API proxy: route every request through background service worker
  //    so we don't hit CORS / host_permissions edge cases in MV3 ──────

  function apiCall(method, path, body) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(
        { type: "api", method, path, body },
        (res) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: chrome.runtime.lastError.message });
          } else {
            resolve(res || { ok: false, error: "no response" });
          }
        }
      );
    });
  }

  const apiGet = (path) => apiCall("GET", path);
  const apiPost = (path, body) => apiCall("POST", path, body);

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

  function isRecommendedPage() {
    return /\/jobs\/collections\/recommended/.test(location.href);
  }

  function isSearchPage() {
    return /\/jobs\/search/.test(location.href);
  }

  function isSimilarJobsPage() {
    return /\/jobs\/collections\/similar-jobs/.test(location.href);
  }

  function isJobListPage() {
    return isRecommendedPage() || isSearchPage() || isSimilarJobsPage();
  }

  // Replace / add ?start=N in current URL
  function urlWithStart(n) {
    const u = new URL(location.href);
    u.searchParams.set("start", String(n));
    return u.toString();
  }

  // Ban / authwall detection (mirrors config.py)
  const BAN_URL_PATTERNS = ["/checkpoint/", "/authwall", "/uas/login", "/login?", "/security/"];
  const BAN_TEXT_PATTERNS = [
    "unusual activity", "security verification", "let's do a quick security check",
    "we restrict", "your account has been temporarily",
    "we've detected some unusual activity",
  ];

  function detectBan() {
    const url = location.href;
    for (const p of BAN_URL_PATTERNS) if (url.includes(p)) return `url: ${p}`;
    const body = document.body ? document.body.innerText.slice(0, 4000).toLowerCase() : "";
    for (const p of BAN_TEXT_PATTERNS) if (body.includes(p)) return `text: ${p}`;
    return null;
  }

  // ── skill detection (unchanged) ──────────────────────────────────

  function getJobDescription() {
    const selectors = [
      "#job-details",
      ".jobs-description__content",
      ".jobs-box__html-content",
      ".jobs-description-content__text",
      '[class*="description__text"]',
      "article",
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
    const r = await apiGet(`/api/detect?text=${encodeURIComponent(text.slice(0, 5000))}`);
    if (!r.ok) return; // API offline / error
    detected = r.data.detected || [];
    renderPanel(detected);
    highlightSkills(descEl, detected);
  }

  // ── click "Show more" to expand description (parse_job.py parity) ─

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

  // ── fulltext description fallback (parse_job.py parity) ─────────

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

  // ── top_card parser (parse_job.py parity) ────────────────────────

  function parseTopCardFromBody(bodyText) {
    const dot = String.fromCharCode(183); // ·
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

  // ── extract current job from DOM (used by single-save + autopilot) ─

  async function extractJob(url, jobId) {
    // Try to click "Show more" before reading description
    await clickShowMore();

    const pageTitle = document.title || "";
    const titleEl = document.querySelector(
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

    const compLink = document.querySelector('a[href*="/company/"]');
    const company = compLink ? compLink.innerText.trim() : "";
    const companyUrl = compLink ? compLink.href.split("?")[0] : "";

    const bodyText = document.body ? document.body.innerText : "";
    const top = parseTopCardFromBody(bodyText);

    const descEl = getJobDescription();
    let descHtml = "", descText = "";
    if (descEl) {
      descHtml = descEl.innerHTML;
      descText = descEl.innerText.trim();
    }
    // Fulltext fallback if description element is missing or too short
    if (!descText || descText.length < 50) {
      const fallback = extractDescriptionFulltext(bodyText);
      if (fallback) { descText = fallback; descHtml = ""; }
    }

    return {
      url, job_id: jobId, title, company, company_url: companyUrl,
      location: top.location, employment: top.employment,
      applies: top.applies, reposted: top.reposted,
      description_html: descHtml, description_text: descText,
    };
  }

  function extractCurrentJob() {
    const url = location.href;
    const jobId = jobIdFromUrl(url);
    if (!jobId) return null;
    return extractJob(url, jobId);
  }

  // ── save single job ──────────────────────────────────────────────

  async function saveCurrentJob() {
    updateBtn("Extracting...", "working");
    const data = await extractCurrentJob();
    if (!data) { updateBtn("No job ID", "error"); return; }
    updateBtn("Saving...", "working");
    const r = await apiPost("/api/parse", data);
    if (!r.ok) { updateBtn("API offline", "error"); setTimeout(renderActionButton, 4000); return; }
    const res = r.data;
    if (res.status === "saved") updateBtn(`Saved (${res.parsed_today}/${res.parsed_today + res.remaining_today})`, "success");
    else if (res.status === "exists") updateBtn("Already saved", "exists");
    else if (res.error === "daily_cap") updateBtn("Daily cap reached", "error");
    else updateBtn("Error: " + (res.error || "unknown"), "error");
    setTimeout(renderActionButton, 4000);
  }

  // ── autopilot: pagination-aware list crawler ─────────────────────

  function getJobCards() {
    const links = document.querySelectorAll(
      '.scaffold-layout__list a[href*="/jobs/view/"], ' +
      '.jobs-search-results-list a[href*="/jobs/view/"], ' +
      'a.job-card-container__link, a.job-card-list__title, ' +
      '[data-occludable-job-id]'
    );
    const seen = new Set();
    const result = [];
    for (const a of links) {
      let id, href;
      if (a.href) { id = jobIdFromUrl(a.href); href = a.href; }
      else if (a.dataset && a.dataset.occludableJobId) {
        id = a.dataset.occludableJobId;
        const inner = a.querySelector('a[href*="/jobs/view/"]');
        href = inner ? inner.href : `https://www.linkedin.com/jobs/view/${id}/`;
      }
      if (id && !seen.has(id)) { seen.add(id); result.push({ id, href, el: a }); }
    }
    return result;
  }

  function getClickableCardEl(id) {
    // Find a clickable anchor for this job id on the list
    const a = document.querySelector(
      `a[href*="/jobs/view/${id}"], a[href*="currentJobId=${id}"], ` +
      `[data-occludable-job-id="${id}"] a[href*="/jobs/view/"]`
    );
    return a;
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

  async function scrollListToBottom(maxAttempts = 15) {
    const container = getScrollContainer();
    if (!container) { window.scrollBy(0, 2000); await sleep(1500); return; }
    for (let i = 0; i < maxAttempts; i++) {
      if (autopilotAbort) return;
      container.scrollBy(0, 600);
      await sleep(1500);
      const atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 50;
      if (atBottom) { await sleep(2000); return; }
    }
  }

  async function processCurrentPage(stats) {
    // Scroll to load all cards
    let prev = 0;
    for (let i = 0; i < 20; i++) {
      if (autopilotAbort) return;
      await scrollListToBottom(1);
      const n = getJobCards().length;
      updateBtn(`Loading... (${n} cards)`, "working");
      if (n === prev) break;
      prev = n;
    }

    const cards = getJobCards();
    updateBtn(`${cards.length} jobs on this page`, "working");
    await sleep(800);

    for (let i = 0; i < cards.length; i++) {
      if (autopilotAbort) return;
      const card = cards[i];

      // Check ban on each iteration
      const ban = detectBan();
      if (ban) { stats.banned = ban; return; }

      updateBtn(`[${i + 1}/${cards.length}] page ${stats.page} (${stats.saved} saved)`, "working");

      try {
        const clickEl = getClickableCardEl(card.id) || card.el;
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
        if (!r.ok) { stats.failed++; }
        else {
          const res = r.data;
          if (res.status === "saved") stats.saved++;
          else if (res.status === "exists") stats.skipped++;
          else if (res.error === "daily_cap") { stats.capReached = true; return; }
          else stats.failed++;
        }
      } catch { stats.failed++; }

      // Humanized delay between jobs (parity with config.PARSE_DELAY_MIN/MAX)
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

    const pageSize = isSearchPage() ? 25 : 24;
    const startUrl = new URL(location.href);
    const initialStart = parseInt(startUrl.searchParams.get("start") || "0");

    const stats = { saved: 0, skipped: 0, failed: 0, page: 1, capReached: false, banned: null };
    let consecutiveEmpty = 0;
    let start = initialStart;

    while (!autopilotAbort) {
      await processCurrentPage(stats);
      if (stats.capReached) { updateBtn(`Cap! ${stats.saved} saved`, "error"); break; }
      if (stats.banned) { updateBtn(`BAN detected — stopped`, "error"); console.warn("jm: ban", stats.banned); break; }
      if (autopilotAbort) break;

      // Check if this page added new vacancies
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

      // Navigate to next page (pagination)
      start += pageSize;
      stats.page++;
      const nextUrl = urlWithStart(start);
      updateBtn(`Next page: start=${start}`, "working");
      await randomDelay(4000, 9000);
      if (autopilotAbort) break;

      // Use history.pushState + manual reload? No — LinkedIn is an SPA,
      // direct location change works and re-triggers content script.
      // But that would lose our running JS state. Instead use
      // window.location.replace which keeps autopilot state lost…
      // Solution: we stay here but mutate the URL — LinkedIn SPA
      // picks up ?start= via its own router after a moment, OR we fall
      // back to hard navigate.
      try {
        window.history.pushState({}, "", nextUrl);
        window.dispatchEvent(new PopStateEvent("popstate"));
      } catch {
        location.href = nextUrl;
        return; // page reload — state lost, but pagination happens
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
