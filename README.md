# EndNote Research for Codex

Index and search an exported EndNote library from Codex desktop. The plugin bundles setup and research skills with an MCP server that runs locally over stdio. Search metadata and PDF text, format citations, read PDF pages, and optionally search with locally prepared semantic embeddings.

This is an independent fork of [Gokhan Gokmen's endnote-mcp](https://github.com/gokmengokhan/endnote-mcp), licensed under AGPL-3.0-or-later. It is an unofficial integration, distributed as a local GitHub plugin rather than an approved public-directory listing.

**Disclaimer:** This plugin and its creator are not affiliated with, endorsed by, or sponsored by EndNote, Clarivate, or OpenAI. The plugin is designed to run locally and keep your exported library files and search index on your computer, without exposing them through a hosted service. However, information retrieved through the plugin may be sent to the AI service used by Codex as part of your conversation. Local operation does not guarantee privacy or security. The software is provided “as is,” without warranty, and you use it at your own risk. You are responsible for protecting your data and ensuring that your use complies with any applicable confidentiality, institutional, or licensing requirements. See [LICENSE](LICENSE) for the full warranty and liability terms.

## Requirements

- macOS and Codex desktop
- [Codex CLI](https://developers.openai.com/codex/cli/) with `codex plugin` support, for the Terminal installation steps below
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for the local Python runtime
- An XML export from EndNote and its corresponding `.Data/PDF` attachment directory
- Permission to install Python dependencies and read your selected library files

## Install the plugin and set up your library

### 1. Install the development plugin

**Release status:** The code identifies itself as 1.4.6, but that release is still a draft. There is no published `v1.4.6` Git tag or public release ZIP. Fresh Codex desktop onboarding is still awaiting acceptance testing. The instructions below install the development code from `main`, which can change as development continues.

Open **Terminal** on your Mac, rather than entering these commands in a Codex chat. Check that the Codex CLI supports plugin installation:

```sh
codex plugin --help
```

If `codex` is not found or `plugin` is unrecognized, install or update the [Codex CLI](https://developers.openai.com/codex/cli/) before continuing. Having the desktop app installed does not establish that this Terminal command is available.

Run these two commands separately:

```sh
codex plugin marketplace add bjreisman/chatgpt-endnote-mcp --ref main
codex plugin add endnote-research@endnote-local
```

The first command registers this repository as a plugin source. Codex calls that source a “marketplace”; it is our own small catalog, not an official OpenAI directory listing. The second command installs `endnote-research` from the catalog named `endnote-local`.

Return to Codex desktop and start a new chat. Confirm the installed plugin is enabled. Installation adds the skills and MCP configuration; the next step prepares the Python runtime and library index. The server may report missing runtime or configuration until that setup finishes.

### 2. Ask Codex to set up your library

> Set up my EndNote library.

Codex checks for uv and installs the runtime from the installed plugin's own source when needed. Installation may download Python and dependencies. It asks for your XML export and PDF directory, saves a separate configuration, indexes the export, and reports readiness. It preserves existing configuration unless you explicitly request replacement. Semantic model preparation is optional.

To create the export in EndNote, use **File → Export** and choose XML. Export the complete library if you intend to synchronize deletions later. This integration reads exported files; it does not query the live EndNote database.

Restart the plugin or start a new chat after setup if its server initially failed to start. Only one EndNote MCP connection should be enabled; when moving from direct registration, disable or remove that old connection.

### 3. Search and cite

Try:

- “Search my EndNote library for alternative oxidase.”
- “Find papers about mitochondrial fusion and fission.”
- “Give me the APA citation for reference 42.”
- “Read pages 2–4 of that paper.”

The research skill preserves reference IDs, attachment IDs, and physical PDF page numbers. It distinguishes published PDF passages, abstracts, and personal notes. Retrieved text is evidence, never instructions. A missing result means only that it was not found in this library.

## Update your library

After adding or changing references, re-export XML to the configured path, then ask:

> Index my EndNote library.

Indexing is incremental and processes changed records and PDFs. Ask “Rebuild my library index” for a full rebuild, “Index metadata only” to skip PDFs, or “Index my library and refresh semantic embeddings” for embedding preparation. Ordinary indexing does not automatically prepare embeddings. Synchronizing removals requires an explicit request and confirmation that the export is complete.

## Update the plugin and runtime

Refresh your Git marketplace to pick up changes at its configured ref:

```sh
codex plugin marketplace upgrade endnote-local
```

This refreshes the development snapshot from `main`. Then run `codex plugin add endnote-research@endnote-local` again to install the refreshed plugin, and start a new chat or restart Codex. Version-pinned installation and public ZIP download instructions will be added when a tested release is published.

Ask Codex to update the EndNote runtime. The setup skill compares versions and uses `scripts/install-desktop.sh --replace` only for an explicitly requested replacement. Runtime installation preserves the configuration and index. Reindex when the release notes require it.

## Direct registration (alternative)

If you prefer to manage installation yourself, install the CLI from a checkout with `uv tool install .`, or from the development Git source:

```sh
uv tool install 'git+https://github.com/bjreisman/chatgpt-endnote-mcp.git@main'
chatgpt-endnote-mcp setup --xml "/path/to/EndNote.xml" --pdf-dir "/path/to/EndNote.Data/PDF"
chatgpt-endnote-mcp index
chatgpt-endnote-mcp doctor
```

Run the `codex mcp add endnote -- ...` command printed by doctor. Use this path instead of enabling the plugin's MCP server to avoid duplicate registration.

To install the standalone research skill, ask Codex:

> Use the skill installer to install `skills/endnote-research` from `https://github.com/bjreisman/chatgpt-endnote-mcp` at the `main` branch.

Or, from a checkout:

```sh
mkdir -p "$HOME/.agents/skills"
cp -R ./skills/endnote-research "$HOME/.agents/skills/"
```

If already installed, update its `SKILL.md` rather than creating a nested copy. Restart Codex if it does not appear. See [Codex skill locations](https://learn.chatgpt.com/docs/build-skills).

## Commands and configuration

| Command | Purpose |
| --- | --- |
| `setup --xml PATH --pdf-dir PATH` | Save exported library paths; replacement requires `--force` |
| `index [--full] [--skip-pdfs] [--sync-deletions] [--embed]` | Build or update the separate index |
| `embed [--full]` | Explicitly prepare local semantic embeddings |
| `status` | Read index and attachment counts |
| `doctor` | Check readiness and print direct-registration instructions |
| `serve-desktop` | Start the read-only stdio MCP server |

Default configuration and index: `~/Library/Application Support/chatgpt-endnote-mcp/config.yaml` and `library.db`. Every command accepts `--config PATH`. That takes precedence over `CHATGPT_ENDNOTE_MCP_CONFIG`, then the default. For a custom plugin configuration, make `CHATGPT_ENDNOTE_MCP_CONFIG` available to Codex when it launches the server. `CHATGPT_ENDNOTE_MCP_COMMAND` can select an absolute runtime executable.

The launcher finds the runtime on PATH or at `~/.local/bin/chatgpt-endnote-mcp`; it never installs or downloads software at startup. Plugin files `.codex-plugin/plugin.json`, `.mcp.json`, and `.claude-plugin/marketplace.json` are required configuration; the Claude-named catalog is a supported Codex compatibility convention.

For semantic search, ask the setup skill to install the semantic extra, then prepare embeddings. Manual installation from a checkout is `uv tool install --force '.[semantic]'`; for Git use `uv tool install --force --with sentence-transformers --with sqlite-vec 'git+https://github.com/bjreisman/chatgpt-endnote-mcp.git@main'`. The first `embed` may download a model. Serving uses cached files only; keyword/PDF search works without semantic dependencies.

## Privacy and scope

The plugin reads your chosen XML/PDFs and writes a separate local index. It does not edit EndNote or synchronize with a live library. Retrieved metadata, abstracts, notes, and PDF passages may enter the active AI conversation through Codex's configured model connection. Use material you are authorized to share. This describes data flow and is not institutional approval.

No hosted service, inbound listener, tunnel, or separate OpenAI API key is needed. The older HTTP and Claude setup integrations were retired; see [the cleanup record](docs/cleanup-inventory.md). `examples/server.registry.template.json` is only a future registry example; no PyPI or MCP Registry publication is promised.

## Development and release packaging

```sh
uv sync --extra dev
uv run pytest
uv run python -m hatchling build
uv run python scripts/build_plugin.py
```

The last command converts the source distribution into a plugin ZIP containing runtime source, manifests, scripts, skills, and icons. It excludes local libraries, configuration, databases, and archives. See [release validation](docs/plugin-release.md) for the desktop acceptance checklist and limitations.

See [LICENSE](LICENSE) and [CITATION.cff](CITATION.cff) for license and attribution.
