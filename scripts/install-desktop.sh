#!/bin/sh
# Explicit onboarding only. Never called by the MCP launcher.
set -eu
semantic=false
replace=false
for argument in "$@"; do
  case "$argument" in
    --semantic) semantic=true ;;
    --replace) replace=true ;;
    --help) printf '%s\n' 'Usage: sh scripts/install-desktop.sh [--semantic] [--replace]' 'Install this plugin runtime with uv. --replace explicitly replaces an existing installation.'; exit 0 ;;
    *) printf '%s\n' "Unknown option: $argument" >&2; exit 2 ;;
  esac
done
if [ -n "${CHATGPT_ENDNOTE_MCP_UV:-}" ]; then
  uv_command=$CHATGPT_ENDNOTE_MCP_UV
  if [ ! -x "$uv_command" ]; then
    printf '%s\n' 'The configured uv executable is unavailable. Install uv or correct CHATGPT_ENDNOTE_MCP_UV.' >&2
    exit 127
  fi
elif command -v uv >/dev/null 2>&1; then
  uv_command=$(command -v uv)
elif [ -x "$HOME/.local/bin/uv" ]; then
  uv_command="$HOME/.local/bin/uv"
else
  printf '%s\n' 'uv is required. Install uv, then ask Codex to set up your EndNote library again.' >&2
  exit 127
fi
plugin_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
package=$plugin_root
if [ "$semantic" = true ]; then package="${plugin_root}[semantic]"; fi
if [ "$replace" = true ]; then
  "$uv_command" tool install --force "$package"
else
  "$uv_command" tool install "$package"
fi
bin_directory=$("$uv_command" tool dir --bin)
executable="$bin_directory/chatgpt-endnote-mcp"
if [ ! -x "$executable" ]; then
  printf '%s\n' "Installation did not produce $executable" >&2
  exit 1
fi
"$executable" --version
printf '%s\n' "Runtime executable: $executable" 'Next: configure your XML/PDF paths, index, and run doctor. Use the plugin MCP connection; no direct MCP registration is needed.'
