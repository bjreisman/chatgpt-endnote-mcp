#!/bin/sh
set -eu

if [ -n "${CHATGPT_ENDNOTE_MCP_COMMAND:-}" ]; then
  executable=$CHATGPT_ENDNOTE_MCP_COMMAND
elif command -v chatgpt-endnote-mcp >/dev/null 2>&1; then
  executable=$(command -v chatgpt-endnote-mcp)
elif [ -x "$HOME/.local/bin/chatgpt-endnote-mcp" ]; then
  executable="$HOME/.local/bin/chatgpt-endnote-mcp"
else
  printf '%s\n' "chatgpt-endnote-mcp was not found. Install it with: uv tool install 'git+https://github.com/bjreisman/chatgpt-endnote-mcp.git'" >&2
  exit 127
fi

exec "$executable" serve-desktop "$@"
