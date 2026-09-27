def build_tools(servers: dict) -> list:
    server_names = list(servers.keys())

    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run one shell command on exactly one configured Linux server. "
                    "Use this only for the smallest command needed to answer the user's request. "
                    "Prefer read-only diagnostics. Do not create SSH keys, change SSH "
                    "configuration, manage users, or change credentials unless explicitly requested."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {
                            "type": "string",
                            "enum": server_names,
                            "description": "Configured server name."
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief user-facing explanation of why this command is needed. Do not include private chain-of-thought."
                        },
                        "command": {
                            "type": "string",
                            "description": "The exact shell command to execute."
                        }
                    },
                    "required": ["server", "command", "reason"]
                }
            }
        }
    ]
