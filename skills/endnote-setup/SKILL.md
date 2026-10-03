---
name: endnote-setup
description: Set up or update the local EndNote Research plugin when the user asks to set up their EndNote library, install its runtime, or configure exported library paths.
---

# Set up EndNote Research

Use this workflow for “Set up my EndNote library.” Explain that it installs a local Python runtime with uv when needed, reads an EndNote XML export and PDFs, and creates a separate local index. Relevant retrieved evidence can enter the AI conversation. It does not read the live EndNote database.

Locate the plugin root from this skill's installed path: `skills/endnote-setup/SKILL.md` is two directories below the root. Use that installed copy's `scripts/install-desktop.sh`; do not download an unrelated version. Quote all paths and command arguments.

Resolve the runtime using `CHATGPT_ENDNOTE_MCP_COMMAND`, `chatgpt-endnote-mcp` on PATH, or `~/.local/bin/chatgpt-endnote-mcp`. Compare its `--version` with `.codex-plugin/plugin.json`. For an absent runtime, the user's setup request authorizes running `sh PLUGIN_ROOT/scripts/install-desktop.sh`. This may download Python and package dependencies. If uv is absent, explain that prerequisite and stop until it is installed; do not silently install uv. For an older runtime, explain the replacement and run the installer with `--replace` only when the user requests or approves that update. Use `--semantic` only when semantic search preparation is requested. On failure, report the actual error; do not proceed as if installation succeeded. Use the absolute executable printed by the installer for subsequent commands.

Select the configuration used by the plugin: `CHATGPT_ENDNOTE_MCP_CONFIG` if set, otherwise the platform default (`~/Library/Application Support/chatgpt-endnote-mcp/config.yaml` on macOS). Pass an explicit `--config PATH` consistently if the user chooses another path, and explain that the same `CHATGPT_ENDNOTE_MCP_CONFIG` must be available to Codex when it starts the plugin server. Preserve any existing direct-registration config if the user is migrating. Never read Claude configuration automatically.

If configuration already exists, check its exported XML and PDF paths and reuse it. If the user wants different paths, ask for them and replace the config with `setup --force` only when that replacement is explicitly requested. If configuration is missing, ask for the XML export and corresponding `.Data/PDF` attachment directory, validate that they exist, then run:

```sh
chatgpt-endnote-mcp setup --xml XML_PATH --pdf-dir PDF_PATH
```

Use the resolved executable and selected configuration. Explain how to export XML from EndNote if needed; wait for the user to produce the export rather than inventing a path. Then run `index` without `--full` or `--sync-deletions`, followed by `doctor`. Allow indexing to finish and summarize counts, extraction failures/textless PDFs, and readiness. If indexing is interrupted or fails, report that and retry only after resolving the cause; the staged index preserves the prior database. Only run `embed` when requested; warn about the first model download, and install the semantic extra through the explicit runtime update if needed.

Use the bundled plugin MCP connection. Do not execute the direct `codex mcp add` command printed by doctor. If a previous direct registration exists, explain that only one EndNote connection should be enabled and ask before removing that registration. Restart the plugin or start a new chat after setup if it previously failed to start because the config/index was missing. Verify a metadata search using the plugin tools, then demonstrate citations and PDF reads where attachments are available.
