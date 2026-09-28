from pathlib import Path
import json
import re


class Policy:
    def __init__(self, config: dict):
        self.config = config
        data_dir = Path(config.get("data_dir", "./data")).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "approved_commands.json"
        self.approved = self._load()

        self.base_allowed = set(config.get("policy", {}).get("allowed_commands", []))
        configured = config.get("policy", {}).get("high_risk_patterns", [])
        built_in = [
            "ssh-keygen", "authorized_keys", "sshd_config",
            "useradd", "usermod", "userdel", "passwd ",
            "visudo", "/etc/sudoers", "/etc/sudoers.d/",
            "mkfs", "dd if=", "rm -rf", "shutdown", "reboot",
        ]
        self.high_risk = list(dict.fromkeys(configured + built_in))

        self.read_only_commands = {
            "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep",
            "find", "ls", "stat", "file", "pwd", "whoami", "hostname",
            "uname", "uptime", "free", "df", "du", "ps", "top", "pgrep",
            "pidof", "ss", "ip", "systemctl", "service", "journalctl",
            "dpkg", "apt-cache", "which", "whereis", "id", "getent",
            "mount", "lsblk", "lscpu", "lsmem", "env", "printenv",
        }

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self):
        self.path.write_text(
            json.dumps(self.approved, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def is_high_risk(self, command: str) -> bool:
        text = str(command or "")
        return any(pattern in text for pattern in self.high_risk)

    def _simple_command_read_only(self, command: str) -> bool:
        command = command.strip()
        if not command:
            return False
        command = re.sub(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)+", "", command)
        command = re.sub(r"^sudo\s+(?:-n\s+)?(?:--\s+)?", "", command)
        match = re.match(r"^([A-Za-z0-9_.+-]+)(?:\s|$)", command)
        if not match or match.group(1) not in self.read_only_commands:
            return False

        executable = match.group(1)
        mutating_subcommands = re.compile(
            r"\b(?:start|stop|restart|enable|disable|mask|unmask|reload|"
            r"install|remove|purge|upgrade|full-upgrade|update|"
            r"write|delete|set-property)\b"
        )
        if executable in {"systemctl", "service"} and mutating_subcommands.search(command):
            return False
        if executable == "dpkg" and re.search(r"\s(?:-i|--install|-r|--remove|-P|--purge)\b", command):
            return False
        if executable == "journalctl" and re.search(r"\s(?:--vacuum|--rotate)\b", command):
            return False
        return True

    def classify(self, command: str, tool_name: str | None = None) -> str:
        """Return read_only, normal_change, or high_risk."""
        if self.is_high_risk(command):
            return "high_risk"

        if tool_name in {
            "server_info", "network_info", "process_list", "service_status",
            "package_status", "disk_usage", "memory_usage", "list_directory",
            "read_file", "search_files", "recall_knowledge",
        }:
            return "read_only"

        if tool_name in {
            "service_action", "package_install", "package_update",
            "package_upgrade", "write_file",
        }:
            return "normal_change"

        if tool_name == "run_command":
            parts = re.split(r"\s*(?:&&|\|\||[;|])\s*", str(command or ""))
            parts = [part for part in parts if part.strip()]
            if parts and all(self._simple_command_read_only(part) for part in parts):
                return "read_only"

        return "normal_change"

    def is_unrestricted(self, server: str) -> bool:
        server_cfg = self.config.get("servers", {}).get(server, {})
        return bool(server_cfg.get("unrestricted", False))

    def is_allowed(self, server: str, command: str, tool_name: str | None = None) -> bool:
        if self.classify(command, tool_name) == "high_risk":
            return False
        if command in self.base_allowed:
            return True
        return command in set(self.approved.get(server, []))

    def is_remembered(self, server: str, command: str, tool_name: str | None = None) -> bool:
        if self.classify(command, tool_name) != "normal_change":
            return False
        return command in set(self.approved.get(server, []))

    def request_web(self, operation: str) -> bool:
        print()
        print("=" * 72)
        print("INTERNET ACCESS REQUEST")
        print("-" * 72)
        print(operation)
        print("-" * 72)
        print("Y = allow this web operation once")
        print("N = deny")
        print("NOTE: Internet access is never remembered.")
        while True:
            answer = input("Choice [Y/N]: ").strip().lower()
            if answer == "y":
                return True
            if answer == "n":
                return False

    def request(self, server: str, command: str, tool_name: str | None = None, preview: str | None = None) -> bool:
        classification = self.classify(command, tool_name)

        print()
        print("=" * 72)
        print(f"CHANGE REQUESTED on {server}")
        print("-" * 72)
        if preview:
            print(preview)
            print("-" * 72)
        print(f"Command: {command}")
        print("-" * 72)

        if classification == "high_risk":
            print("Y = allow once")
            print("N = deny")
            print("NOTE: HIGH RISK — this operation cannot be remembered.")
        else:
            print("Y = allow once")
            print("A = allow and remember this exact command")
            print("N = deny")

        while True:
            answer = input("Choice [Y/A/N]: ").strip().lower()
            if answer == "y":
                return True
            if answer == "n":
                return False
            if answer == "a":
                if classification == "high_risk":
                    print("High-risk operations must be approved each time.")
                    continue
                self.approved.setdefault(server, [])
                if command not in self.approved[server]:
                    self.approved[server].append(command)
                    self._save()
                return True
