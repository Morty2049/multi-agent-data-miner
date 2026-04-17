(() => {
  const API = "http://127.0.0.1:8000";
  const PANEL_ID = "jm-skill-panel";
  let detected = [];

  function getJobDescription() {
    const selectors = [
      ".jobs-description__content",
      ".jobs-box__html-content",
      ".jobs-description-content__text",
      '[class*="description__text"]',
      "#job-details",
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
        ${sorted
          .map(
            (s) => `
          <div class="jm-skill" title="${s.about || ""}">
            <span class="jm-skill-name">${s.name}</span>
            <span class="jm-skill-jobs">${s.mentions} jobs</span>
          </div>`
          )
          .join("")}
      </div>
    `;
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
          html = html.replace(
            re,
            '<span class="jm-highlight" title="Tracked skill">$1</span>'
          );
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

  async function scan() {
    const descEl = getJobDescription();
    if (!descEl) return;

    const text = descEl.innerText;
    if (text.length < 30) return;

    try {
      const r = await fetch(
        `${API}/api/detect?text=${encodeURIComponent(text.slice(0, 5000))}`
      );
      if (!r.ok) return;
      const data = await r.json();
      detected = data.detected || [];
      renderPanel(detected);
      highlightSkills(descEl, detected);
    } catch {
      // API offline — silently skip
    }
  }

  const observer = new MutationObserver(() => {
    clearTimeout(observer._timer);
    observer._timer = setTimeout(scan, 1500);
  });

  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(scan, 2000);
})();
