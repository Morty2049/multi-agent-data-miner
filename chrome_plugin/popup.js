const API = "http://127.0.0.1:8000";

async function api(path) {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function $(sel) { return document.querySelector(sel); }

function showStatus(msg, isError = true) {
  const bar = $("#status-bar");
  $("#status-msg").textContent = msg;
  bar.classList.toggle("hidden", false);
  bar.style.background = isError ? "var(--red)" : "var(--accent2)";
}

function hideStatus() { $("#status-bar").classList.add("hidden"); }

$("#status-close").addEventListener("click", hideStatus);

async function checkApi() {
  try {
    await api("/api/health");
    $("#api-status").classList.remove("offline");
    $("#api-status").classList.add("online");
    $("#api-status").title = "API online";
    hideStatus();
    return true;
  } catch {
    $("#api-status").classList.remove("online");
    $("#api-status").classList.add("offline");
    $("#api-status").title = "API offline";
    showStatus("API offline. Run: venv/bin/uvicorn chrome_plugin.api_server:app --port 8000");
    return false;
  }
}

async function loadDashboard() {
  if (!(await checkApi())) return;

  try {
    const d = await api("/api/dashboard");
    $("#stat-vacancies").textContent = d.total_vacancies;
    $("#stat-companies").textContent = d.total_companies;

    // Parsed today + progress bar
    $("#today-value").textContent = `${d.parsed_today} / ${d.daily_cap}`;
    const pct = Math.min(100, (d.parsed_today / d.daily_cap) * 100);
    $("#today-bar").style.width = `${pct}%`;

    // Freshness
    const freshness = $("#data-freshness");
    if (d.last_parsed_date) {
      const age = d.data_age_days;
      const ageText = age === 0 ? "today" : age === 1 ? "1 day ago" : `${age} days ago`;
      freshness.textContent = `Last save: ${d.last_parsed_date} (${ageText})`;
      freshness.style.color = age <= 1 ? "var(--accent2)" : age <= 7 ? "var(--accent3)" : "var(--text-dim)";
    } else {
      freshness.textContent = "Vault is empty — go to LinkedIn and save your first vacancy.";
    }
  } catch (e) {
    showStatus(`Dashboard error: ${e.message}`);
  }
}

loadDashboard();
