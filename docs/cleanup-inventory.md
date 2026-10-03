# Cleanup inventory — 3 October 2026

Scope: this project checkout only. No external Claude installation, EndNote files,
configuration, index, or GitHub repository is changed. Publication and runtime
verification wait until the owner reviews and manually deletes `archive/`.

## Provenance

The current branch is `codex/chatgpt-bridge-foundation`. Before this cleanup its
latest commit was `91cb249` (29 April 2026). The bridge and HTTP experiments were
introduced in April commits `4ccca76` and `91cb249`. No commits were found in
August 2026 across local refs; an August attempt cannot be independently dated
from this checkout. The current desktop implementation was uncommitted.
`origin` already points to `https://github.com/bjreisman/chatgpt-endnote-mcp.git`;
remote availability and authentication have not been checked.

## Move to archive (preserve original relative paths)

| Files | Reason |
| --- | --- |
| `src/endnote_mcp/bridge_client.py`, `bridge_models.py`, `companion.py`, `gateway.py` | April remote gateway/local HTTP companion experiment; not imported by desktop code. |
| `src/endnote_mcp/chat_app.py`, `chatgpt_local_server.py` | OpenAI API web app and tunnel-backed MCP experiment; not used by desktop stdio server. |
| `src/endnote_mcp/cli.py`, `server.py`, `tool_runtime.py` | Old CLI (including Claude configuration installer), MCP server and runtime; used only by the retired frontends. Current entry point is `desktop_cli:main`. |
| `tests/test_bridge.py`, `test_chat_app.py`, `test_chatgpt_local_server.py`, `test_cli.py` | Tests exclusively for the archived implementations. Desktop and shared core tests remain active. |
| `scripts/index_library.py` | Older indexing script, superseded by desktop CLI and staged indexing implementation. |
| `handoff.md` | April experiment handoff with obsolete commands and local setup details. |
| `assets/seahorse-extracellular-flux-analyzer.svg` | Unreferenced illustration, not included in the release configuration. |
| `dist/` | Existing generated wheel/source archive still include obsolete code; regenerate after verification. Ignored by Git. |
| `.DS_Store`, `src/.DS_Store` | Finder metadata. Ignored by Git. |

Files already missing before this work: tracked `server.json` was deleted in the
pre-existing working tree. Preserve its last committed contents in
`archive/prior-version/server.json` for review. The supported future registry
example remains in `examples/server.registry.template.json`.

## Keep

- Shared parser, database, PDF, embeddings, search, citation and configuration
  modules; desktop CLI/runtime/server and indexing; their tests.
- `.codex-plugin/`, `.claude-plugin/marketplace.json`, `plugin.json`, both MCP
  manifests, launcher and `skills/endnote-research/`: current plugin support.
  The Claude-named marketplace is referenced by the current Codex setup.
- License, citation metadata, fabricated examples and GitHub Actions workflow.
- `scripts/validate_research.py`: current stdio validation harness.
- `.venv/`: active project environment; preserve it for testing.
- `.local/`: ignored current research evidence and clean-install validation
  environments from October 3, not demonstrated August leftovers. May contain
  private library excerpts; do not commit or publish.
- `.pytest_cache/` and Python bytecode caches: ignored generated runtime files;
  not evidence of a retired integration. Leave for now.
- Legacy fields in shared `config.py`: inert compatibility fields; leave in
  place to keep this cleanup focused on retiring files.

## Accompanying housekeeping

Ignore root `archive/`, exclude it from pytest discovery, remove the retired
`experimental` dependency extra and its CI installation, and update README and
release metadata assertions. Source distribution already uses an explicit
include list that excludes `archive/`; wheel includes only the active package.

## Checkpoint and validation boundary

Make a local checkpoint of non-ignored source, including this inventory, before
moving any files. Ignored runtime/private data stay outside the commit. All moves
are reversible and their file hashes are recorded in `archive/manifest.json`.
The archived original `server.json` comes from `91cb249`. Keep this document after
manual deletion. Do not run the runtime suite until the owner deletes the archive
and resumes testing. A static import/reference and whitespace review is allowed
at this stage; it does not establish runtime correctness.

Checkpoint created: `895b5e2` (full hash in `archive/manifest.json`).
Archive moves completed and SHA256-verified; no files deleted. Runtime tests and
GitHub operations remain pending owner review and manual archive deletion.

## Post-deletion verification — 3 October 2026

The owner manually deleted `archive/` and authorized testing. Verified the folder
is absent. The checkpoint still preserves the retired source; the ignored
archived build/Finder artifacts were manually deleted and are not in Git.

- Full active suite: **139 passed**, no exclusions, in 4.79 seconds. Five
  dependency deprecation warnings came from PyMuPDF/SWIG imports.
- Real-library doctor: ready; 3,938 references, 65,830 PDF pages and 3,938
  reference embeddings. Seven existing attachment failures remain; cleanup did
  not reindex or alter attachments.
- Real stdio session listed all 11 tools, performed metadata, PDF-text and
  cached/offline semantic searches, citation formatting and a PDF-page read.
  Database SHA256 before/after was identical.
- Wheel and source distribution rebuilt. Inventories exclude retired modules,
  archive, private local evidence, databases, PDFs, configuration and bytecode.
  Source package now includes `docs/` to preserve the README inventory link.
- Rebuilt wheel installed offline into a separate environment inheriting base
  dependencies from the previous clean-install environment. Imports resolved to
  its installed wheel, not the source checkout. Synthetic setup and indexing,
  MCP initialization, search, semantic-unavailability reporting and shutdown
  passed. This is package validation, not a fresh network dependency resolution.
- Existing desktop registration was not changed; GUI interaction was not tested.
- GitHub read-only checks: authenticated as `bjreisman`, admin access to public
  `bjreisman/chatgpt-endnote-mcp`, default branch `main`. Remote `main` was
  `c9f5ec5`; remote `codex/chatgpt-bridge-foundation` was `91cb249`. Nothing pushed.

Proposed publication: push `codex/chatgpt-bridge-foundation` to `origin` without
force, open a pull request into `main`, and review hosted CI before merging.
GitHub write operations remain pending the owner's next instruction.
