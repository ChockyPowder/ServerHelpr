import base64
import shlex


def _schema(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def build_tools(servers: dict) -> list:
    names = list(servers)
    server = {"type": "string", "enum": names, "description": "Configured target server."}
    path = {"type": "string", "description": "Absolute path on the target Linux server."}
    return [
        _schema("web_search", "Search the public internet for current information. Requires user approval every time and is never remembered.", {"query": {"type": "string", "description": "Web search query."}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ["query"]),
        _schema("web_fetch", "Fetch a public web page for research. Requires user approval every time and is never remembered.", {"url": {"type": "string", "description": "Public http or https URL to fetch."}}, ["url"]),
        _schema("server_info", "Collect basic OS, hostname, uptime, memory and root filesystem information.", {"server": server}, ["server"]),
        _schema("network_info", "Inspect network addresses and listening sockets.", {"server": server}, ["server"]),
        _schema("process_list", "List running processes, optionally filtered by a pattern.", {"server": server, "pattern": {"type": "string"}}, ["server"]),
        _schema("service_status", "Check whether a systemd service is installed and its current state.", {"server": server, "service": {"type": "string"}}, ["server", "service"]),
        _schema("service_action", "Start, stop or restart a systemd service. Only use for an explicitly requested change.", {"server": server, "service": {"type": "string"}, "action": {"type": "string", "enum": ["start", "stop", "restart"]}}, ["server", "service", "action"]),
        _schema("package_status", "Check a Debian package's installed state and version.", {"server": server, "package": {"type": "string"}}, ["server", "package"]),
        _schema("package_install", "Install a Debian package. This changes the server.", {"server": server, "package": {"type": "string"}}, ["server", "package"]),
        _schema("package_update", "Refresh Debian package indexes.", {"server": server}, ["server"]),
        _schema("package_upgrade", "Upgrade installed Debian packages. Use full=true for apt full-upgrade.", {"server": server, "full": {"type": "boolean"}}, ["server"]),
        _schema("disk_usage", "Show filesystem disk usage.", {"server": server, "path": path}, ["server", "path"]),
        _schema("memory_usage", "Show memory and swap usage.", {"server": server}, ["server"]),
        _schema("list_directory", "List a directory with metadata.", {"server": server, "path": path}, ["server", "path"]),
        _schema("read_file", "Read a text file before inspecting or modifying it.", {"server": server, "path": path, "max_bytes": {"type": "integer", "minimum": 100, "maximum": 50000}}, ["server", "path"]),
        _schema("write_file", "Replace a text file with supplied content. This changes the server.", {"server": server, "path": path, "content": {"type": "string"}}, ["server", "path", "content"]),
        _schema("search_files", "Search text under a directory with grep.", {"server": server, "path": path, "pattern": {"type": "string"}}, ["server", "path", "pattern"]),
        _schema("run_command", "Run one arbitrary shell command when no specialized capability covers the task. Policy still applies.", {"server": server, "command": {"type": "string"}}, ["server", "command"]),
        _schema("remember_knowledge", "Store a durable fact, procedure, preference or lesson. Never store secrets.", {"server": {"type": "string", "enum": names + ["global"]}, "type": {"type": "string", "enum": ["server_fact", "procedure", "preference", "lesson"]}, "subject": {"type": "string"}, "content": {"type": "string"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}}, ["server", "type", "subject", "content"]),
        _schema("recall_knowledge", "Search persistent ServerHelpr memory.", {"server": {"type": "string", "enum": names + ["global"]}, "query": {"type": "string"}}, ["server", "query"]),
    ]


def _q(value):
    return shlex.quote(str(value))


def command_for_tool(name: str, args: dict) -> str | None:
    if name == "server_info":
        return "hostname; uname -a; uptime; free -h; df -h /"
    if name == "network_info":
        return "hostname -I; ss -tulpn"
    if name == "process_list":
        p = args.get("pattern", "")
        return "ps auxww" if not p else f"ps auxww | grep -i -- {_q(p)} | grep -v grep"
    if name == "service_status":
        s = _q(args.get("service", ""))
        return f"systemctl is-enabled {s} 2>/dev/null; systemctl is-active {s}; systemctl status {s} --no-pager -l 2>&1 | head -80"
    if name == "service_action":
        return f"systemctl {args.get('action')} {_q(args.get('service', ''))}"
    if name == "package_status":
        return f"dpkg -s {_q(args.get('package', ''))}"
    if name == "package_install":
        return f"apt-get install -y {_q(args.get('package', ''))}"
    if name == "package_update":
        return "apt-get update"
    if name == "package_upgrade":
        return "apt-get full-upgrade -y" if args.get("full") else "apt-get upgrade -y"
    if name == "disk_usage":
        return f"df -h {_q(args.get('path', '/'))}"
    if name == "memory_usage":
        return "free -h"
    if name == "list_directory":
        return f"ls -la {_q(args.get('path', '/'))}"
    if name == "read_file":
        return f"head -c {int(args.get('max_bytes', 20000))} {_q(args.get('path', ''))}"
    if name == "write_file":
        encoded = base64.b64encode(str(args.get("content", "")).encode()).decode()
        return f"printf '%s' {_q(encoded)} | base64 -d > {_q(args.get('path', ''))}"
    if name == "search_files":
        return f"grep -RIn --exclude-dir=.git -- {_q(args.get('pattern', ''))} {_q(args.get('path', '.'))} | head -100"
    if name == "run_command":
        return str(args.get("command", "")).strip()
    return None


def tool_requires_command(name: str) -> bool:
    return name not in {"remember_knowledge", "recall_knowledge"}


READ_ONLY_TOOLS = {
    "server_info", "network_info", "process_list", "service_status",
    "package_status", "disk_usage", "memory_usage", "list_directory",
    "read_file", "search_files", "recall_knowledge",
}

MUTATING_TOOLS = {
    "service_action", "package_install", "package_update",
    "package_upgrade", "write_file", "run_command",
}

def tool_is_read_only(name: str) -> bool:
    return name in READ_ONLY_TOOLS

def tool_is_mutating(name: str) -> bool:
    return name in MUTATING_TOOLS
