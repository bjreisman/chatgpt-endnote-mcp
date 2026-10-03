#!/bin/sh
set -eu

if [ -n "${CHATGPT_ENDNOTE_MCP_COMMAND:-}" ]; then
  executable=$CHATGPT_ENDNOTE_MCP_COMMAND
elif command -v chatgpt-endnote-mcp >/dev/null 2>&1; then
  executable=$(command -v chatgpt-endnote-mcp)
elif [ -x "$HOME/.local/bin/chatgpt-endnote-mcp" ]; then
  executable="$HOME/.local/bin/chatgpt-endnote-mcp"
else
  printf '%s\n' "EndNote runtime is not installed. Ask Codex: Set up my EndNote library." >&2
  exit 127
fi

exec "$executable" serve-desktop "$@"
