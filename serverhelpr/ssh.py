import os

import paramiko


class SSHManager:
    def __init__(self, config: dict):
        self.config = config
        ssh_cfg = config.get("ssh", {})
        self.connect_timeout = int(ssh_cfg.get("connect_timeout", 10))
        self.command_timeout = int(ssh_cfg.get("command_timeout", 30))

    def run(self, server_name: str, server: dict, command: str) -> dict:
        key_path = server.get("key")
        if not key_path:
            raise ValueError(f"No SSH key configured for {server_name}")

        key_path = os.path.expanduser(os.path.expandvars(key_path))

        if not os.path.isfile(key_path):
            raise FileNotFoundError(
                f"SSH private key not found for {server_name}: {key_path}"
            )

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

        try:
            client.connect(
                hostname=server["host"],
                username=server["user"],
                key_filename=key_path,
                timeout=self.connect_timeout,
                banner_timeout=self.connect_timeout,
                auth_timeout=self.connect_timeout,
            )

            stdin, stdout, stderr = client.exec_command(
                command,
                timeout=self.command_timeout,
            )

            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            code = stdout.channel.recv_exit_status()

            return {
                "server": server_name,
                "command": command,
                "exit_code": code,
                "stdout": out[-12000:],
                "stderr": err[-12000:],
            }
        finally:
            client.close()
