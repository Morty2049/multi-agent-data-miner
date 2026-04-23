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
  const settingsSaveBtn  = document.getElementById("tally-settings-save");
  const settingsMsg      = document.getElementById("tally-settings-msg");

  let settingsOpen = false;
  let lastPageMode = "other";  // remembered so closing settings restores the right section

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

    // Page-aware sections. View pages show Save, list pages show
    // Autopilot; settings panel (if open) appears beneath them — they
    // all stay accessible at the same time.
    const mode = payload.pageMode || "other";
    lastPageMode = mode;
    if (mode === "view") {
      vacancySection.classList.remove("tally-hidden");
      autopilotSection.classList.add("tally-hidden");
      timelineSection.classList.remove("tally-hidden");
      const job = payload.currentJob;
      vacancyTitle.textContent = (job && job.title) ? job.title : "Loading…";
      applySaveButton(job, payload.saveStatus);
      applyTimeline(payload.timeline || []);
    } else if (mode === "list") {
      vacancySection.classList.add("tally-hidden");
      autopilotSection.classList.remove("tally-hidden");
      timelineSection.classList.add("tally-hidden");
    } else {
      vacancySection.classList.add("tally-hidden");
      autopilotSection.classList.add("tally-hidden");
      timelineSection.classList.add("tally-hidden");
    }

    // Settings form content — populate whenever content.js pushes
    // fresh settings. Harmless when the panel is closed.
    if (payload.settings) applySettingsForm(payload.settings);
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
  }

  function collectSettingsFromForm() {
    const unlimited = dailyCapUnlimitedBox.checked;
    const rawCap = parseInt(dailyCapInput.value, 10);
    const dailyCap = unlimited ? null : (Number.isFinite(rawCap) ? rawCap : undefined);
    const payload = { randomize_delays: randomizeBox.checked, mode: "custom" };
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

  dailyCapUnlimitedBox.addEventListener("change", () => {
    dailyCapInput.disabled = dailyCapUnlimitedBox.checked;
    if (dailyCapUnlimitedBox.checked) dailyCapInput.value = "";
  });

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

  settingsSaveBtn.addEventListener("click", () => {
    const payload = collectSettingsFromForm();
    settingsMsg.textContent = "Saving…";
    window.parent.postMessage(
      { from: "tally-sidebar", type: "settings.save", payload },
      "*"
    );
  });

  // Signal readiness — content.js will respond with a "state" message
  window.parent.postMessage({ from: "tally-sidebar", type: "sidebar.ready" }, "*");
})();
