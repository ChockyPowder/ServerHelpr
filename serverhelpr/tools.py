def build_tools(servers: dict) -> list:
    server_names = list(servers.keys())

    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run one shell command on exactly one configured Linux server. "
                    "The command is executed with the permissions configured for that server. "
                    "For an explicitly unrestricted test sandbox, the command runs as root. "
                    "Use this only for the smallest command needed to answer the user's request. "
                    "Do not invent extra commands after a command succeeds."
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
