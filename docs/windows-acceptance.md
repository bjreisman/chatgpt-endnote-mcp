# Windows 1.4.7 candidate validation

Target: Windows 11 x64, Windows PowerShell 5.1, Python 3.10–3.13.
The version is prepared for prerelease review, not published.

## Local results — October 3, 2026

- Windows 11 x64 (build 26100): core suite passed on Python 3.10 and 3.12.
  Latest Python 3.12 result: 179 passed, 9 skipped (seven Unix-platform
  tests, one unavailable symlink capability, one opt-in semantic test).
- Real semantic integration passed both from the checkout and from the extracted
  Windows ZIP installed with its PowerShell installer and semantic extra. Offline
  search and embedding refresh with an active reader were verified.
- Codex Desktop CLI/app-server 0.160.0 installed the candidate in an isolated
  profile and discovered all 11 tools with an embedded index. Environment
  forwarding and the 60-second startup allowance were exercised natively.
- A real Windows export indexed 3,483 references, 3,219 attachments and 56,406 PDF
  pages. Attachment results: 3,191 indexed, 21 textless, six unreadable PDFs and
  one exceeding the existing 200 MB limit; no attachments were missing.
- Packaged stdio acceptance passed 14 search/detail/citation/bibliography/BibTeX/
  page-read calls across two sessions, restart and live incremental reindexing.
  Retrieval preserved index bytes; the XML and sampled PDF hashes were unchanged.
- Wheel, sdist and both platform ZIPs build. Private inputs, configurations,
  indexes and reports remain in ignored local acceptance directories.

Still pending: execution of the GitHub Actions matrix on all configured platforms
and fresh-profile GUI onboarding in Codex desktop. Native CLI/app-server checks
do not establish GUI onboarding acceptance. Keep issue #4 open until both gates pass.

## Unix regression review — October 3, 2026

- Ubuntu under the existing local WSL installation, Python 3.12.3: final full
  suite passed with 174 passed and 14 skipped. This supplements, but does not
  replace, the macOS/Linux GitHub Actions matrix.
- Actual extracted Unix ZIP stdio initialization, metadata/PDF search, citations,
  page reading, unavailable-semantic fallback, restart and live incremental
  reindexing passed using synthetic fixtures.
- Separate-process checks passed for compatibility with the previous Unix
  manager's `flock` protocol and atomic publication while an existing reader
  retains the old database snapshot.
- Review found CRLF shell scripts in the Unix ZIP built from a Windows checkout.
  Packaging now normalizes `.sh` files to LF; `.gitattributes` also requests LF
  on checkout. A synthetic CRLF-source packaging test prevents recurrence.
- Windows targeted runtime, packaging and release checks after this fix:
  42 passed, 5 skipped. Both platform ZIPs were rebuilt.

No other Unix correctness regression was identified in review. Remaining changes
in behavior include a Python worker startup per extracted PDF and deliberately
stricter attachment validation: colon-containing Unix filenames are now rejected
by the shared alternate-data-stream safety rule. macOS execution and optional
semantic integration on Unix have not been rerun locally.

## Automated gates

- Full test matrix: Linux, macOS, Windows; Python 3.10–3.13.
- Windows real semantic dependency/model integration on Python 3.12.
- Native installer discovery, explicit replacement/semantic flags, failure handling,
  and native launcher executable discovery, arguments, Unicode streams and exit codes.
- Platform ZIPs, copied Windows ZIP stdio initialization, 11 tools, metadata/PDF
  search, citations, PDF reads, incremental update and server restart.
- Process-owned management locks, killed-manager recovery, active readers blocking
  publication, bounded failures preserving the previous index, and embedding refresh.
- Portable worker timeout, crash, cancellation, encrypted/corrupt/blank PDFs,
  nested separator formats, traversal/drive/UNC/ADS rejection and link containment.

Run the ordinary suite without semantic downloads:

```powershell
uv sync --extra dev
uv run pytest -q
uv run python -m hatchling build
uv run python scripts/build_plugin.py
uv run python scripts/build_plugin.py --platform windows
```

Run opt-in semantic integration with a separate local model cache if desired:

