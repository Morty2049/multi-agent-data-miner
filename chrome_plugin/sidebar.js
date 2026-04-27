(() => {
  const autopilotBtn     = document.getElementById("tally-autopilot-btn");
  const autopilotSection = document.getElementById("tally-autopilot-section");
  const vacancySection   = document.getElementById("tally-vacancy-section");
  const vacancyTitle     = document.getElementById("tally-vacancy-title");
  const saveBtn          = document.getElementById("tally-save-btn");
  const saveMsg          = document.getElementById("tally-save-msg");
  const closeBtn         = document.getElementById("tally-close");
  const gearBtn          = document.getElementById("tally-gear");
  const statusDot        = document.getElementById("tally-status-dot");
  const vacanciesEl      = document.getElementById("tally-vacancies");
  const companiesEl      = document.getElementById("tally-companies");
  const todayEl          = document.getElementById("tally-today");
  const progressEl       = document.getElementById("tally-progress");

  // Company history refs
  const companySection   = document.getElementById("tally-company-section");
  const companyName      = document.getElementById("tally-company-name");
  const companyList      = document.getElementById("tally-company-list");
  const companyCount     = document.getElementById("tally-company-count");
  const companyEmpty     = document.getElementById("tally-company-empty");

  // Match section refs
  const matchSection     = document.getElementById("tally-match-section");
  const matchPct         = document.getElementById("tally-match-pct");
  const matchSummary     = document.getElementById("tally-match-summary");
  const matchSkills      = document.getElementById("tally-match-skills");
  const matchGapsWrap    = document.getElementById("tally-match-gaps-wrap");
  const matchGapsList    = document.getElementById("tally-match-gaps");
  const scoreBtn         = document.getElementById("tally-score-btn");
  const matchMsg         = document.getElementById("tally-match-msg");

  // Timeline refs
  const timelineSection  = document.getElementById("tally-timeline-section");
  const timelineList     = document.getElementById("tally-timeline-list");
  const timelineCount    = document.getElementById("tally-timeline-count");
  const eventKindSelect  = document.getElementById("tally-event-kind");
  const eventNoteInput   = document.getElementById("tally-event-note");
  const eventAddBtn      = document.getElementById("tally-event-add");
  const eventMsg         = document.getElementById("tally-event-msg");

  // Settings panel refs
  const settingsSection  = document.getElementById("tally-settings-section");
  const modeBadge        = document.getElementById("tally-mode-badge");
  const presetBtns       = document.querySelectorAll(".tally-preset-btn");
  const dailyCapInput    = document.getElementById("tally-daily-cap-input");
  const dailyCapUnlimitedBox = document.getElementById("tally-daily-cap-unlimited");
  const randomizeBox     = document.getElementById("tally-randomize");
  const matchThresholdInput = document.getElementById("tally-match-threshold-input");
  const matchThresholdValue = document.getElementById("tally-match-threshold-value");
  const settingsMsg      = document.getElementById("tally-settings-msg");

  let settingsOpen = false;
  let lastPageMode = "other";  // remembered so closing settings restores the right section
  let _currentThreshold = 80;

  function applyState(payload) {
    // API status dot
    statusDot.className = "tally-status-dot " + (
      payload.apiOnline === true  ? "tally-dot-ok" :
      payload.apiOnline === false ? "tally-dot-offline" :
                                    "tally-dot-unknown"
    );

    // Stat cards
    vacanciesEl.textContent = payload.totalVacancies != null ? payload.totalVacancies : "—";
    companiesEl.textContent = payload.totalCompanies != null ? payload.totalCompanies : "—";
    if (payload.parsedToday != null && payload.dailyCap != null) {
      // daily_cap=null on the server becomes the _UNLIMITED sentinel
      // (1e9) in the dashboard response. Show it as ∞ so the number
      // doesn't dwarf the "TODAY" stat card.
      const isUnlimited = payload.dailyCap >= 1e8;
      todayEl.textContent = isUnlimited
        ? payload.parsedToday + " / ∞"
        : payload.parsedToday + " / " + payload.dailyCap;
    } else if (payload.parsedToday != null) {
      todayEl.textContent = payload.parsedToday;
    } else {
      todayEl.textContent = "—";
    }

    // Autopilot button
    if (payload.autopilotRunning) {
      autopilotBtn.textContent = "Stop";
      autopilotBtn.classList.add("tally-btn-running");
    } else {
      autopilotBtn.textContent = "Autopilot";
      autopilotBtn.classList.remove("tally-btn-running");
    }

    // Progress text
    progressEl.textContent = payload.autopilotProgress || "";

    // Settings form content — populate whenever content.js pushes
    // fresh settings. Update _currentThreshold BEFORE applyMatch so
    // the muted-pct visual uses the latest threshold on every render.
    if (payload.settings) {
      applySettingsForm(payload.settings);
      _currentThreshold = payload.settings.match_threshold ?? 80;
    }

    // Page-aware sections. View pages show Save, list pages show
    // Autopilot; settings panel (if open) appears beneath them — they
    // all stay accessible at the same time.
    const mode = payload.pageMode || "other";
    lastPageMode = mode;
    // Sections are independent of each other — Current Vacancy +
    // Timeline are driven by the URL having a jobId (works on list
    // pages with ?currentJobId too, not just /jobs/view/), Autopilot
    // is driven by pageMode === "list", and Company History by
    // pageMode === "company". On a list page with a selected card,
    // the user sees Autopilot AND the per-vacancy Timeline at once.
    const job = payload.currentJob;
    if (job && job.jobId) {
      vacancySection.classList.remove("tally-hidden");
      matchSection.classList.remove("tally-hidden");
      timelineSection.classList.remove("tally-hidden");
      vacancyTitle.textContent = job.title || "Loading…";
      applySaveButton(job, payload.saveStatus);
      applyMatch(payload.matchScore);
      applyTimeline(payload.timeline || []);
    } else {
      vacancySection.classList.add("tally-hidden");
      matchSection.classList.add("tally-hidden");
      timelineSection.classList.add("tally-hidden");
    }
    if (mode === "list") {
      autopilotSection.classList.remove("tally-hidden");
    } else {
      autopilotSection.classList.add("tally-hidden");
    }
    if (mode === "company") {
      companySection.classList.remove("tally-hidden");
      const co = payload.currentCompany;
      companyName.textContent = (co && co.name) ? co.name : "—";
      applyCompanyHistory(payload.companyHistory || []);
    } else {
      companySection.classList.add("tally-hidden");
    }
  }

  function applySettingsForm(s) {
    modeBadge.textContent = (s.mode || "regular").toUpperCase();
    presetBtns.forEach((b) => {
      b.classList.toggle("tally-active", b.dataset.preset === s.mode);
    });
    if (s.daily_cap === null || s.daily_cap === undefined) {
      dailyCapUnlimitedBox.checked = true;
      dailyCapInput.disabled = true;
      dailyCapInput.value = "";
    } else {
      dailyCapUnlimitedBox.checked = false;
      dailyCapInput.disabled = false;
      dailyCapInput.value = String(s.daily_cap);
    }
    randomizeBox.checked = Boolean(s.randomize_delays);
    const thr = s.match_threshold ?? 80;
    matchThresholdInput.value = String(thr);
    matchThresholdValue.textContent = thr + "%";
  }

  function collectSettingsFromForm() {
    const unlimited = dailyCapUnlimitedBox.checked;
    const rawCap = parseInt(dailyCapInput.value, 10);
    const dailyCap = unlimited ? null : (Number.isFinite(rawCap) ? rawCap : undefined);
    const rawThr = parseInt(matchThresholdInput.value, 10);
    const matchThreshold = Number.isFinite(rawThr) ? rawThr : undefined;
    const payload = {
      randomize_delays: randomizeBox.checked,
      mode: "custom",
    };
    if (matchThreshold !== undefined) payload.match_threshold = matchThreshold;
    if (dailyCap !== undefined) payload.daily_cap = dailyCap;
    return payload;
  }

  function toggleSettings(open) {
    settingsOpen = open;
    settingsSection.classList.toggle("tally-hidden", !open);
    gearBtn.classList.toggle("tally-active", open);
    gearBtn.setAttribute("aria-expanded", String(open));
    if (open) {
      settingsMsg.textContent = "";
      window.parent.postMessage({ from: "tally-sidebar", type: "settings.open" }, "*");
    }
    // Vacancy / Autopilot sections are page-context driven (see
    // applyState) and stay visible regardless of settings panel state.
  }

  function formatEventAt(isoString) {
    if (!isoString) return "";
    const d = new Date(isoString);
    if (Number.isNaN(d.getTime())) return "";
    // Month short + day + HH:mm — compact and unambiguous in context.
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const mm = months[d.getMonth()];
    const dd = d.getDate();
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${mm} ${dd}, ${hh}:${mi}`;
  }

  function applyTimeline(events) {
    timelineCount.textContent = String(events.length);
    // Oldest first (chronological) so the latest event sits at the bottom
    // closest to the "Add event" form. Matches the design mockup.
    const sorted = events.slice().sort((a, b) => {
      const at = a.at || ""; const bt = b.at || "";
      return at < bt ? -1 : at > bt ? 1 : 0;
    });
    timelineList.innerHTML = "";
    for (const ev of sorted) {
      const li = document.createElement("li");
      li.className = "tally-event";
      li.dataset.kind = ev.kind || "note";
      const dot  = document.createElement("span"); dot.className = "tally-event-dot";
      const body = document.createElement("div"); body.className = "tally-event-body";
      const kind = document.createElement("div"); kind.className = "tally-event-kind";
      kind.textContent = (ev.kind || "note").replace("_", " ");
      const note = document.createElement("div"); note.className = "tally-event-note";
      note.textContent = ev.note || "";
      body.appendChild(kind);
      if (ev.note) body.appendChild(note);
      const at = document.createElement("span"); at.className = "tally-event-at";
      at.textContent = formatEventAt(ev.at);
      li.appendChild(dot); li.appendChild(body); li.appendChild(at);
      timelineList.appendChild(li);
    }
  }

  function applyCompanyHistory(items) {
    companyCount.textContent = String(items.length);
    companyList.innerHTML = "";
    if (items.length === 0) {
      companyEmpty.classList.remove("tally-hidden");
      return;
    }
    companyEmpty.classList.add("tally-hidden");
    for (const it of items) {
      const li = document.createElement("li");
      li.className = "tally-company-row";
      li.dataset.kind = it.status || "saved";

      const dot = document.createElement("span");
      dot.className = "tally-company-row-dot";

      const titleCell = document.createElement("div");
      titleCell.className = "tally-company-title";
      const link = document.createElement("a");
      link.href = `https://www.linkedin.com/jobs/view/${it.job_id}/`;
      link.target = "_top";  // open in the parent LinkedIn tab, not inside the iframe
      link.textContent = it.title || `Job ${it.job_id}`;
      link.title = it.title || "";
      titleCell.appendChild(link);

      const pill = document.createElement("span");
      pill.className = "tally-company-pill";
      pill.dataset.kind = it.status || "saved";
      pill.textContent = (it.status || "saved").replace("_", " ");

      li.appendChild(dot);
      li.appendChild(titleCell);
      li.appendChild(pill);
      companyList.appendChild(li);
    }
  }

  function applyMatch(score) {
    // score: null | {error, message?, raw?} | {working: true} | {match_pct, summary, skills, gaps, cached_at}
    matchSkills.innerHTML = "";
    matchGapsList.innerHTML = "";
    matchGapsWrap.classList.add("tally-hidden");

    if (!score) {
      matchPct.textContent = "—";
      matchPct.removeAttribute("data-tier");
      matchSummary.textContent = "";
      scoreBtn.textContent = "Score this vacancy";
      scoreBtn.disabled = false;
      matchMsg.textContent = "";
      return;
    }
    if (score.working) {
      matchPct.textContent = "…";
      matchSummary.textContent = "";
      scoreBtn.textContent = "Scoring…";
      scoreBtn.disabled = true;
      matchMsg.textContent = "Asking Gemini…";
      return;
    }
    if (score.error === "no_api_key") {
      matchPct.textContent = "—";
      matchPct.removeAttribute("data-tier");
      matchSummary.textContent = "";
      scoreBtn.textContent = "Score this vacancy";
      scoreBtn.disabled = true;
      matchMsg.textContent = "Set GOOGLE_API_KEY in .env to enable scoring";
      return;
    }
    if (score.error) {
      matchPct.textContent = "—";
      matchPct.removeAttribute("data-tier");
      matchSummary.textContent = "";
      scoreBtn.textContent = "Retry score";
      scoreBtn.disabled = false;
      matchMsg.textContent = score.message || score.error;
      return;
    }
    // Successful score
    const pct = Math.max(0, Math.min(100, Math.round(score.match_pct || 0)));
    matchPct.textContent = pct + "%";
    if (pct >= 85) matchPct.dataset.tier = "strong";
    else if (pct >= 60) matchPct.removeAttribute("data-tier");
    else if (pct >= 40) matchPct.dataset.tier = "weak";
    else matchPct.dataset.tier = "poor";
    if (pct < _currentThreshold) {
      matchPct.classList.add("tally-pct-below");
    } else {
      matchPct.classList.remove("tally-pct-below");
    }
    matchSummary.textContent = score.summary || "";
    scoreBtn.textContent = "Re-score";
    scoreBtn.disabled = false;
    matchMsg.textContent = "";
    // Skills
    for (const s of (score.skills || [])) {
      const li = document.createElement("li");
      li.className = "tally-match-skill";
      const w = Math.max(0, Math.min(1, Number(s.weight) || 0));
      li.innerHTML = `
        <span class="tally-match-skill-name"></span>
        <span class="tally-match-skill-pct">${Math.round(w * 100)}%</span>
        <span class="tally-match-skill-bar"><span class="tally-match-skill-bar-fill" style="width:${(w * 100).toFixed(0)}%"></span></span>
      `;
      li.querySelector(".tally-match-skill-name").textContent = s.name || "";
      if (s.evidence) {
        const ev = document.createElement("div");
        ev.className = "tally-match-skill-evidence";
        ev.textContent = s.evidence;
        li.appendChild(ev);
      }
      matchSkills.appendChild(li);
    }
    // Gaps
    const gaps = score.gaps || [];
    if (gaps.length) {
      matchGapsWrap.classList.remove("tally-hidden");
      for (const g of gaps) {
        const li = document.createElement("li");
        const sev = (g.severity === "hard" ? "hard" : "soft");
        li.innerHTML = `<span class="tally-match-gap-severity" data-severity="${sev}">${sev}</span>`;
        const text = document.createTextNode((g.name || "") + (g.mitigation ? " — " + g.mitigation : ""));
        li.appendChild(text);
        matchGapsList.appendChild(li);
      }
    }
  }

  function applySaveButton(job, status) {
    saveBtn.classList.remove("tally-btn-running", "tally-btn-saved", "tally-btn-exists");
    saveMsg.textContent = "";

    if (job && job.saved) {
      saveBtn.textContent = "In vault ✓";
      saveBtn.disabled = true;
      saveBtn.classList.add("tally-btn-exists");
      if (status && status.state === "saved") saveMsg.textContent = status.label;
      return;
    }
    if (status && status.working) {
      saveBtn.textContent = status.label || "Saving…";
      saveBtn.disabled = true;
      saveBtn.classList.add("tally-btn-running");
      return;
    }
    if (status && status.state === "error") {
      saveBtn.textContent = "Save to vault";
      saveBtn.disabled = false;
      saveMsg.textContent = status.label || "Error";
      return;
    }
    // idle
    saveBtn.textContent = "Save to vault";
    saveBtn.disabled = false;
  }

  // Listen for state + result pushes from the parent (content.js)
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || data.to !== "tally-sidebar") return;
    if (data.type === "state") {
      applyState(data.payload);
    } else if (data.type === "settings.result") {
      const p = data.payload || {};
      settingsMsg.textContent = p.ok ? "Saved ✓" : (p.error || "Error");
    } else if (data.type === "event.result") {
      const p = data.payload || {};
      eventAddBtn.disabled = false;
      if (p.ok) {
        eventMsg.textContent = "Added ✓";
        eventNoteInput.value = "";
        eventKindSelect.value = "note";
      } else {
        eventMsg.textContent = p.error || "Error";
      }
    }
  });

  autopilotBtn.addEventListener("click", () => {
    window.parent.postMessage({ from: "tally-sidebar", type: "autopilot.toggle" }, "*");
  });

  saveBtn.addEventListener("click", () => {
    if (saveBtn.disabled) return;
    window.parent.postMessage({ from: "tally-sidebar", type: "job.save" }, "*");
  });

  scoreBtn.addEventListener("click", () => {
    window.parent.postMessage({ from: "tally-sidebar", type: "score.run" }, "*");
  });

  eventAddBtn.addEventListener("click", () => {
    const kind = eventKindSelect.value;
    const note = eventNoteInput.value.trim();
    if (!kind) return;
    eventMsg.textContent = `Adding ${kind}…`;
    eventAddBtn.disabled = true;
    window.parent.postMessage(
      { from: "tally-sidebar", type: "event.add", payload: { kind, note } },
      "*"
    );
  });

  closeBtn.addEventListener("click", () => {
    window.parent.postMessage({ from: "tally-sidebar", type: "sidebar.close" }, "*");
  });

  gearBtn.addEventListener("click", () => toggleSettings(!settingsOpen));

  // ── Auto-save settings on change ────────────────────────────────
  // Earlier UX required hitting "Save settings" after every tweak. The
  // Unlimited checkbox in particular felt broken — it greyed out the
  // input but didn't persist, so users (rightly) expected an immediate
  // effect and got none. Treating each settings field as a stateful
  // toggle that auto-persists matches every other modern settings UI
  // (Notion / Slack / Linear). The explicit Save button stays as a
  // belt-and-suspenders fallback. Localhost API is free, so the extra
  // POST per click is fine.
  function saveSettingsAuto() {
    const payload = collectSettingsFromForm();
    settingsMsg.textContent = "Saving…";
    window.parent.postMessage(
      { from: "tally-sidebar", type: "settings.save", payload },
      "*"
    );
  }

  dailyCapUnlimitedBox.addEventListener("change", () => {
    dailyCapInput.disabled = dailyCapUnlimitedBox.checked;
    if (dailyCapUnlimitedBox.checked) dailyCapInput.value = "";
    saveSettingsAuto();
  });

  // `change` (not `input`) fires once on blur for text inputs and on
  // mouseup for sliders — avoids spamming the API while the user types
  // a digit at a time or drags the slider.
  dailyCapInput.addEventListener("change", saveSettingsAuto);
  randomizeBox.addEventListener("change", saveSettingsAuto);

  matchThresholdInput.addEventListener("input", () => {
    matchThresholdValue.textContent = matchThresholdInput.value + "%";
  });
  matchThresholdInput.addEventListener("change", saveSettingsAuto);

  presetBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const preset = btn.dataset.preset;
      if (!preset) return;
      settingsMsg.textContent = `Applying ${preset}…`;
      window.parent.postMessage(
        { from: "tally-sidebar", type: "settings.preset", payload: { name: preset } },
        "*"
      );
    });
  });

  // (No explicit "Save settings" button — every settings field auto-saves
  // on change via saveSettingsAuto. The button was a UX trap: clicking it
  // after a change just re-saved the same state, with no visible diff
  // beyond a brief "Saved ✓" flash, which read as "nothing happened.")

  // Signal readiness — content.js will respond with a "state" message
  window.parent.postMessage({ from: "tally-sidebar", type: "sidebar.ready" }, "*");
})();
