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
      todayEl.textContent = payload.parsedToday + "/" + payload.dailyCap;
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

    // Page-aware sections. Settings panel takes over when open,
    // otherwise view pages show Save and list pages show Autopilot.
    const mode = payload.pageMode || "other";
    lastPageMode = mode;
    if (settingsOpen) {
      vacancySection.classList.add("tally-hidden");
      autopilotSection.classList.add("tally-hidden");
    } else if (mode === "view") {
      vacancySection.classList.remove("tally-hidden");
      autopilotSection.classList.add("tally-hidden");
      const job = payload.currentJob;
      vacancyTitle.textContent = (job && job.title) ? job.title : "Loading…";
      applySaveButton(job, payload.saveStatus);
    } else if (mode === "list") {
      vacancySection.classList.add("tally-hidden");
      autopilotSection.classList.remove("tally-hidden");
    } else {
      vacancySection.classList.add("tally-hidden");
      autopilotSection.classList.add("tally-hidden");
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
      vacancySection.classList.add("tally-hidden");
      autopilotSection.classList.add("tally-hidden");
      settingsMsg.textContent = "";
      window.parent.postMessage({ from: "tally-sidebar", type: "settings.open" }, "*");
    } else {
      // Restore whichever section matches the page we were on.
      if (lastPageMode === "view") vacancySection.classList.remove("tally-hidden");
      else if (lastPageMode === "list") autopilotSection.classList.remove("tally-hidden");
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

  // Listen for state pushes from the parent (content.js)
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || data.to !== "tally-sidebar") return;
    if (data.type === "state") {
      applyState(data.payload);
    }
  });

  autopilotBtn.addEventListener("click", () => {
    window.parent.postMessage({ from: "tally-sidebar", type: "autopilot.toggle" }, "*");
  });

  saveBtn.addEventListener("click", () => {
    if (saveBtn.disabled) return;
    window.parent.postMessage({ from: "tally-sidebar", type: "job.save" }, "*");
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

  // content.js can echo back a save result via a "settings.result" message
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || data.to !== "tally-sidebar") return;
    if (data.type === "settings.result") {
      settingsMsg.textContent = data.payload && data.payload.ok
        ? "Saved ✓"
        : (data.payload && data.payload.error) || "Error";
    }
  });

  // Signal readiness — content.js will respond with a "state" message
  window.parent.postMessage({ from: "tally-sidebar", type: "sidebar.ready" }, "*");
})();