```powershell
uv sync --extra dev --extra semantic
$env:ENDNOTE_TEST_SEMANTIC = '1'
uv run pytest tests/test_semantic_integration.py -v
```

## Native Codex acceptance gate

`scripts/validate_windows.py` automates packaged stdio checks against a selected
real XML/PDF library using a new isolated output directory. It checks unchanged
XML and one sampled PDF and reports counts only. `scripts/validate_codex_plugin.py`
installs the extracted plugin into a fresh isolated Codex profile and verifies all
11 tools through the native Codex app-server, without creating chats or running a
model. These checks supplement the GUI gate below; they do not replace it.

1. Use a fresh Windows Codex profile with no EndNote connection. Install the
   extracted Windows ZIP's local marketplace; confirm both skills and one server.
2. Ask to set up an exported library. Verify the native installer, existing uv,
   setup/index/doctor, then restart the plugin/new chat after initial setup.
3. Search metadata and PDF evidence, format citations, and read PDF pages. Check
   physical page attribution, Unicode and spaced paths, nested attachments, and
   unchanged source XML/PDFs and database bytes after retrieval.
4. Keep the server running while reindexing an unchanged real export. Use a
   synthetic export to exercise changed records, interrupted imports and deletions.
   Restart and repeat searches. Existing configuration must be preserved.
5. Explicitly install optional semantic dependencies and prepare embeddings.
   Verify cached offline serving and refresh while readers are active; repeat the
   core workflow without semantic dependencies.
6. Record OS/runtime versions, counts, failure categories and readiness only.
   Store library paths/evidence and local configuration/index outside commits and
   public logs. Synthetic fixtures are the only committed test data.

## Upgrade and packaging

The default Git marketplace remains Unix. Windows installation uses
`endnote-research-1.4.7-windows.zip`; Unix uses `endnote-research-1.4.7.zip`.
Both ZIPs share source, plugin identity and version. Replace the marketplace source
when changing platform/version; enable only one EndNote connection.

The Windows manifest allows 60 seconds for startup. When embeddings exist, the
server initializes optional native semantic dependencies before opening stdio;
this avoids Windows initialization hangs with transport reader threads. Models
remain cached-only while serving. Core indexes skip semantic initialization.
Both manifests explicitly forward the runtime/configuration overrides, uv/XDG
executable directory settings, and optional model cache locations. This is
necessary because Codex stdio servers use an environment allowlist.

Restart all old runtimes before management after upgrade: legacy processes do not
participate in Windows reader/publication locking. Obsolete `.lock.d` directories
are not used by the new runtime; persistent `.lock` files are not stale ownership.
Configuration and index schema remain compatible; no migration is required.

Keep issue #4 open until CI and native Codex acceptance pass. Publishing a GitHub
prerelease or stable release is a separate action. The historical 1.4.6 validation
record does not establish Windows acceptance.

## Prepare the platform release for review

1. Run the complete CI matrix and the opt-in Windows semantic job on the candidate
   commit. Record failures and resolve them before claiming cross-platform support.
2. Build the wheel and sdist, then both ZIPs with `scripts/build_plugin.py` and
   `scripts/build_plugin.py --platform windows`. Build commands are the same in
   PowerShell and POSIX shells. Packaging normalizes shell scripts to LF even
   when the source distribution was built from a Windows checkout.
3. Test each extracted ZIP with its own manifest and installer. Windows uses
   PowerShell `-Replace`/`-Semantic` switches and the `.exe` printed by the installer;
   Unix uses shell `--replace`/`--semantic` switches and the extensionless executable.
   Preserve an existing configuration and index when replacing the runtime.
4. Complete desktop onboarding on macOS and Windows, with one EndNote connection
   enabled. Record counts and readiness only; keep library evidence private.
5. Review a prerelease containing both clearly named ZIPs and the wheel/sdist.
   Do not switch the Git marketplace manifest to Windows: that route stays Unix.
   Keep 1.4.6 installation commands labeled as the existing Unix prerelease until
   the new release is actually published. No tag, release, registry upload or
   issue closure is part of preparing the implementation PR.
