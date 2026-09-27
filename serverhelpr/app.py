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
from .knowledge import KnowledgeBase
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
- For local IP/address use exactly: hostname -I
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


def _parse_tool_arguments(function):
    """Normalize Ollama tool arguments from small-model responses."""
    args = function.get("arguments", {})
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _parse_embedded_tool(content):
    """Recover tool-call-shaped JSON emitted as ordinary text by tiny models."""
    text = (content or "").strip()
    if not text:
        return None
    candidates = [text]
    if "<tool_call>" in text and "</tool_call>" in text:
        inner = text.split("<tool_call>", 1)[1].split("</tool_call>", 1)[0].strip()
        candidates.insert(0, inner)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        name = parsed.get("name")
        arguments = parsed.get("arguments", {})
        if isinstance(name, str) and isinstance(arguments, dict):
            return {"name": name, "arguments": arguments}
    return None


def _infer_server(user_text, servers):
    lower = user_text.lower()
    if len(servers) == 1:
        return next(iter(servers))
    for name in servers:
        if name.lower() in lower:
            return name
    return None


def _deterministic_command(user_text):
    lower = user_text.lower()
    if "hostname" in lower:
        return "hostname"
    if "who am i" in lower or "current user" in lower:
        return "whoami"
    if "uptime" in lower:
        return "uptime"
    if "memory" in lower or "ram" in lower:
        return "free -h"
    if "disk usage" in lower or "disk space" in lower:
        return "df -h"
    if ("local ip" in lower or "local ip address" in lower
            or "local address" in lower or "ip address" in lower):
        return "hostname -I"

    # Common service checks are deterministic too; this avoids asking a small
    # model to invent systemctl syntax.
    if "nginx" in lower and ("installed" in lower or "install" in lower):
        return "dpkg-query -W -f='${Status}\\n' nginx"
    if "nginx" in lower and ("running" in lower or "active" in lower or "is nginx" in lower):
        return "systemctl is-active nginx"
    return None
def _show_direct_answer(result):
    if result.get("ok"):
        output = result.get("stdout", "").strip()
        console.print(Panel(
            output or "Command completed successfully.",
            title="[bold cyan]AI RESPONSE[/bold cyan]",
            border_style="cyan",
        ))
    else:
        error = result.get("stderr") or result.get("error") or "Command failed."
        console.print(Panel(
            error.strip(),
            title="[bold red]AI RESPONSE[/bold red]",
            border_style="red",
        ))


def _run_command(ssh, servers, server_name, command, label):
    """Execute one already-validated command and render its result."""
    _show_tool_request(server_name, command)
    try:
        tool_result, command_elapsed = _run_with_spinner(
            label,
            lambda: ssh.run(server_name, servers[server_name], command),
        )
        tool_result["ok"] = tool_result.get("exit_code") == 0
        _show_tool_request(server_name, command, command_elapsed)
        _show_result(tool_result)
        return tool_result
    except Exception as exc:
        tool_result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        console.print(Panel(
            tool_result["error"],
            title="[bold red]EXECUTION ERROR[/bold red]",
            border_style="red",
        ))
        return tool_result

