import json

from .config import load_config
from .ollama import OllamaClient
from .policy import Policy
from .ssh import SSHManager
from .tools import build_tools


SYSTEM_PROMPT = """You are ServerHelpr, a local Linux server operations assistant.

You manage only the configured servers through the run_command tool.

COMMAND DISCIPLINE:
- Use exactly one run_command call when one command answers the user's question.
- Do not issue multiple equivalent commands.
- For hostname questions use exactly: hostname
- For current user use exactly: whoami
- For uptime use exactly: uptime
- For memory use exactly: free -h
- For disk usage use exactly: df -h
- Prefer the simplest read-only command that directly answers the question.
- Do not invent extra troubleshooting steps after a successful result.
- If the user did not ask for a change, do not make a change.

Before requesting a command, include a short user-facing action summary in the tool call's reason field. This is not private chain-of-thought.

Never claim to have run a command unless the tool result confirms it.
Do not attempt to access the Proxmox host unless it is explicitly configured as a target.

The user wants practical, evidence-based troubleshooting. Keep command output concise.
"""


def main():
    config = load_config()
    servers = config["servers"]

    if not servers:
        raise SystemExit("No servers configured in config.yaml")

    ollama = OllamaClient(config)
    policy = Policy(config)
    ssh = SSHManager(config)
    tools = build_tools(servers)

    print("ServerHelpr 0.2.0")
    print(f"Model: {ollama.model}")
    print("Servers:", ", ".join(servers))
    print("Type 'exit' to quit.")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user:
            continue
        if user.lower() in {"exit", "quit"}:
            break

        messages.append({"role": "user", "content": user})

        while True:
            print("\nAI is working...")
            result = ollama.chat(messages, tools)
            message = result.get("message", {})
            messages.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                print("\nAI:", message.get("content", ""))
                break

            if len(tool_calls) > 1:
                print(f"AI requested {len(tool_calls)} commands; limiting execution to one at a time.")
                messages.append({
                    "role": "tool",
                    "content": json.dumps({
                        "ok": False,
                        "error": (
                            f"Only one command may be executed per turn. "
                            f"You requested {len(tool_calls)} commands. "
                            "Choose the single simplest command that directly answers the user."
                        ),
                    }),
                })
                continue

            for call in tool_calls[:1]:
                function = call.get("function", {})
                name = function.get("name")

                if name != "run_command":
                    continue

                args = function.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)

                server_name = args.get("server")
                command = args.get("command")
                reason = args.get("reason", "").strip()

                if reason:
                    print(f"AI plan: {reason}")
                else:
                    print("AI plan: execute the requested diagnostic command.")

                if server_name not in servers:
                    tool_result = {"ok": False, "error": "Unknown server."}
                elif not command:
                    tool_result = {"ok": False, "error": "Empty command."}
                elif policy.is_allowed(server_name, command) or policy.request(
                    server_name, command
                ):
                    try:
                        tool_result = ssh.run(
                            server_name,
                            servers[server_name],
                            command,
                        )
                        tool_result["ok"] = True
                    except Exception as exc:
                        tool_result = {
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                else:
                    tool_result = {
                        "ok": False,
                        "error": "User denied command execution.",
                    }

                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(tool_result),
                    }
                )
