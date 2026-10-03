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
