# EndNote Research 1.4.6 release validation

This release adds local plugin metadata/icons, a setup onboarding skill, an
explicit uv runtime installer, and a distributable plugin ZIP. Installation reads
runtime source from the installed plugin copy. Server startup does not install
software. The default indexing flow is incremental and preserves configuration.

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
