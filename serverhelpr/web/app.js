let sessionId = null;

const feed = document.getElementById("feed");
const input = document.getElementById("input");
const form = document.getElementById("composer");
const thinking = document.getElementById("thinking");
const thinkingText = document.getElementById("thinkingText");

function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, c => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;"
  }[c]));
}

function addBlock(kind, html) {
  const el = document.createElement("div");
  el.className = "block " + kind;
  el.innerHTML = html;
  feed.appendChild(el);
  feed.scrollTop = feed.scrollHeight;
}

function showThinking(s) {
  thinkingText.textContent = s;
  thinking.classList.add("active");
}

function hideThinking() {
  thinking.classList.remove("active");
}

function setBusy(v) {
  input.disabled = v;
  document.querySelector(".send").disabled = v;
}

async function init() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) throw new Error("Web API returned HTTP " + response.status);
    const c = await response.json();

    document.getElementById("model").textContent = c.model || "offline";
    document.getElementById("targets").textContent = "CHAT ONLY";
    document.getElementById("memory").textContent = "local Ollama";

    const sessionResponse = await fetch("/api/session", {
      method: "POST",
      headers: {"Content-Type": "application/json"}
    });
    if (!sessionResponse.ok) throw new Error("Could not create chat session");
    sessionId = (await sessionResponse.json()).session_id;

    input.focus();
  } catch (e) {
    addBlock("assistant-block",
      '<div class="content fail">Connection error: ' + esc(e.message) + "</div>");
  }
}

async function sendMessage(text) {
  addBlock("user-block",
    '<div class="prompt-line"><span class="sigil">›</span><span>you</span></div>' +
    '<div class="content">' + esc(text) + "</div>");

  setBusy(true);
  showThinking("thinking");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({session_id: sessionId, message: text})
    });

    const raw = await response.text();
    let d;
    try {
      d = JSON.parse(raw);
    } catch {
      throw new Error("Server returned invalid JSON: " + raw.slice(0, 200));
    }

    hideThinking();

    if (!response.ok || d.type === "error") {
      throw new Error(d.content || d.error || ("HTTP " + response.status));
    }

    if (d.content) {
      addBlock("assistant-block",
        '<div class="prompt-line"><span class="sigil">◆</span><span>serverhelpr</span></div>' +
        '<div class="content">' + esc(d.content).replace(/\n/g, "<br>") + "</div>");
    } else {
      addBlock("assistant-block",
        '<div class="content fail">The model returned an empty response.</div>');
    }
  } catch (e) {
    hideThinking();
    addBlock("assistant-block",
      '<div class="content fail">ERROR: ' + esc(e.message) + "</div>");
  } finally {
    setBusy(false);
    input.focus();
  }
}

form.addEventListener("submit", e => {
  e.preventDefault();
  const t = input.value.trim();
  if (!t || input.disabled) return;
  input.value = "";
  input.style.height = "auto";
  sendMessage(t);
});

input.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 180) + "px";
});

document.querySelectorAll("[data-prompt]").forEach(b =>
  b.addEventListener("click", () => sendMessage(b.dataset.prompt))
);

init();
