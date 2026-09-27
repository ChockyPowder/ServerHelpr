from pathlib import Path
import json


class Policy:
    def __init__(self, config: dict):
        self.config = config
        data_dir = Path(config.get("data_dir", "./data")).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "approved_commands.json"
        self.approved = self._load()

        self.base_allowed = set(
            config.get("policy", {}).get("allowed_commands", [])
        )
        configured = config.get("policy", {}).get("high_risk_patterns", [])
        built_in = [
            "ssh-keygen",
            "authorized_keys",
            "sshd_config",
            "useradd",
            "usermod",
            "userdel",
            "passwd ",
            "visudo",
            "/etc/sudoers",
            "/etc/sudoers.d/",
        ]
        self.high_risk = list(dict.fromkeys(configured + built_in))

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
        return any(pattern in command for pattern in self.high_risk)

    def is_unrestricted(self, server: str) -> bool:
        server_cfg = self.config.get("servers", {}).get(server, {})
        return bool(server_cfg.get("unrestricted", False))

    def is_allowed(self, server: str, command: str) -> bool:
        if self.is_unrestricted(server):
            return True

        if self.is_high_risk(command):
            return False

        if command in self.base_allowed:
            return True

        return command in set(self.approved.get(server, []))

    def request(self, server: str, command: str) -> bool:
        print()
        print("=" * 72)
        print(f"COMMAND REQUESTED on {server}")
        print("-" * 72)
        print(command)
        print("-" * 72)
        print("Y = allow once")
        print("A = allow and remember this exact command")
        print("N = deny")

        if self.is_high_risk(command):
            print("NOTE: This command is classified HIGH RISK and cannot be remembered.")

        while True:
            answer = input("Choice [Y/A/N]: ").strip().lower()
            if answer == "y":
                return True
            if answer == "n":
                return False
            if answer == "a":
                if self.is_high_risk(command):
                    print("High-risk commands must be approved each time.")
                    continue
                self.approved.setdefault(server, [])
                if command not in self.approved[server]:
                    self.approved[server].append(command)
                    self._save()
                return True
