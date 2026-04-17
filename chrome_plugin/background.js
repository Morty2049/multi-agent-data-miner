const API = "http://127.0.0.1:8000";

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "api") {
    const url = `${API}${msg.path}`;
    fetch(url)
      .then((r) => r.json())
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
});
