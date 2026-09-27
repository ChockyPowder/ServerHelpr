# ServerHelpr

A local-first AI server operations assistant for Debian/Linux servers.

## Goals

- Run a local LLM through Ollama.
- Manage multiple Linux servers over SSH.
- Start in read-only mode.
- Ask for approval before executing unknown commands.
- Allow commands to be approved once or permanently.
- Keep the server inventory and policy locally.
- Never give the model direct shell access; the agent mediates every operation.

## Architecture

\`\`\`
You -> ServerHelpr -> Ollama
                  -> SSH -> Debian servers
                  -> policy/approval engine
\`\`\`

## Current status

This repository contains the initial MVP. It is deliberately conservative: SSH commands require an approval decision unless they are already in the configured allowlist.

## Requirements

- Python 3.11+
- Ollama
- A local model with tool/function-calling support
- SSH access to target servers

## Quick start

1. Copy the example config:

\`\`\`bash
cp config.example.yaml config.yaml
\`\`\`

2. Edit \`config.yaml\` with your servers and SSH key paths.

3. Install dependencies:

\`\`\`bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
\`\`

4. Pull a model in Ollama, for example:

\`\`\`bash
ollama pull qwen3.5:4b
\`\`

5. Start ServerHelpr:

\`\`\`bash
python3 -m serverhelpr
\`\`

## Approval model

When the model requests a command that is not approved, ServerHelpr displays the exact server and command.

- **Y** = allow this execution only.
- **A** = allow and remember this exact command for that server.
- **N** = deny.

Commands classified as high-risk always require an interactive confirmation even if they have previously been approved.

This project is intended for private infrastructure. Review commands before approving them.
