(() => {
  const autopilotBtn = document.getElementById("tally-autopilot-btn");
  const closeBtn     = document.getElementById("tally-close");
  const statusDot    = document.getElementById("tally-status-dot");
  const vacanciesEl  = document.getElementById("tally-vacancies");
  const companiesEl  = document.getElementById("tally-companies");
  const todayEl      = document.getElementById("tally-today");
  const progressEl   = document.getElementById("tally-progress");

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
  }

  // Listen for state pushes from the parent (content.js)
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || data.to !== "tally-sidebar") return;
    if (data.type === "state") {
      applyState(data.payload);
    }
  });

  // Autopilot toggle
  autopilotBtn.addEventListener("click", () => {
    window.parent.postMessage({ from: "tally-sidebar", type: "autopilot.toggle" }, "*");
  });

  // Close
  closeBtn.addEventListener("click", () => {
    window.parent.postMessage({ from: "tally-sidebar", type: "sidebar.close" }, "*");
  });

  // Signal readiness — content.js will respond with a "state" message
  window.parent.postMessage({ from: "tally-sidebar", type: "sidebar.ready" }, "*");
})();