def main():
    config = load_config()
    servers = config["servers"]

    if not servers:
        raise SystemExit("No servers configured in config.yaml")

    ollama = OllamaClient(config)
    policy = Policy(config)
    ssh = SSHManager(config)
    tools = build_tools(servers)
    knowledge = KnowledgeBase(config)

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
        learned = knowledge.find(user)
        expected_command = None
        expected_server = None

        if learned:
            learned_command = learned.get("command")
            if learned_command == "systemctl is active nginx":
                learned_command = "systemctl is-active nginx"
            console.print(Panel(
                f"Matched learned intent: {learned.get('meaning', learned.get('phrase', user))}\\n"
                f"Command: {learned_command}",
                title="[bold green]KNOWLEDGE BASE MATCH[/bold green]",
                border_style="green",
            ))
            expected_command = learned_command
            if learned.get("server") in servers:
                expected_server = learned.get("server")

        if not expected_command:
            expected_command = _deterministic_command(user)
        if expected_command and not expected_server:
            expected_server = _infer_server(user, servers)

        # Known/learned operations execute once without an LLM round-trip.
        if expected_command and expected_server:
            if not (policy.is_allowed(expected_server, expected_command) or policy.request(
                expected_server, expected_command
            )):
                console.print(Panel(
                    "Command denied by user.",
                    title="[bold yellow]COMMAND DENIED[/bold yellow]",
                    border_style="yellow",
                ))
                continue

            tool_result = _run_command(
                ssh, servers, expected_server, expected_command,
                f"Executing on {expected_server}…",
            )
            _show_direct_answer(tool_result)
            continue

        while True:
            result, elapsed = _run_with_spinner(
                "Thinking / planning…",
                lambda: ollama.chat(messages, tools),
            )
            message = result.get("message", {})
            messages.append(message)

            tool_calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()

            # Tiny models can emit tool-call JSON as ordinary text.
            embedded = _parse_embedded_tool(content)
            if not tool_calls and embedded:
                embedded_name = embedded["name"]
                embedded_args = embedded["arguments"]
                if embedded_name == "run_command":
                    tool_calls = [{"function": {
                        "name": embedded_name,
                        "arguments": embedded_args,
                    }}]
                else:
                    known = {
                        "hostname": "hostname",
                        "whoami": "whoami",
                        "uptime": "uptime",
                        "free -h": "free -h",
                        "df -h": "df -h",
                        "hostname -I": "hostname -I",
                    }
                    suggested_command = known.get(embedded_name)
                    suggested_server = embedded_args.get("server")
                    if suggested_server not in servers:
                        suggested_server = _infer_server(user, servers)

                    suggestion = (
                        "The AI thinks you may be referring to a tool/capability "
                        "that ServerHelpr does not currently have.\n\n"
                        f"Possible tool: {embedded_name}\n"
                        f"Server: {suggested_server or 'unknown'}"
                    )
                    if suggested_command:
                        suggestion += f"\nCommand I would use: {suggested_command}"

                    console.print(Panel(
                        suggestion,
                        title=f"[bold magenta]AI TOOL SUGGESTION[/bold magenta]  [dim]{elapsed:.2f}s[/dim]",
                        border_style="magenta",
                    ))
                    choice = Prompt.ask(
                        "[bold cyan]y=yes, n=no, d=more details, a=accept + remember[/bold cyan]",
                        choices=["y", "n", "d", "a"],
                        default="n",
                    ).lower()

                    if choice == "d":
                        try:
                            details, details_elapsed = _run_with_spinner(
                                "Asking AI for more details…",
                                lambda: ollama.clarify(user, list(servers)),
                            )
                            console.print(Panel(
                                details or "The AI could not provide more detail.",
                                title=f"[bold magenta]AI DETAILS[/bold magenta]  [dim]{details_elapsed:.2f}s[/dim]",
                                border_style="magenta",
                            ))
                        except Exception as exc:
                            console.print(Panel(
                                f"Could not get more details: {type(exc).__name__}: {exc}",
                                title="[bold red]CLARIFICATION ERROR[/bold red]",
                                border_style="red",
                            ))
                        break

                    if choice == "n":
                        console.print("[dim]Okay — please rephrase the request.[/dim]")
                        break

                    if suggested_server in servers and suggested_command:
                        if choice == "a":
                            knowledge.add(
                                user,
                                f"Use {suggested_command} on {suggested_server}.",
                                suggested_server,
                                suggested_command,
                            )
                            console.print(Panel(
                                "Saved this interpretation for future requests.",
                                title="[bold green]ADDED TO KNOWLEDGE BASE[/bold green]",
                                border_style="green",
                            ))
                        if policy.is_allowed(suggested_server, suggested_command) or policy.request(
                            suggested_server, suggested_command
                        ):
                            tool_result = _run_command(
                                ssh, servers, suggested_server, suggested_command,
                                f"Executing on {suggested_server}…",
                            )
                            _show_direct_answer(tool_result)
                        else:
                            console.print(Panel(
                                "Command denied by user.",
                                title="[bold yellow]COMMAND DENIED[/bold yellow]",
                                border_style="yellow",
                            ))
                        break

                    console.print(Panel(
                        "That tool is not implemented yet, so nothing was executed.",
                        title="[bold yellow]TOOL NOT AVAILABLE[/bold yellow]",
                        border_style="yellow",
                    ))
                    break

            if not tool_calls:
                if content:
                    console.print(Panel(
                        content,
                        title=f"[bold cyan]AI RESPONSE[/bold cyan]  [dim]{elapsed:.2f}s[/dim]",
                        border_style="cyan",
                    ))
                    break

                try:
                    suggestion, clarify_elapsed = _run_with_spinner(
                        "Asking AI to clarify…",
                        lambda: ollama.clarify(user, list(servers)),
                    )
                except Exception as exc:
                    console.print(Panel(
                        f"Could not get an AI clarification: {type(exc).__name__}: {exc}",
                        title="[bold red]CLARIFICATION ERROR[/bold red]",
                        border_style="red",
                    ))
                    break

                suggestion = suggestion or "I couldn't confidently determine what you meant."
                console.print(Panel(
                    suggestion,
                    title=f"[bold magenta]AI SUGGESTION[/bold magenta]  [dim]{clarify_elapsed:.2f}s[/dim]",
                    border_style="magenta",
                ))
                choice = Prompt.ask(
                    "[bold cyan]y=yes, n=no, d=more details, a=accept + remember[/bold cyan]",
                    choices=["y", "n", "d", "a"],
                    default="n",
                ).lower()

                if choice == "d":
                    try:
                        details, details_elapsed = _run_with_spinner(
                            "Asking AI for more details…",
                            lambda: ollama.clarify(user, list(servers)),
                        )
                        console.print(Panel(
                            details or "The AI could not provide more detail.",
                            title=f"[bold magenta]AI DETAILS[/bold magenta]  [dim]{details_elapsed:.2f}s[/dim]",
                            border_style="magenta",
                        ))
                    except Exception as exc:
                        console.print(Panel(
                            f"Could not get more details: {type(exc).__name__}: {exc}",
                            title="[bold red]CLARIFICATION ERROR[/bold red]",
                            border_style="red",
                        ))
                    break

                if choice == "n":
                    console.print("[dim]Okay — please rephrase the request.[/dim]")
                    break

                fields = {}
                for line in suggestion.splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        fields[key.strip().lower()] = value.strip()

                meaning = fields.get("meaning", suggestion)
                suggested_server = fields.get("server")
                suggested_command = fields.get("command")

                if suggested_server in servers and suggested_command and suggested_command.lower() != "unknown":
                    if choice == "a":
                        knowledge.add(user, meaning, suggested_server, suggested_command)
                        console.print(Panel(
                            f"Saved this interpretation for future requests.\\n\\n"
                            f"Phrase: {user}\\nServer: {suggested_server}\\nCommand: {suggested_command}",
                            title="[bold green]ADDED TO KNOWLEDGE BASE[/bold green]",
                            border_style="green",
                        ))
                    if policy.is_allowed(suggested_server, suggested_command) or policy.request(
                        suggested_server, suggested_command
                    ):
                        tool_result = _run_command(
                            ssh, servers, suggested_server, suggested_command,
                            f"Executing on {suggested_server}…",
                        )
                        _show_direct_answer(tool_result)
                    else:
                        console.print(Panel(
                            "Command denied by user.",
                            title="[bold yellow]COMMAND DENIED[/bold yellow]",
                            border_style="yellow",
                        ))
                    break

                console.print(Panel(
                    "The AI suggestion did not contain a usable server and command, so nothing was executed.",
                    title="[bold yellow]NO EXECUTABLE INTERPRETATION[/bold yellow]",
                    border_style="yellow",
                ))
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
                tool_result = {"ok": False, "error": f"Unsupported tool requested: {name!r}"}
                console.print(Panel(
                    tool_result["error"],
                    title="[bold red]UNSUPPORTED TOOL[/bold red]",
                    border_style="red",
                ))
                messages.append({"role": "tool", "content": json.dumps(tool_result)})
                continue

            args = _parse_tool_arguments(function)
            if args is None:
                tool_result = {"ok": False, "error": "Malformed tool arguments; expected a JSON object."}
                console.print(Panel(
                    tool_result["error"],
                    title="[bold red]INVALID TOOL ARGUMENTS[/bold red]",
                    border_style="red",
                ))
                messages.append({"role": "tool", "content": json.dumps(tool_result)})
                continue

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
                tool_result = _run_command(
                    ssh, servers, server_name, command,
                    f"Executing on {server_name}…",
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
            _show_direct_answer(tool_result)
            break
