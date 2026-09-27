import json
import time

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .config import load_config
from .knowledge import KnowledgeBase
from .ollama import OllamaClient
from .policy import Policy
from .ssh import SSHManager
from .tools import build_tools, command_for_tool, tool_is_mutating


SYSTEM_PROMPT = """You are ServerHelpr, a local-first AI infrastructure agent.

You are the reasoning brain. Understand goals, investigate real systems, use tools, inspect results, complete multi-step tasks, verify changes, and remember durable knowledge.

WORKFLOW:
- Understand the complete user goal before acting.
- Use persistent memory as useful evidence, but verify volatile facts.
- Prefer specialized tools over run_command.
- You may take multiple tool steps for one request.
- Inspect every tool result before deciding the next step.
- Do not stop after a partial step when the user's requested task remains incomplete.
- For changes, verify the resulting state.
- If you discover durable server facts, reusable procedures, user instructions, or corrected knowledge, store them with remember_knowledge.
- Do not store secrets.

SAFETY:
- Only configured servers are accessible.
- Policy and approval are authoritative; never bypass them.
- A failed command is evidence of failure, not proof of an invented cause.
- Do not perform unrelated cleanup or remediation.
- Only change systems when the user requested the change or it is necessary to fulfill the explicit task.
- Never claim execution without tool evidence.
- Unrestricted configured test servers may execute without approval.
- Mutating tools require user approval before execution.
- If a read-only question needs a mutating tool, ask the user for permission instead of blocking the task.
- Never assume approval. The user must explicitly allow the proposed command.
- High-risk operations are always approved explicitly and cannot be remembered.

When a task needs investigation, investigate first. When a task needs modification, inspect before editing. When a task changes a service or file, verify afterwards.

TOOL USE EXAMPLES:
- "is nginx running" -> call service_status with service="nginx".
- "is nginx installed" -> call package_status with package="nginx".
- "what is the hostname" -> call server_info.
- "what is the IP" -> call network_info.
- "restart nginx" -> call service_action with service="nginx", action="restart", then verify with service_status.
Do not answer an infrastructure status/change question from memory when a tool can check the real server.
If your previous response did not execute a tool, correct that on the next step by selecting the appropriate tool.
"""



_MUTATION_PATTERNS = [
    r"\b(?:please\s+)?(?:start|stop|restart|reboot|shutdown|enable|disable)\b",
    r"\b(?:install|uninstall|remove|purge|upgrade|downgrade|update)\b",
    r"\b(?:change|modify|edit|write|create|delete|replace|rename|move|copy)\b",
    r"\b(?:configure|reconfigure|repair|fix|restore|reset|set)\b",
]

_NEGATED_ACTION_PATTERNS = [
    r"\b(?:should|would|could|can)\s+(?:i|we)\b.*\b(?:start|stop|restart|reboot|shutdown|install|remove|upgrade|change|modify|edit|delete|configure|fix)\b",
    r"\bwhat\s+(?:would|will|happens?|happen)\b.*\b(?:if|when)\b",
]

def request_allows_mutation(user_text: str) -> bool:
    import re
    text = " ".join(str(user_text or "").lower().split())
    if not text:
        return False
    if any(re.search(pattern, text) for pattern in _NEGATED_ACTION_PATTERNS):
        return False
    return any(re.search(pattern, text) for pattern in _MUTATION_PATTERNS)


console = Console()


def spinner(label, fn):
    start = time.perf_counter()
    with console.status(Spinner("dots", text=f" {label}"), spinner_style="cyan"):
        value = fn()
    return value, time.perf_counter() - start


def parse_args(function):
    args = function.get("arguments", {})
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            value = json.loads(args)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
    return None


def embedded_call(content):
    text = (content or "").strip()
    if not text:
        return None
    candidates = [text]
    if "<tool_call>" in text and "</tool_call>" in text:
        candidates.insert(0, text.split("<tool_call>", 1)[1].split("</tool_call>", 1)[0].strip())
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("name"), str) and isinstance(obj.get("arguments", {}), dict):
            return {"name": obj["name"], "arguments": obj.get("arguments", {})}
    return None


def execute(ssh, servers, server, command, tool_name):
    console.print(Panel(
        f"[bold]Tool:[/bold] {tool_name}\n[bold]Target:[/bold] {server}\n[bold]Command:[/bold] {command}",
        title="[bold yellow]AI TOOL REQUEST[/bold yellow]", border_style="yellow",
    ))
    try:
        result, elapsed = spinner(f"Executing {tool_name} on {server}…",
                                  lambda: ssh.run(server, servers[server], command))
        result["ok"] = result.get("exit_code") == 0
        result["elapsed"] = round(elapsed, 2)
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold")
        table.add_column()
        table.add_row("Exit", str(result.get("exit_code")))
        if result.get("stdout", "").strip():
            table.add_row("stdout", result["stdout"].strip())
        if result.get("stderr", "").strip():
            table.add_row("stderr", result["stderr"].strip())
        console.print(Panel(
            table,
            title="[bold green]COMMAND RESULT[/bold green]" if result["ok"] else "[bold red]COMMAND FAILED[/bold red]",
            border_style="green" if result["ok"] else "red",
        ))
        return result
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        console.print(Panel(error, title="[bold red]EXECUTION ERROR[/bold red]", border_style="red"))
        return {"ok": False, "exit_code": None, "error": error}


