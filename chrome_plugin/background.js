// Background service worker — proxy API calls from content scripts to
// bypass MV3 cross-origin quirks. Content scripts cannot always fetch
// localhost directly even with host_permissions; routing through here is
// reliable because the service worker runs in the extension origin.
//
// Protocol: content.js posts { type: "api", method, path, body }
// and gets back { ok: true, status, data } or { ok: false, error }.

const API = "http://127.0.0.1:8000";

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "api") {
    const url = `${API}${msg.path}`;
    const init = { method: msg.method || "GET" };
    if (msg.body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = typeof msg.body === "string" ? msg.body : JSON.stringify(msg.body);
    }
    fetch(url, init)
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        sendResponse({ ok: r.ok, status: r.status, data });
      })
      .catch((err) => sendResponse({ ok: false, status: 0, error: String(err) }));
    return true; // keep channel open for async sendResponse
  }
});

// Toolbar icon → no popup; jump straight to a LinkedIn jobs tab.
// If one is already open, focus it; otherwise create a new tab on the
// recommended-jobs feed. This is the user's "is the extension live?"
// signal: a click that does something is unmistakable.
const JOBS_URL = "https://www.linkedin.com/jobs/collections/recommended/";

chrome.action.onClicked.addListener(async () => {
  try {
    // Prefer an existing LinkedIn tab — most likely the one the user
    // wants to land in. Match any /jobs/ path; fall back to any
    // linkedin.com tab; create a new one if neither exists.
    const allLinked = await chrome.tabs.query({ url: "https://www.linkedin.com/*" });
    const onJobs = allLinked.find((t) => /\/jobs\//.test(t.url || ""));
    const target = onJobs || allLinked[0];
    if (target) {
      await chrome.tabs.update(target.id, { active: true });
      if (target.windowId !== undefined) {
        await chrome.windows.update(target.windowId, { focused: true });
      }
      // If the existing tab isn't on a /jobs/ page, send it there
      if (!onJobs) {
        await chrome.tabs.update(target.id, { url: JOBS_URL });
      }
    } else {
      await chrome.tabs.create({ url: JOBS_URL, active: true });
    }
  } catch (err) {
    // Last-resort fallback — open a new tab even if the queries blew up
    chrome.tabs.create({ url: JOBS_URL, active: true });
  }
});
