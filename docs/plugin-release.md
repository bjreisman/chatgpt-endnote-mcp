# EndNote Research 1.4.6 release validation

This is the historical 1.4.6 validation record. For the 1.4.7 Windows candidate,
see [Windows validation and release gates](windows-acceptance.md). No 1.4.7 release
has been published; do not treat historical macOS checks as Windows acceptance.

This release adds local plugin metadata/icons, a setup onboarding skill, an
explicit uv runtime installer, and a distributable plugin ZIP. Installation reads
runtime source from the installed plugin copy. Server startup does not install
software. The default indexing flow is incremental and preserves configuration.

## Completed automated validation

- Full local suite: 145 tests pass. Wheel, source distribution and plugin ZIP build.
- A separate uv tool environment installed the extracted ZIP source, including a
  plugin path and library paths containing spaces, with current dependencies.
- Actual stdio sessions verified metadata/PDF search, citations, PDF page reads,
  restart, incremental updates and semantic fallback without optional packages.
  Retrieval left the index unchanged; failed XML import preserved the prior index.
- Setup preserved existing configuration. Tests cover missing uv/export paths,
  interrupted indexing and optional semantic dependencies.
- Codex's plugin reader recognizes both skills, the server and display assets.
  This is a manifest check, not an installed desktop onboarding check.
- The ZIP includes source, launcher, installer, both skills and icons, with no
  personal library, local configuration or database files.
- GitHub Actions was previously active but had no recorded runs. Manual dispatch
  and branch triggers now allow verification; the first dispatched matrix passed
  all eight macOS/Linux and Python 3.10–3.13 jobs.

Fresh dependency testing exposed a PyMuPDF compatibility-alias warning on stdout.
The runtime now imports `pymupdf` (minimum 1.24.3), and a regression test protects
the stdio channel. The repeated packaged runtime check had no JSON-RPC parse errors.

## Desktop acceptance gate

Before publishing a stable release, test with a fresh macOS Codex profile with no
EndNote runtime, configuration or direct MCP registration:

1. Install the release ZIP through its local marketplace. Confirm both skills
   appear and only one `endnote` MCP connection is enabled.
2. Ask “Set up my EndNote library.” Select a synthetic XML export and PDF folder,
   including paths with spaces. Verify runtime installation, setup, indexing and
   doctor readiness. Restart the plugin/new chat after first setup.
3. Search metadata/PDF evidence, format a citation, read an attached PDF page,
   restart the plugin and repeat a search.
4. Update the export and ask “Index my EndNote library.” Verify changes appear.
5. Repeat setup with existing config and confirm it is preserved. Test missing uv,
   missing exports and interrupted indexing. Request semantic preparation
   separately and verify keyword/PDF search works without it.
6. Confirm the prior direct registration is absent/disabled and no source EndNote
   files were modified.

Synthetic CLI/package tests and Codex's plugin reader do not substitute for this
GUI acceptance test. Public-directory submission is a separate future task; this
local server's submission eligibility has not been confirmed.
