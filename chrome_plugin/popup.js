const API = "http://127.0.0.1:8000";

// ── helpers ─────────────────────────────────────────────────────────

async function api(path) {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function showStatus(msg, isError = true) {
  const bar = $("#status-bar");
  $("#status-msg").textContent = msg;
  bar.classList.toggle("hidden", false);
  bar.style.background = isError ? "var(--red)" : "var(--accent2)";
}

function hideStatus() { $("#status-bar").classList.add("hidden"); }

function loading(container) {
  container.innerHTML =
    '<div class="loading"><div class="spinner"></div><br>Loading...</div>';
}

function empty(container, msg = "No results") {
  container.innerHTML = `<div class="empty">${msg}</div>`;
}

function scoreColor(score) {
  if (score >= 0.7) return "var(--accent2)";
  if (score >= 0.4) return "var(--accent3)";
  return "var(--red)";
}

// ── tabs ────────────────────────────────────────────────────────────

$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
  });
});

$("#status-close").addEventListener("click", hideStatus);

// ── health check ────────────────────────────────────────────────────

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
    showStatus("API server offline. Run: uvicorn api_server:app --reload");
    return false;
  }
}

// ── DASHBOARD ───────────────────────────────────────────────────────

async function loadDashboard() {
  const ok = await checkApi();
  if (!ok) return;

  try {
    const d = await api("/api/dashboard");
    $("#stat-vacancies").textContent = d.total_vacancies;
    $("#stat-companies").textContent = d.total_companies;
    $("#stat-skills").textContent = d.total_skills;

    // top skills bar chart
    const chart = $("#top-skills-chart");
    const maxCount = d.top_skills[0]?.count || 1;
    chart.innerHTML = d.top_skills
      .slice(0, 15)
      .map(
        (s) => `
      <div class="bar-row">
        <span class="bar-label" title="${s.name}">${s.name}</span>
        <div class="bar-track">
          <div class="bar-fill" style="width:${(s.count / maxCount) * 100}%"></div>
        </div>
        <span class="bar-count">${s.count}</span>
      </div>`
      )
      .join("");

    // top locations
    const locDiv = $("#top-locations");
    locDiv.innerHTML = d.top_locations
      .map(
        (l) =>
          `<span class="tag">${l.name}<span class="tag-count">${l.count}</span></span>`
      )
      .join("");

    // employment types
    const empDiv = $("#employment-types");
    empDiv.innerHTML = Object.entries(d.employment_types)
      .sort((a, b) => b[1] - a[1])
      .map(
        ([k, v]) =>
          `<span class="tag">${k}<span class="tag-count">${v}</span></span>`
      )
      .join("");
  } catch (e) {
    showStatus(`Dashboard error: ${e.message}`);
  }
}

// ── SKILLS ──────────────────────────────────────────────────────────

let skillDebounce = null;

$("#skill-search").addEventListener("input", (e) => {
  clearTimeout(skillDebounce);
  skillDebounce = setTimeout(() => searchSkills(e.target.value), 300);
});

async function searchSkills(q) {
  const container = $("#skill-results");
  const detail = $("#skill-detail");
  detail.classList.add("hidden");

  if (!q.trim()) {
    container.innerHTML = '<div class="empty">Type to search skills</div>';
    return;
  }

  loading(container);
  try {
    const skills = await api(`/api/skills?q=${encodeURIComponent(q)}`);
    if (!skills.length) {
      empty(container, "No skills found");
      return;
    }
    container.innerHTML = skills
      .map(
        (s) => `
      <div class="list-item" data-skill="${s.name}">
        <div class="list-item-title">${s.name}</div>
        <div class="list-item-sub">${s.about ? s.about.slice(0, 80) + (s.about.length > 80 ? "..." : "") : "No description"}</div>
        <div class="list-item-meta">
          <span class="badge badge-accent">${s.mentions_count} jobs</span>
          ${s.parents.length ? `<span class="badge badge-green">${s.parents[0]}</span>` : ""}
          ${s.children.length ? `<span class="badge badge-orange">${s.children.length} children</span>` : ""}
        </div>
      </div>`
      )
      .join("");

    container.querySelectorAll(".list-item").forEach((el) => {
      el.addEventListener("click", () => showSkillDetail(el.dataset.skill));
    });
  } catch (e) {
    showStatus(`Skill search error: ${e.message}`);
  }
}

