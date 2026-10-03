# Cleanup record — 3 October 2026

## Retired integrations

The April bridge, local HTTP companion/gateway, OpenAI API web app, tunnel-backed
MCP server, old Claude setup CLI, and their runtime and tests were retired in
commit `56b2560`. Their source remains recoverable from checkpoint `895b5e2`.
No August 2026 commits were found in local history, so August provenance could
not be confirmed. The old indexing script, handoff, unused illustration and stale
build artifacts were also archived; the owner then manually deleted that archive.
The previous `server.json` was superseded by the explicitly marked future
registry template in `examples/server.registry.template.json`.

The cleanup was merged into GitHub `main` in PR #1. Conversational indexing skill
and README guidance were subsequently merged in PR #2.

## Packaging and configuration cleanup

Checkpoint `2f86173` preserves the tree before this cleanup. Root `plugin.json`
and `mcp.json` duplicated the Codex packaging and are now in the ignored local
`archive/packaging-consolidation/` folder for manual review/deletion. The active
package uses `.codex-plugin/plugin.json`, `.mcp.json`, the marketplace catalog at
`.claude-plugin/marketplace.json`, its launcher, and the bundled research skill.
The Claude-named marketplace is a supported Codex compatibility convention.

Unused companion/tunnel configuration fields, URL helpers, timeout settings,
and the unreferenced legacy configuration path have been removed. Older YAML
files can retain those keys: the desktop loader ignores them and still reads
only the active library paths and PDF page limit. The user's configuration and
index have not been edited.

## Preserved local data

EndNote source XML/PDFs, the separate desktop configuration/index, external
Claude configuration, the active virtual environment, and private `.local/`
research evidence remain untouched. Databases, PDFs, config, caches, build
artifacts and archives are ignored by Git and excluded from package builds.

## Verification

The first retirement cleanup passed 139 tests and real stdio metadata/PDF/semantic
search, citation and PDF-page retrieval; the database hash was unchanged. Wheel
and source package inventories excluded retired code and private data. A rebuilt
wheel passed synthetic setup/indexing/retrieval in a separate environment with
existing base dependencies. This was not fresh network dependency resolution.

The follow-up packaging/configuration cleanup is validated in its pull request.

- 141 active tests passed, including ignored legacy YAML settings and real stdio
  startup/search from a copied plugin directory with the consolidated manifests.
- Codex app-server's read-only `plugin/read` accepted the marketplace and found
  the bundled research skill and `endnote` MCP server without the root duplicates.
  The plugin was not installed into the user's profile during this inspection.
- Wheel and source distributions rebuilt; inventories included the active plugin
  files and excluded the duplicate root manifests, archive and private data.
- The rebuilt wheel was reinstalled offline in the separate package-validation
  environment and passed synthetic stdio search; its database hash was unchanged.
- Desktop GUI plugin installation and fresh network dependency resolution were
  not part of this validation.
