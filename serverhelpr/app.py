import json
import time

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

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
- Prefer the simplest read-only command that directly answers the user's request.
- Do not invent extra troubleshooting steps after a successful result.
- If the user did not ask for a change, do not make a change.
- Keep answers concise unless the user asks for detail.

FAILURE DISCIPLINE:
- Treat command output, stderr, and exit codes as authoritative evidence.
- If a command fails, report the actual error before suggesting a fix.
- Do not claim a lock is stale, a service is broken, a package is missing, or another condition exists unless command output establishes it.
- Do not perform cleanup or remediation merely because a command failed.
- If the user has not explicitly asked to fix a failure, do not execute a corrective command.
- Never replace a failed command with a different destructive command unless the user explicitly requests remediation.

Never claim to have run a command unless the tool result confirms it.
Do not attempt to access the Proxmox host unless it is explicitly configured as a target.

The user wants practical, evidence-based troubleshooting. Keep command output concise.
"""


console = Console()


def _run_with_spinner(label, fn):
    start = time.perf_counter()
    with console.status(Spinner("dots", text=f" {label}"), spinner_style="cyan"):
        result = fn()
    return result, time.perf_counter() - start


def _show_banner(ollama, servers):
    title = Text("SERVERHELPR", style="bold cyan")
    subtitle = Text("local Linux operations agent", style="dim")
    console.print(Panel.fit(
        Text.assemble(title, "\n", subtitle),
        border_style="cyan",
        padding=(0, 2),
    ))

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Model", ollama.model)
    table.add_row("Ollama", f"context={ollama.num_ctx}  max_output={ollama.num_predict}  think={ollama.think}")
    table.add_row("Targets", ", ".join(servers))
    console.print(table)
    console.print()


def _show_tool_request(server, command, elapsed=None):
    body = Text()
    body.append("TARGET  ", style="bold")
    body.append(server + "\n", style="cyan")
    body.append("COMMAND ", style="bold")
    body.append(command)
    if elapsed is not None:
        body.append(f"\n\nCompleted in {elapsed:.2f}s", style="dim")

    console.print(Panel(
        body,
        title="[bold yellow]AI TOOL REQUEST[/bold yellow]",
        border_style="yellow",
    ))


def _show_result(result):
    code = result.get("exit_code")
    success = code == 0
    title = "[bold green]COMMAND RESULT[/bold green]" if success else "[bold red]COMMAND FAILED[/bold red]"
    border = "green" if success else "red"

    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Exit", str(code))

    stdout = result.get("stdout", "").strip()
    stderr = result.get("stderr", "").strip()

    if stdout:
        table.add_row("stdout", stdout)
    if stderr:
        table.add_row("stderr", stderr)

    console.print(Panel(table, title=title, border_style=border))


def main():
    config = load_config()
    servers = config["servers"]

    if not servers:
        raise SystemExit("No servers configured in config.yaml")

    ollama = OllamaClient(config)
    policy = Policy(config)
    ssh = SSHManager(config)
    tools = build_tools(servers)

    _show_banner(ollama, servers)
    console.print("[dim]Type 'exit' to quit.[/dim]")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    max_history_messages = int(
        config.get("ollama", {}).get("max_history_messages", 8)
    )

    while True:
        try:
            console.print()
            user = Prompt.ask("[bold cyan]You[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not user:
            continue
        if user.lower() in {"exit", "quit"}:
            break

        messages.append({"role": "user", "content": user})

        if len(messages) > max_history_messages + 1:
            messages = [messages[0]] + messages[-max_history_messages:]

        lower_user = user.lower()
        expected_command = None
        if "hostname" in lower_user:
            expected_command = "hostname"
        elif "who am i" in lower_user or "current user" in lower_user:
            expected_command = "whoami"
        elif "uptime" in lower_user:
            expected_command = "uptime"
        elif "memory" in lower_user or "ram" in lower_user:
            expected_command = "free -h"
        elif "disk usage" in lower_user or "disk space" in lower_user:
            expected_command = "df -h"

        while True:
            result, elapsed = _run_with_spinner(
                "Thinking / planning…",
                lambda: ollama.chat(messages, tools),
            )
            message = result.get("message", {})
            messages.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                console.print(
                    Panel(
                        message.get("content", ""),
                        title=f"[bold cyan]AI RESPONSE[/bold cyan]  [dim]{elapsed:.2f}s[/dim]",
                        border_style="cyan",
                    )
                )
                break

            if len(tool_calls) > 1:
                console.print(
                    Panel(
                        f"AI requested {len(tool_calls)} commands; limiting execution to one at a time.",
                        title="[bold red]TOOL LIMIT[/bold red]",
                        border_style="red",
                    )
                )
                messages.append({
                    "role": "tool",
                    "content": json.dumps({
                        "ok": False,
                        "error": (
                            "Only one command may be executed per turn. "
                            "Choose the single simplest command that directly "
                            "answers the user."
                        ),
                    }),
                })
                continue

            call = tool_calls[0]
            function = call.get("function", {})
            name = function.get("name")

            if name != "run_command":
                continue

            args = function.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)

            server_name = args.get("server")
            command = args.get("command")

            if command:
                console.print(
                    Panel(
                        f"[bold]Planning:[/bold] run [cyan]{command}[/cyan] on [cyan]{server_name}[/cyan]",
                        title="[bold cyan]AI PLAN[/bold cyan]",
                        border_style="cyan",
                    )
                )

            if server_name not in servers:
                tool_result = {"ok": False, "error": "Unknown server."}
            elif not command:
                tool_result = {"ok": False, "error": "Empty command."}
            elif expected_command and command != expected_command:
                console.print(
                    Panel(
                        f"Expected: {expected_command}\nReceived: {command}",
                        title="[bold red]INTENT GUARD BLOCKED[/bold red]",
                        border_style="red",
                    )
                )
                tool_result = {
                    "ok": False,
                    "error": (
                        "Command rejected by deterministic intent guard. "
                        f"For this request, use exactly: {expected_command}"
                    ),
                }
            elif policy.is_allowed(server_name, command) or policy.request(
                server_name, command
            ):
                _show_tool_request(server_name, command)
                try:
                    tool_result, command_elapsed = _run_with_spinner(
                        f"Executing on {server_name}…",
                        lambda: ssh.run(
                            server_name,
                            servers[server_name],
                            command,
                        ),
                    )
                    tool_result["ok"] = tool_result["exit_code"] == 0
                    _show_tool_request(server_name, command, command_elapsed)
                    _show_result(tool_result)
                except Exception as exc:
                    tool_result = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    console.print(
                        Panel(
                            tool_result["error"],
                            title="[bold red]EXECUTION ERROR[/bold red]",
                            border_style="red",
                        )
                    )
            else:
                tool_result = {
                    "ok": False,
                    "error": "User denied command execution.",
                }
                console.print(
                    Panel(
                        "Command denied by user.",
                        title="[bold yellow]COMMAND DENIED[/bold yellow]",
                        border_style="yellow",
                    )
                )

            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(tool_result),
                }
            )
