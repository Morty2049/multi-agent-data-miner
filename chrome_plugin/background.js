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
