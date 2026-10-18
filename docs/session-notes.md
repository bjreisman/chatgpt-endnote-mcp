# Reviewed paper-session notes

This prototype delivers reviewed entries for manual paste. **Live saving and undo
are unavailable in the shipping adapter.** Issue #8 remains incomplete until
native write acceptance passes. The existing eleven research tools remain
read-only; three note tools explicitly advertise writes.

## Review and paste

Ask Codex to draft a session note for a selected reference. The preview includes
paper identity, DOI when available, a dated provenance line, cited findings,
and separate personal interpretation, questions, and hypotheses. It returns the
full exact entry, a durable `note_id`, and an **unsaved** status. Preview does not
change EndNote. Paste the reviewed text into that paper’s Research Notes yourself.
The plugin cannot verify a manual paste or mark it as a native save.

Findings require at least one PDF or abstract citation. The tool checks reference
membership, current attachment fingerprints, physical PDF page bounds, and
indexed evidence text. It does not determine whether a finding is scientifically
supported; that remains part of reading and review. Entries can contain personal
sections alone. Each item is limited to 6,000 characters and the rendered entry
to 20,000; excessive entries are rejected, never silently shortened.

Example `preview_session_note` input:

```json
{
  "rec_number": 42,
  "entry": {
    "findings": [{
      "text": "A finding supported by the passage you read.",
      "sources": [{
        "evidence_type": "pdf_text",
        "attachment_id": "ID returned by the research tools",
        "start_page": 3,
        "end_page": 4
      }]
    }],
    "interpretation": ["My interpretation of that finding."],
    "questions": ["What remains unclear?"],
    "hypotheses": ["An idea to test later."]
  }
}
```

An abstract citation is simply `{"evidence_type": "abstract"}`. The record and
attachment IDs above are illustrative. The MCP schema rejects other source types
and unknown fields. PDF indices refer to physical pages, not printed page labels.

## Optional native reads and the closed write gate

Native reads default off. To inspect eligibility, explicitly add these settings
to the selected configuration on macOS:

```yaml
native_notes_enabled: true
live_library: /absolute/path/to/Disposable Test Library.enl
```

This enables live **reads**, not permission to bypass the write gate. Serving and
ordinary research requests do not contact EndNote or create a note journal.
When a native preview is requested, EndNote must already be running with exactly
one open library matching that path. macOS may request Automation permission.
The helper neither opens nor closes libraries and never edits records.

The adapter resolves live references using a unique DOI candidate (or unique
title when DOI is absent), verifies title/year/authors and library path, and
captures the EndNote database identifier. It obtains full XML through the
in-memory `export … as "RSXML"` command. It never assumes that an exported record
number or the native ID’s session `database` component identifies the live paper.
The source export’s library path and database identifier must also agree with
the live target. Duplicate candidates, conflicting metadata, wrong/multiple libraries, denied
permission, and timeouts yield a copyable unsaved draft with the diagnostic.

EndNote 2025 exposes separate `field` and `set field` commands. No validated
atomic conditional field update is available through this adapter. A local lock
only excludes this plugin’s own requests, not edits from EndNote or other clients.
Rechecking before a separate write leaves a race in which a user’s edit could be
lost. Text replacement also has no validated formatting-preserving append/restore
behavior. Consequently **all native commits are refused**, including empty notes.
Whole-record replacement is not a fallback.

The recovery service is tested against a simulated atomic conditional writer.
Those tests establish the service contract, not AppleScript write safety. A future
adapter must demonstrate atomic conflict protection and faithful formatting before
its internal gate can open; no YAML setting currently opens that gate.

## Durable drafts and recovery

`session-notes.sqlite3` and its OS lock live beside the selected configuration,
separately from `library.db`. They are created only by a note operation. The
journal contains exact drafts and, when native reads succeed, full-record XML
preimages including formatted Research Notes. Unix permissions are restricted to
the owner. Preserve this journal if recovery is needed; it contains library data.

Recover the exact draft after restarting:

```sh
chatgpt-endnote-mcp note-show NOTE_ID --config '/path/to/config.yaml'
chatgpt-endnote-mcp note-show NOTE_ID --config '/path/to/config.yaml' --recovery
```

These commands read the journal without editing EndNote. Drafts are scoped to the
configuration that created them. Recovery output includes preimages, expected
postimages where applicable, and durable operation state.

A validated future writer uses `draft → saving → saved → undoing → undone` states.
Intent, faithful field postimages, and preimages are committed before any external
update. Citation fingerprints are pinned to the reviewed PDF versions. Retrying the same
ID reconciles a completed write without another append. Unknown read-back results
remain unresolved rather than being reported as saved; changed live fields block
retries and undo. Do not paste again while a native operation is unresolved.
Explicit undo restores only a matching postimage and retains recovery data on
conflict. Native save/undo requires an explicit user request after the exact draft
has been shown. Tool annotations are advisory; conversational approval is enforced
by the research workflow, not inferred from a caller-supplied boolean.

The XML/index remains a snapshot after native saves, undo, or manual paste. Export
fresh XML from EndNote before incremental reindexing; do not patch the index to
represent unexported edits.

## Disposable-library acceptance

The initial read-only probe on October 3, 2026 found seven records in the supplied
test library. Native IDs were library-scoped; field reads worked and XML export
included a database identifier and style markup. `record contents` returned no
usable result, so the adapter uses in-memory export. At that initial probe, the original and test libraries were both open.
A later isolated-fixture run succeeded with only the test library open: seven
records and eight attachments were indexed in metadata-only mode, the unsaved
draft captured a live XML preimage, and commit returned `native_safety_gate`.
No live records were changed.

To prepare an isolated fixture and exercise the draft and closed gate:

```sh
.venv/bin/python scripts/validate_session_notes.py --library '/absolute/path/to/Disposable Test Library.enl'
```

This script reads only the selected already-open library, then writes its XML,
configuration, index, draft, and report under ignored `.local/session-notes-test`.
Fixture capture may select the explicit test document among several open libraries;
production eligibility still requires only one. It never changes normal user
configuration or any live EndNote record.

Before claiming native acceptance, validate on a disposable library with only
that library open: database identity across reopen, formatted append and faithful
restore, pending and simultaneous edits, persistence after reopening, automation
denial, timeout/crash recovery, duplicate DOI and identity conflicts, and visible
verification in EndNote. Until a mechanism protects the check/write interval,
live write experiments remain blocked by the safety gate. Windows and ordinary
ChatGPT native saving are deferred; draft/manual-paste support is cross-platform.
