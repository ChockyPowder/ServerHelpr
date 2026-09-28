# ServerHelpr

A local-first AI infrastructure agent for Debian/Linux servers.

## What it is

ServerHelpr is an AI agent, not a phrase-to-command chatbot. The local model is the reasoning brain. It can understand natural-language requests, investigate systems, use specialized capabilities, perform multi-step work, verify changes, and remember useful infrastructure knowledge.

## Agent loop

```
understand
   |
   v
recall memory
   |
   v
investigate
   |
   v
choose tool
   |
   v
execute
   |
   v
inspect result
   |
   +----> more work ----+
   |                    |
   v                    |
verify <----------------+
   |
   v
remember useful knowledge
   |
   v
answer
```

A single user request can therefore require many tool steps.

## Persistent memory

Memory is stored locally in `data/knowledge.json`.

It stores structured knowledge rather than exact user phrases:

- `server_fact` — facts about a server, service, application, paths, configuration, etc.
- `procedure` — reusable ways of accomplishing a task
- `preference` — user or infrastructure preferences
- `lesson` — corrections and useful experience

Memory is supplied to the model when relevant and can also be searched explicitly with the memory tools.

Memory is evidence, not absolute truth. Volatile facts should be checked again.

Passwords, private keys, API keys, tokens and other obvious secrets are rejected by the memory tool.

## Tools

The model can currently use:

- server information
- network information
- process inspection
- systemd service status/start/stop/restart
- Debian package status/install/update/upgrade
- disk usage
- memory usage
- directory listing
- file reading/writing
- file searching
- arbitrary shell commands
- persistent memory recall/storage

The tool layer is intentionally extensible.

## Multi-step example

For:

`change the current nginx website to a blue background and restart nginx`

the agent should investigate the nginx configuration and website files, determine the active content, inspect the relevant HTML/CSS, make the requested change, validate it, restart nginx if appropriate, verify nginx, verify the resulting website files, and remember useful discoveries.

It is not limited to one command per request.

## Safety

- Only configured servers are accessible.
- The model never receives SSH private keys.
- Every server command passes through the policy/approval layer.
- Restricted servers require approval for commands not already allowed.
- High-risk command patterns require interactive approval and cannot be permanently remembered.
- A server configured with `unrestricted: true` only controls SSH execution privileges; changes still require approval.
- Internet access is separate from server access. Every web search/page fetch requires interactive approval and web approval is never remembered.
- The model is not allowed to use `run_command` as an internet-access bypass; web research goes through the dedicated web tools.
- Failed commands are returned as evidence; the agent is instructed not to invent causes or perform unrelated cleanup.

## Requirements

- Python 3.11+
- Ollama
- A local model with tool/function-calling support
- SSH access to configured Linux servers

## Install

```bash
cp config.example.yaml config.yaml
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen3.5:4b
python3 -m serverhelpr
```

## Model

The model is configurable in `config.yaml`. Small models can emit tool calls as ordinary JSON text, so ServerHelpr includes recovery for that format. Stronger tool-calling models are recommended for complex multi-step tasks.
