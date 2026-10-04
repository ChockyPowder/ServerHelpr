import uuid
from flask import Flask, jsonify, request, send_from_directory

from .config import load_config
from .ollama import OllamaClient


WEB_SYSTEM_PROMPT = "You are ServerHelpr, a local AI assistant focused on helping the user reason through technical, infrastructure, Linux, networking, coding, and troubleshooting questions.\n\nYou are running in WEB CHAT MODE.\n\nIMPORTANT WEB MODE LIMITS:\n- You are a chat-only assistant.\n- You have NO SSH access.\n- You have NO access to servers, files, shells, terminals, Docker, systemd, or other external systems.\n- You cannot execute commands or make changes.\n- Never claim that you inspected, changed, restarted, installed, or verified anything on a real system.\n- When useful, provide commands, code, configuration examples, or step-by-step instructions for the user to run themselves.\n- If the user asks you to perform an action on a server, explain that this web chat cannot access it and give the safest practical instructions instead.\n\nREASONING STYLE:\n- Understand the complete goal before answering.\n- Think through problems carefully and systematically.\n- Check assumptions and point out uncertainty.\n- For troubleshooting, narrow the problem down step by step and distinguish facts from guesses.\n- Prefer concrete commands and actionable diagnostics when appropriate.\n- For coding, give complete, usable examples and explain important failure modes.\n- Do not invent command output, system state, or test results.\n- Keep answers focused and useful rather than adding unnecessary filler.\n"

app = Flask(__name__, static_folder="web", static_url_path="")

config = load_config()
ollama = OllamaClient(config)
agent = config.get("agent", {})
max_history = int(agent.get("max_history_messages", 30))
_sessions = {}


def _new_session():
    sid = uuid.uuid4().hex
    _sessions[sid] = {
        "messages": [{"role": "system", "content": WEB_SYSTEM_PROMPT}]
    }
    return sid


def _session(sid):
    if sid and sid in _sessions:
        return sid
    return _new_session()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def api_config():
    return jsonify({
        "model": ollama.model,
        "chat_only": True,
    })


@app.post("/api/session")
def api_session():
    return jsonify({"session_id": _new_session()})


@app.post("/api/chat")
def api_chat():
    body = request.get_json(silent=True) or {}
    sid = _session(body.get("session_id"))
    user_text = str(body.get("message", "")).strip()

    if not user_text:
        return jsonify({"error": "Message is required."}), 400

    messages = _sessions[sid]["messages"]
    messages.append({"role": "user", "content": user_text})

    try:
        result = ollama.chat(messages, [])
        message = result.get("message", {})
        content = (message.get("content") or "").strip()

        if not content:
            return jsonify({
                "session_id": sid,
                "type": "error",
                "content": "The model returned no response.",
            }), 502

        messages.append({
            "role": "assistant",
            "content": content,
        })

        if len(messages) > max_history:
            messages[:] = [messages[0]] + messages[-(max_history - 1):]

        return jsonify({
            "session_id": sid,
            "type": "answer",
            "content": content,
        })
    except Exception as exc:
        return jsonify({
            "session_id": sid,
            "type": "error",
            "content": f"{type(exc).__name__}: {exc}",
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
