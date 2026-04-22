(() => {
  const autopilotBtn     = document.getElementById("tally-autopilot-btn");
  const autopilotSection = document.getElementById("tally-autopilot-section");
  const vacancySection   = document.getElementById("tally-vacancy-section");
  const vacancyTitle     = document.getElementById("tally-vacancy-title");
  const saveBtn          = document.getElementById("tally-save-btn");
  const saveMsg          = document.getElementById("tally-save-msg");
  const closeBtn         = document.getElementById("tally-close");
  const statusDot        = document.getElementById("tally-status-dot");
  const vacanciesEl      = document.getElementById("tally-vacancies");
  const companiesEl      = document.getElementById("tally-companies");
  const todayEl          = document.getElementById("tally-today");
  const progressEl       = document.getElementById("tally-progress");

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

    // Page-aware sections: view page shows Save, list page shows Autopilot
    const mode = payload.pageMode || "other";
    if (mode === "view") {
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

  // Signal readiness — content.js will respond with a "state" message
  window.parent.postMessage({ from: "tally-sidebar", type: "sidebar.ready" }, "*");
})();
