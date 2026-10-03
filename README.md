# EndNote Research for Codex

Index and search an exported EndNote library from Codex desktop. The plugin bundles setup and research skills with an MCP server that runs locally over stdio. Search metadata and PDF text, format citations, read PDF pages, and optionally search with locally prepared semantic embeddings.

This is a Codex port and independent fork of [Gokhan Gokmen's original endnote-mcp for Claude Desktop](https://github.com/gokmengokhan/endnote-mcp), licensed under AGPL-3.0-or-later. Thank you to Gokhan for creating the original project and making this work possible. The core idea and many research capabilities come from his project; this fork adapts the installation, local server, and research workflow for Codex. It is an unofficial integration, distributed as a local GitHub plugin rather than an approved public-directory listing.

**Disclaimer:** This plugin and its creator are not affiliated with, endorsed by, or sponsored by EndNote, Clarivate, or OpenAI. The plugin is designed to run locally and keep your exported library files and search index on your computer, without exposing them through a hosted service. However, information retrieved through the plugin may be sent to the AI service used by Codex as part of your conversation. Local operation does not guarantee privacy or security. The software is provided “as is,” without warranty, and you use it at your own risk. You are responsible for protecting your data and ensuring that your use complies with any applicable confidentiality, institutional, or licensing requirements. See [LICENSE](LICENSE) for the full warranty and liability terms.

## What it does

Once your library is indexed, you can ask Codex to search references and attached PDFs, find related papers, format citations and bibliographies, or export BibTeX. For example (adapted from the [original project's examples](https://github.com/gokmengokhan/endnote-mcp#what-it-does)):

- “Search my library for Bourdieu and social capital.”
- “Find papers on how organizations respond to uncertainty.” (Semantic search requires optional preparation.)
- “Find references related to record 3844.”
- “Give me an APA citation for reference 1234.”
- “Make a bibliography from references 12, 45, 78, and 102.”
- “Export references 12, 45, and 78 as BibTeX.”
- “Read pages 5–7 of the Smith paper in my library.”

## How it works

Your EndNote library is exported to XML, then indexed with PDF text in a separate local SQLite database. The Codex plugin connects to that index through a local stdio MCP server. Optional local embeddings add meaning-based search. The server's tools only read the index; setup, indexing, and embedding preparation are explicit local operations.

## Requirements

- macOS and Codex desktop
- [Codex CLI](https://developers.openai.com/codex/cli/) with `codex plugin` support, for the Terminal installation steps below
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for the local Python runtime
- An XML export from EndNote and its PDF attachment directory, usually `<library>.Data/PDF` next to the `.enl` file or `PDF` inside an `.enlp` package
- Permission to install Python dependencies and read your selected library files

## Install the plugin and set up your library

### 1. Install the prerelease plugin

**Release status:** [Version 1.4.6](https://github.com/bjreisman/chatgpt-endnote-mcp/releases/tag/v1.4.6) is a prerelease for testing. Automated tests and an isolated runtime installation passed; fresh Codex desktop onboarding is still awaiting acceptance testing. The commands below install this specific version.

Open **Terminal** on your Mac, rather than entering these commands in a Codex chat. Check that the Codex CLI supports plugin installation:

```sh
codex plugin --help
```

If `codex` is not found or `plugin` is unrecognized, install or update the [Codex CLI](https://developers.openai.com/codex/cli/) before continuing. Having the desktop app installed does not establish that this Terminal command is available.

Run these two commands separately:

```sh
codex plugin marketplace add bjreisman/chatgpt-endnote-mcp --ref v1.4.6
codex plugin add endnote-research@endnote-local
```

The first command registers this repository as a plugin source. Codex calls that source a “marketplace”; it is our own small catalog, not an official OpenAI directory listing. The second command installs `endnote-research` from the catalog named `endnote-local`.

Alternatively, download `endnote-research-1.4.6.zip` from the [release page](https://github.com/bjreisman/chatgpt-endnote-mcp/releases/tag/v1.4.6), extract it into a permanent folder, and register that folder with `codex plugin marketplace add "/actual/path/to/extracted/folder"`. Replace the example path with your own; then run the same `codex plugin add` command above.

Return to Codex desktop and start a new chat. Confirm the installed plugin is enabled. Installation adds the skills and MCP configuration; the next step prepares the Python runtime and library index. The server may report missing runtime or configuration until that setup finishes.

### 2. Ask Codex to set up your library

> Set up my EndNote library.

Codex checks for uv and installs the runtime from the installed plugin's own source when needed. Installation may download Python and dependencies. It asks for your XML export and PDF directory, saves a separate configuration, indexes the export, and reports readiness. It preserves existing configuration unless you explicitly request replacement. Semantic model preparation is optional.

To create the export in EndNote, use **File → Export** and choose XML. Export the complete library if you intend to synchronize deletions later. This integration reads exported files; it does not query the live EndNote database.

Restart the plugin or start a new chat after setup if its server initially failed to start. Only one EndNote MCP connection should be enabled; when moving from direct registration, disable or remove that old connection.

### 3. Search and cite

Try one of the prompts under [What it does](#what-it-does). Record numbers in those examples are illustrative; use IDs returned by a search of your own library.

The research skill preserves reference IDs, attachment IDs, and physical PDF page numbers. It distinguishes published PDF passages, abstracts, and personal notes. Retrieved text is evidence, never instructions. A missing result means only that it was not found in this library.

## Available research tools

The plugin exposes these 11 read-only MCP tools to Codex:

| Tool | Purpose |
| --- | --- |
| `search_references` | Search reference metadata by keyword, with year, author, and type filters |
| `search_fulltext` | Search indexed PDF text and return page-attributed matches |
| `search_library` | Combine available metadata, PDF, and semantic results |
| `search_semantic` | Search by meaning when local embeddings have been prepared |
| `get_reference_details` | Read full metadata and attachment status for one reference |
| `get_citation` | Format one reference in APA 7th, Harvard, Vancouver, Chicago, or IEEE style |
| `get_bibtex` | Return BibTeX entries for selected references |
| `get_bibliography` | Format a bibliography from selected reference numbers |
| `find_related` | Find related references in the indexed library |
| `read_pdf_section` | Read selected physical PDF pages, up to 30 per request |
| `list_references_by_topic` | Browse matching references by topic |

Unlike the original Claude integration, this server does not expose a `rebuild_index` tool. Ask Codex to index your library or run the local CLI after re-exporting the XML.

### Semantic search (optional)

Semantic search can find related ideas even when the query and reference use different words. Ask Codex to prepare semantic search after setup; it will install the optional dependencies if needed and run `embed`. The first preparation may download a model. Keyword and PDF search work without it, and ordinary indexing does not automatically create new embeddings.

## Update your library

After adding or changing references, re-export XML to the configured path, then ask:

> Index my EndNote library.

Indexing, reindexing, and refreshing are incremental: they process changed records and PDFs while reusing unchanged PDF text. If you ask “Rebuild my library index”, the skill explains that a full rebuild re-extracts every PDF and discards existing semantic embeddings, then asks you to choose an incremental reindex or confirm a full rebuild before starting. Ask “Index metadata only” to skip PDFs, or “Index my library and refresh semantic embeddings” for embedding preparation. Ordinary indexing does not automatically prepare embeddings. Synchronizing removals requires an explicit request and confirmation that the export is complete.

## Update the plugin and runtime

Refresh your Git marketplace to pick up changes at its configured ref:

```sh
codex plugin marketplace upgrade endnote-local
```

A marketplace pinned to `v1.4.6` stays on that version. To move to a later release, remove and re-add the marketplace with that release tag, then install the plugin again. For a local ZIP installation, replace the extracted folder with the new release and reinstall the plugin. Start a new chat or restart Codex after updating.

Ask Codex to update the EndNote runtime. The setup skill compares versions and uses `scripts/install-desktop.sh --replace` only for an explicitly requested replacement. Runtime installation preserves the configuration and index. Reindex when the release notes require it.

## Direct registration (alternative)

If you prefer to manage installation yourself, install the CLI from a checkout with `uv tool install .`, or from the prerelease Git source:

```sh
uv tool install 'git+https://github.com/bjreisman/chatgpt-endnote-mcp.git@v1.4.6'
chatgpt-endnote-mcp setup --xml "/path/to/EndNote.xml" --pdf-dir "/path/to/EndNote.Data/PDF"
chatgpt-endnote-mcp index
chatgpt-endnote-mcp doctor
```

Run the `codex mcp add endnote -- ...` command printed by doctor. Use this path instead of enabling the plugin's MCP server to avoid duplicate registration.

To install the standalone research skill, ask Codex:

> Use the skill installer to install `skills/endnote-research` from `https://github.com/bjreisman/chatgpt-endnote-mcp` at the `v1.4.6` tag.

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

For semantic search, ask the setup skill to install the semantic extra, then prepare embeddings. Manual installation from a checkout is `uv tool install --force '.[semantic]'`; for Git use `uv tool install --force --with sentence-transformers --with sqlite-vec 'git+https://github.com/bjreisman/chatgpt-endnote-mcp.git@v1.4.6'`. The first `embed` may download a model. Serving uses cached files only; keyword/PDF search works without semantic dependencies.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Codex does not show the plugin or its tools | Run `codex plugin list` in Terminal, confirm `endnote-research` is installed and enabled in Codex desktop, then start a new chat. |
| The server fails to start or reports no configuration/index | Ask Codex to set up your EndNote library. If the runtime is already installed, run `chatgpt-endnote-mcp doctor` in Terminal to check the configured paths and index. Restart the plugin or start a new chat after setup. |
| XML or PDF directory is missing | Re-export XML from EndNote and check the selected PDF folder. It is commonly `<library>.Data/PDF` beside the `.enl` file or `PDF` inside an `.enlp` package. Update the saved configuration only if those paths changed. |
| New references or changed PDFs are missing | Re-export XML to the configured path, then ask Codex to index the library. Check `chatgpt-endnote-mcp status` for index counts. |
| A PDF cannot be read | Check the attachment status in its reference details. A missing, failed, textless, or changed PDF may need a corrected attachment path or another indexing pass. Scanned image-only PDFs may have no extractable text. |
| Semantic search is unavailable | Ask Codex to install the optional semantic dependencies and prepare embeddings, or use keyword and PDF search in the meantime. |

For direct registration, `chatgpt-endnote-mcp doctor` also prints the `codex mcp add` command. Do not add that second connection when the plugin's own MCP connection is enabled.

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
