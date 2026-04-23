const API = "http://127.0.0.1:8000";
const dot = document.getElementById("api-dot");
const msg = document.getElementById("api-msg");

async function checkApi() {
  try {
    const r = await fetch(`${API}/api/health`, { cache: "no-store" });
    if (r.ok) {
      dot.dataset.state = "online";
      dot.title = "API online";
      msg.classList.add("hidden");
      return;
    }
    throw new Error(`status ${r.status}`);
  } catch {
    dot.dataset.state = "offline";
    dot.title = "API offline";
    msg.innerHTML = 'API offline. Start with:<br><span class="cmd">venv/bin/uvicorn chrome_plugin.api_server:app --port 8000</span>';
    msg.classList.remove("hidden");
  }
}

document.getElementById("open-jobs").addEventListener("click", () => {
  chrome.tabs.create({ url: "https://www.linkedin.com/jobs/collections/recommended/" });
  window.close();
});

checkApi();