async function showSkillDetail(name) {
  const detail = $("#skill-detail");
  detail.classList.remove("hidden");
  detail.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  try {
    const s = await api(`/api/skills/${encodeURIComponent(name)}`);
    if (s.error) {
      detail.innerHTML = `<p>${s.error}</p>`;
      return;
    }
    detail.innerHTML = `
      <h4>${s.name}</h4>
      <p>${s.about || "No description available."}</p>
      ${s.parents.length ? `
        <div class="detail-section">
          <div class="detail-section-title">Parents</div>
          <div class="tag-cloud">${s.parents.map((p) => `<span class="tag">${p}</span>`).join("")}</div>
        </div>` : ""}
      ${s.children.length ? `
        <div class="detail-section">
          <div class="detail-section-title">Children</div>
          <div class="tag-cloud">${s.children.map((c) => `<span class="tag">${c}</span>`).join("")}</div>
        </div>` : ""}
      <div class="detail-section">
        <div class="detail-section-title">Referenced in ${s.mentions.length} vacancies</div>
        <div class="tag-cloud">${s.mentions.slice(0, 8)
          .map((m) => {
            const parts = m.split("_-_");
            const label = parts.length > 1 ? parts[0].replace(/_/g, " ") : m.replace(/_/g, " ");
            return `<span class="tag">${label}</span>`;
          }).join("")}
          ${s.mentions.length > 8 ? `<span class="tag">+${s.mentions.length - 8} more</span>` : ""}
        </div>
      </div>`;
  } catch (e) {
    detail.innerHTML = `<p>Error loading skill: ${e.message}</p>`;
  }
}

// ── MATCHER ─────────────────────────────────────────────────────────

$("#matcher-btn").addEventListener("click", runMatcher);
$("#matcher-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runMatcher();
});

async function runMatcher() {
  const input = $("#matcher-input").value.trim();
  const container = $("#matcher-results");
  if (!input) return;

  loading(container);
  try {
    const jobs = await api(`/api/jobs/match?skills=${encodeURIComponent(input)}`);
    if (!jobs.length) {
      empty(container, "No matching jobs found. Try different skills.");
      return;
    }
    container.innerHTML = jobs
      .map(
        (j) => `
      <div class="list-item" ${j.job_url ? `data-url="${j.job_url}"` : ""}>
        <div class="list-item-title">${j.title}</div>
        <div class="list-item-sub">${j.company} &middot; ${j.location || "Remote"}</div>
        <div class="score-bar-wrap">
          <div class="score-bar">
            <div class="score-bar-fill" style="width:${j.match_score * 100}%; background:${scoreColor(j.match_score)}"></div>
          </div>
          <span class="score-label" style="color:${scoreColor(j.match_score)}">${Math.round(j.match_score * 100)}%</span>
        </div>
        <div class="list-item-meta">
          ${j.matched_skills.slice(0, 5).map((s) => `<span class="badge badge-green">${s}</span>`).join("")}
          ${j.missing_skills.length ? `<span class="badge badge-red">${j.missing_skills.length} gaps</span>` : ""}
        </div>
      </div>`
      )
      .join("");

    container.querySelectorAll(".list-item[data-url]").forEach((el) => {
      el.addEventListener("click", () => chrome.tabs.create({ url: el.dataset.url }));
    });
  } catch (e) {
    showStatus(`Matcher error: ${e.message}`);
  }
}

// ── COMPANIES ───────────────────────────────────────────────────────

let companyDebounce = null;

$("#company-search").addEventListener("input", (e) => {
  clearTimeout(companyDebounce);
  companyDebounce = setTimeout(() => searchCompanies(e.target.value), 300);
});

async function searchCompanies(q) {
  const container = $("#company-results");
  loading(container);

  try {
    const companies = await api(`/api/companies?q=${encodeURIComponent(q || "")}`);
    if (!companies.length) {
      empty(container, "No companies found");
      return;
    }
    container.innerHTML = companies
      .map(
        (c) => `
      <div class="list-item">
        <div class="list-item-title">${c.name}</div>
        <div class="list-item-sub">${c.industry || "—"} &middot; ${c.size || "—"}</div>
        <div class="list-item-meta">
          <span class="badge badge-accent">${c.jobs_count} jobs</span>
          ${c.headquarters && c.headquarters !== "Unknown" ? `<span class="badge badge-green">${c.headquarters}</span>` : ""}
          ${c.website ? `<span class="badge badge-orange">website</span>` : ""}
        </div>
      </div>`
      )
      .join("");
  } catch (e) {
    showStatus(`Company search error: ${e.message}`);
  }
}

// ── GAPS ────────────────────────────────────────────────────────────

$("#gaps-btn").addEventListener("click", runGaps);
$("#gaps-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runGaps();
});

async function runGaps() {
  const input = $("#gaps-input").value.trim();
  const container = $("#gaps-results");
  if (!input) return;

  loading(container);
  try {
    const gaps = await api(`/api/gaps?skills=${encodeURIComponent(input)}`);
    if (!gaps.length) {
      empty(container, "No skill gaps detected. Your profile covers everything!");
      return;
    }
    const maxDemand = gaps[0]?.demand || 1;
    container.innerHTML = gaps
      .map(
        (g) => `
      <div class="gap-bar">
        <span class="gap-name" title="${g.name}">${g.name}</span>
        <div class="gap-track">
          <div class="gap-fill" style="width:${(g.demand / maxDemand) * 100}%"></div>
        </div>
        <span class="gap-count">${g.demand}</span>
      </div>
      ${g.about ? `<div class="gap-about">${g.about.slice(0, 100)}${g.about.length > 100 ? "..." : ""}</div>` : ""}`
      )
      .join("");
  } catch (e) {
    showStatus(`Gap analysis error: ${e.message}`);
  }
}

// ── init ────────────────────────────────────────────────────────────

loadDashboard();
searchCompanies("");
