def build_tools(servers: dict) -> list:
    server_names = list(servers.keys())

    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run one shell command on exactly one configured Linux server. "
                    "Use this to inspect logs, services, CPU, memory, disk, Docker, "
                    "network state, or perform an approved administrative action."
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
