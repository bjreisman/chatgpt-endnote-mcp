# Reviewed paper-session notes

This milestone generates cited entries for manual paste into EndNote Research
Notes. It reads the selected XML-derived index and PDF attachments, and stores
exact drafts in a separate local journal. It has no connection to the running
EndNote application, on either macOS or Windows. The eleven research tools stay
read-only; `preview_session_note` is the only additional tool and writes only the
local draft journal. There are no live save or undo tools.

## Review and paste

Ask Codex to draft a session note for a selected indexed reference. The preview
includes title, authors, year, DOI when available, dated provenance, cited
findings, and separate interpretation, questions, and hypotheses. It returns the
complete exact entry, a durable `note_id`, and an **unsaved** status.

Review the text and identify the matching paper in EndNote, then paste the entry
into that paper’s Research Notes yourself. Preserve existing notes when pasting.
The plugin cannot inspect current notes, verify the paste, or mark a draft as
saved to EndNote. No Automation permission or running EndNote process is needed
to generate or recover a draft.

Findings require at least one PDF or abstract citation. The tool checks attachment
membership, current fingerprints, physical PDF page bounds, and indexed evidence
text. Those checks validate a source location, not scientific support for a claim.
Personal sections may stand alone. Each item is limited to 6,000 characters and
the rendered entry to 20,000; excessive entries are rejected, never truncated.

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

## Durable drafts and recovery

`session-notes.sqlite3` and its OS lock live beside the selected configuration,
separately from `library.db`. They are created only by a note preview. The journal
stores exact text, draft inputs, indexed paper identity, source fingerprints, and
creation time. Unix permissions restrict access to the owner; this is local
library data and should be preserved if draft recovery is needed.

```sh
chatgpt-endnote-mcp note-show NOTE_ID --config /path/to/config.yaml
chatgpt-endnote-mcp note-show NOTE_ID --config /path/to/config.yaml --recovery
```

Use the exact configuration that created the draft. The first command returns
the full rendered entry; `--recovery` includes the stored inputs and provenance.
Recovery reads the journal without contacting EndNote or changing the index.
Existing prototype journals are preserved rather than migrated or deleted;
`--recovery` may include additional data previously stored by that prototype.
No old journal contents or configuration settings can activate a live connection.

After manually pasting and saving, export fresh XML and reindex to make the notes
available through ordinary research tools. The plugin continues using its previous
snapshot until then. Pasting does not change the local journal’s draft status.

## Validation and remaining acceptance

Tests exercise PDF-cited previews over real MCP stdio, exact Unicode/multiline
recovery in a separate CLI process, recovery after restarting the server,
configuration scoping, journal locking, and unchanged source/index bytes.
Regression coverage rejects live save/undo tools and verifies that legacy native
settings cannot cause a preview to invoke an external application.

Manual paste and preservation of existing formatted notes were exercised on a
disposable library on October 18, 2026. Those observations were made before the
live adapter was separated; the current draft-only packages require fresh checks.
Fresh-profile desktop chat presentation remains an outstanding acceptance check;
CLI/app-server discovery alone does not establish that result.

## Deferred AppleScript prototype

The complete previous implementation, tests, and investigation notes are preserved
on [codex/applescript-session-notes-prototype](https://github.com/bjreisman/chatgpt-endnote-mcp/tree/codex/applescript-session-notes-prototype).
It is future evaluation work and is excluded from this PR’s source tree and
packages. Do not merge that branch without a separate review of Unicode export
fidelity, full-library performance, application permissions, concurrent edits,
and any proposed write behavior. Issue #8 remains open for future integration.
