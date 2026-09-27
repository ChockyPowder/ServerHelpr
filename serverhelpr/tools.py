def build_tools(servers: dict) -> list:
    server_names = list(servers.keys())

    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run exactly one shell command on exactly one configured Linux server. "
                    "The command is executed with the permissions configured for that server. "
                    "For an explicitly unrestricted test sandbox, the command runs as root. "
                    "Use the smallest command that directly answers the user request. "
                    "Examples: hostname -> hostname; uptime -> uptime; current user -> whoami; "
                    "memory/RAM -> free -h; disk usage/space -> df -h. "
                    "Never add a second command when one command is sufficient."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {
                            "type": "string",
                            "enum": server_names,
                            "description": "Configured server name."
                        },
                        "command": {
                            "type": "string",
                            "description": "The exact shell command to execute."
                        }
                    },
                    "required": ["server", "command"]
                }
            }
        }
    ]