def memory_call(name, args, knowledge):
    if name == "recall_knowledge":
        server = None if args.get("server") == "global" else args.get("server")
        return {"ok": True, "matches": knowledge.search(args.get("query", ""), server, 8)}

    content = str(args.get("content", "")).strip()
    if not content:
        return {"ok": False, "error": "Cannot store empty knowledge."}
    lower = content.lower()
    if any(x in lower for x in ("password", "private key", "api key", "token", "secret")):
        return {"ok": False, "error": "Refused to store possible secret material."}

    server = None if args.get("server") == "global" else args.get("server")
    entry = knowledge.add(
        args.get("type", "lesson"), content, server, args.get("subject"),
        "ai", args.get("confidence", 0.8)
    )
    console.print(Panel(
        f"{entry['type']} [{entry.get('server') or 'global'}]\n{entry['content']}",
        title="[bold green]MEMORY STORED[/bold green]", border_style="green",
    ))
    return {"ok": True, "entry": entry}


def main():
    config = load_config()
    servers = config.get("servers", {})
    if not servers:
        raise SystemExit("No servers configured in config.yaml")

    ollama = OllamaClient(config)
    policy = Policy(config)
    ssh = SSHManager(config)
    knowledge = KnowledgeBase(config)
    tools = build_tools(servers)
    agent = config.get("agent", {})
    max_steps = int(agent.get("max_steps", 16))
    max_history = int(agent.get("max_history_messages", 20))

    console.print(Panel.fit(
        Text.assemble(Text("SERVERHELPR", style="bold cyan"), "\n",
                      Text("AI infrastructure agent", style="dim")),
        border_style="cyan", padding=(0, 2),
    ))
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Model", ollama.model)
    table.add_row("Ollama", f"context={ollama.num_ctx} max_output={ollama.num_predict} think={ollama.think}")
    table.add_row("Targets", ", ".join(servers))
    table.add_row("Memory", f"{len(knowledge.entries)} stored items")
    console.print(table)
    console.print("[dim]Type 'exit' to quit.[/dim]")

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

        server_hint = next((s for s in servers if s.lower() in user.lower()), None)
        memory = knowledge.context(user, server_hint)
        system = SYSTEM_PROMPT + "\n\nCONFIGURED SERVERS:\n" + json.dumps(list(servers))
        system += "\n\nRELEVANT MEMORY:\n" + memory

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

        last_call = None
        repeated_calls = 0
        forced_tool_retry = 0
        mutation_allowed = request_allows_mutation(user)
        successful_tool_executed = False

        for step in range(1, max_steps + 1):
            try:
                result, elapsed = spinner("Thinking / planning…", lambda: ollama.chat(messages, tools))
            except Exception as exc:
                console.print(Panel(
                    f"{type(exc).__name__}: {exc}",
                    title="[bold red]MODEL ERROR[/bold red]", border_style="red",
                ))
                break

            message = result.get("message", {})
            calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()
            if not calls:
                recovered = embedded_call(content)
                if recovered:
                    calls = [{"function": recovered}]
            messages.append(message)

            if not calls:
                # Once a tool has successfully executed, a natural-language response
                # is a valid completion. Do not force another tool call merely because
                # the small model did not emit a second tool call.
                if content and successful_tool_executed:
                    console.print(Panel(
                        content,
                        title=f"[bold cyan]AI RESPONSE[/bold cyan] [dim]{elapsed:.2f}s · {step} step(s)[/dim]",
                        border_style="cyan",
                    ))
                    break
                if content and forced_tool_retry < 1:
                    forced_tool_retry += 1
                    messages.append({
                        "role": "user",
                        "content": (
                            "STOP. Continue the infrastructure request with exactly one appropriate tool. "
                            "Use the real configured server and inspect actual state. "
                            "If the user's request is read-only/status-only, select ONLY a read-only "
                            "inspection tool; do not start, stop, restart, install, update, upgrade, "
                            "write, delete, or run an arbitrary command. If the previous tool failed, "
                            "choose another appropriate inspection tool or correct its arguments."
                        ),
                    })
                    console.print(Panel(
                        "Model produced an answer without executing a tool; requesting an actual tool action.",
                        title="[bold yellow]AGENT TOOL WATCHDOG[/bold yellow]",
                        border_style="yellow",
                    ))
                    continue
                if content:
                    console.print(Panel(
                        content,
                        title=f"[bold cyan]AI RESPONSE[/bold cyan] [dim]{elapsed:.2f}s · {step} step(s)[/dim]",
                        border_style="cyan",
                    ))
                else:
                    console.print(Panel(
                        "The model returned no tool call or answer.",
                        title="[bold red]AI RESPONSE ERROR[/bold red]", border_style="red",
                    ))
                break

            call = calls[0]
            function = call.get("function", {})
            name = function.get("name")
            args = parse_args(function)

            call_signature = json.dumps(
                {"name": name, "arguments": args}, sort_keys=True, ensure_ascii=False
            )
            if call_signature == last_call:
                repeated_calls += 1
            else:
                repeated_calls = 0
            last_call = call_signature

            if repeated_calls >= 2:
                tool_result = {
                    "ok": False,
                    "error": (
                        "The agent repeated the exact same tool call three times. "
                        "Do not repeat it. Re-evaluate the request and choose another "
                        "tool or provide a final evidence-based answer."
                    ),
                }
                console.print(Panel(
                    f"{name} {json.dumps(args, ensure_ascii=False)}",
                    title="[bold red]REPEATED TOOL CALL BLOCKED[/bold red]",
                    border_style="red",
                ))
                messages.append({"role": "tool", "content": json.dumps(tool_result)})
                forced_tool_retry += 1
                continue
            if args is None:
                tool_result = {"ok": False, "error": "Malformed tool arguments. Return valid JSON arguments for the selected tool."}
            elif name not in {t["function"]["name"] for t in tools}:
                tool_result = {
                    "ok": False,
                    "error": f"Unknown tool {name!r}. Choose one of the advertised tools and call it again.",
                }
                console.print(Panel(
                    str(name),
                    title="[bold red]UNKNOWN TOOL REQUEST[/bold red]",
                    border_style="red",
                ))
            elif name in {"remember_knowledge", "recall_knowledge"}:
                tool_result = memory_call(name, args, knowledge)
            elif tool_is_mutating(name):
                server = args.get("server")
                command = command_for_tool(name, args)
                if server not in servers:
                    tool_result = {"ok": False, "error": f"Unknown server: {server!r}"}
                elif not command:
                    tool_result = {"ok": False, "error": f"Unsupported tool: {name!r}"}
                elif policy.is_remembered(server, command):
                    console.print(Panel(
                        f"[bold]Remembered approval[/bold]\nTool: [cyan]{name}[/cyan]\nTarget: [cyan]{server}[/cyan]\nCommand: [cyan]{command}[/cyan]",
                        title="[bold green]APPROVED POLICY[/bold green]", border_style="green",
                    ))
                    tool_result = execute(ssh, servers, server, command, name)
                    if tool_result.get("ok"):
                        successful_tool_executed = True
                else:
                    if policy.request(server, command):
                        tool_result = execute(ssh, servers, server, command, name)
                        if tool_result.get("ok"):
                            successful_tool_executed = True
                    else:
                        tool_result = {"ok": False, "error": "User denied execution of the mutating command."}
            else:
                server = args.get("server")
                command = command_for_tool(name, args)
                if server not in servers:
                    tool_result = {"ok": False, "error": f"Unknown server: {server!r}"}
                elif not command:
                    tool_result = {"ok": False, "error": f"Unsupported tool: {name!r}"}
                else:
                    console.print(Panel(
                        f"[bold]Step {step}/{max_steps}[/bold]\n"
                        f"Tool: [cyan]{name}[/cyan]\nTarget: [cyan]{server}[/cyan]\n"
                        f"Command: [cyan]{command}[/cyan]",
                        title="[bold cyan]AI PLAN[/bold cyan]", border_style="cyan",
                    ))
                    allowed = policy.is_allowed(server, command)
                    if not allowed:
                        allowed = policy.request(server, command)
                    if allowed:
                        tool_result = execute(ssh, servers, server, command, name)
                        if tool_result.get("ok"):
                            successful_tool_executed = True
                    else:
                        tool_result = {"ok": False, "error": "User denied execution by policy."}
                        console.print(Panel(
                            "Execution denied.",
                            title="[bold yellow]COMMAND DENIED[/bold yellow]", border_style="yellow",
                        ))

            messages.append({"role": "tool", "content": json.dumps(tool_result, ensure_ascii=False)})
            if len(messages) > max_history:
                messages = [messages[0]] + messages[-(max_history - 1):]
        else:
            console.print(Panel(
                f"Stopped after {max_steps} agent steps. The task may be incomplete.",
                title="[bold yellow]AGENT STEP LIMIT[/bold yellow]", border_style="yellow",
            ))
