"""Exact reviewed drafts and durable recovery, isolated from the research index.

The shipping macOS adapter is read-only until its write safety gate passes.
A future writer must provide atomic conditional replacement and faithful styling.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import UUID, uuid4

from lxml import etree

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from endnote_mcp import db, search
from endnote_mcp.config import Config
from endnote_mcp.locking import FileLock
from endnote_mcp.native_notes import MacEndNoteAdapter, NativeNoteError, snapshot_from_xml

MAX_ENTRY = 20000
MAX_PREVIEW = 50000
REF_FIELDS = ('rec_number', 'title', 'authors', 'year', 'doi')
REFRESH = 'EndNote was updated. Search still uses the XML snapshot; export again before incremental reindexing.'


class SourceCitation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    evidence_type: Literal['pdf_text', 'abstract']
    attachment_id: str | None = Field(default=None, max_length=200)
    start_page: StrictInt | None = Field(default=None, ge=1)
    end_page: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def valid_source(self):
        if self.evidence_type == 'pdf_text':
            if not self.attachment_id or self.start_page is None:
                raise ValueError('PDF citations require an attachment_id and physical start_page.')
            if self.end_page is not None and self.end_page < self.start_page:
                raise ValueError('PDF page ranges must be ascending.')
            if (self.end_page or self.start_page) - self.start_page >= 30:
                raise ValueError('Cite at most 30 PDF pages per source.')
        elif any(v is not None for v in (self.attachment_id, self.start_page, self.end_page)):
            raise ValueError('Abstract citations cannot claim PDF attachments or pages.')
        return self


class Finding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=6000)
    sources: list[SourceCitation] = Field(min_length=1, max_length=20)


class SessionNoteEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    findings: list[Finding] = Field(default_factory=list, max_length=30)
    interpretation: list[str] = Field(default_factory=list, max_length=30)
    questions: list[str] = Field(default_factory=list, max_length=30)
    hypotheses: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def valid_content(self):
        texts = [f.text for f in self.findings] + self.interpretation + self.questions + self.hypotheses
        if not texts or any(not t.strip() or len(t) > 6000 or '\x00' in t for t in texts):
            raise ValueError('Supply nonblank content, at most 6000 characters per item, without NUL characters.')
        if sum(map(len, texts)) > MAX_ENTRY:
            raise ValueError('Session entry exceeds the 20000-character limit.')
        return self


def reference_identity(ref):
    return {k: ref.get(k) for k in REF_FIELDS}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def field_equal(a, b):
    return all(a.get(k) == b.get(k) for k in ('library_path', 'database_id', 'rec_number', 'notes_text', 'notes_xml'))


def same_target(a, b):
    return all(a.get(k) == b.get(k) for k in ('library_path', 'database_id', 'rec_number'))


def render_entry(ref, entry, note_id, created):
    lines = [f'--- Session note {note_id} ---', ref['title'],
             f"Authors: {'; '.join(ref['authors'])}", f"Year: {ref['year']}; DOI: {ref.get('doi') or 'not recorded'}",
             f"Indexed reference: {ref['rec_number']}", f'Date: {created}',
             'Provenance: Codex-assisted reading session; reviewed separately before any save.']
    if entry.findings:
        lines += ['', 'Published findings']
        for finding in entry.findings:
            citations = []
            for source in finding.sources:
                if source.evidence_type == 'abstract':
                    citations.append(f"reference {ref['rec_number']}, abstract only")
                else:
                    end = source.end_page or source.start_page
                    pages = str(source.start_page) if end == source.start_page else f'{source.start_page}–{end}'
                    citations.append(f"reference {ref['rec_number']}, attachment {source.attachment_id}, physical PDF page(s) {pages}")
            lines.append(f'- {finding.text}\n  Source: ' + '; '.join(citations))
    for title, values in [('Personal interpretation', entry.interpretation), ('Questions', entry.questions), ('Hypotheses', entry.hypotheses)]:
        if values:
            lines += ['', title, *['- ' + value for value in values]]
    lines.append(f'--- End session note {note_id} ---')
    result = '\n'.join(lines)
    if len(result) > MAX_ENTRY:
        raise ValueError('Rendered session entry exceeds 20000 characters; shorten it before previewing.')
    return result


class NoteService:
    def __init__(self, config_path=None, *, adapter=None):
        self.cfg = Config.load(config_path)
        self.adapter = adapter or (MacEndNoteAdapter(self.cfg.live_library) if self.cfg.native_notes_enabled else None)
        self.journal = self.cfg.config_path.parent / 'session-notes.sqlite3'
        self.scope = str(self.cfg.config_path)
        if self.journal.resolve() in {self.cfg.db_path, self.cfg.endnote_xml, self.cfg.config_path, self.cfg.live_library}:
            raise ValueError('The note journal must be separate from the index, source files, and configuration.')

    @contextmanager
    def _journal(self, create=False):
        if not create and not self.journal.exists():
            raise ValueError('Unknown note_id; preview a note first.')
        with FileLock(str(self.journal) + '.lock', timeout=0):
            # Exclusive creation restricts permissions before any sensitive data is written.
            if not self.journal.exists():
                fd = os.open(self.journal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            if os.name != 'nt':
                self.journal.chmod(0o600)
                Path(str(self.journal) + '.lock').chmod(0o600)
            with closing(sqlite3.connect(self.journal)) as conn:
                conn.execute('PRAGMA synchronous=FULL')
                conn.execute('PRAGMA journal_mode=DELETE')
                conn.execute('CREATE TABLE IF NOT EXISTS notes (note_id TEXT PRIMARY KEY, scope TEXT NOT NULL, data TEXT NOT NULL)')
                conn.commit()
                yield conn

    def _load(self, conn, note_id):
        try:
            UUID(note_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError('Invalid note_id.') from exc
        row = conn.execute('SELECT data FROM notes WHERE note_id=? AND scope=?', (note_id, self.scope)).fetchone()
        if row is None:
            raise ValueError('Unknown note_id for this configuration.')
        return json.loads(row[0])

    @staticmethod
    def _save(conn, draft):
        conn.execute('INSERT INTO notes VALUES (?,?,?) ON CONFLICT(note_id) DO UPDATE SET data=excluded.data',
                     (draft['note_id'], draft['scope'], json.dumps(draft, ensure_ascii=False)))
        conn.commit()

    def _reference(self, rec_number):
        with closing(db.connect_readonly(self.cfg.db_path)) as conn:
            ref = search.get_reference_details(conn, rec_number)
        if ref is None:
            raise ValueError('Reference not found in the selected index.')
        return ref

    def _validate_sources(self, ref, entry):
        from endnote_mcp.desktop_runtime import DesktopRuntime
        runtime = DesktopRuntime(self.cfg.config_path)
        fingerprints = {}
        with closing(db.connect_readonly(self.cfg.db_path)) as conn:
            if digest(search.get_reference_details(conn, ref['rec_number'])) != digest(ref):
                raise ValueError('Indexed reference changed while validating citations; preview again.')
            for finding in entry.findings:
                for source in finding.sources:
                    if source.evidence_type == 'abstract':
                        if not ref.get('abstract', '').strip():
                            raise ValueError('The reference has no indexed abstract.')
                        continue
                    row = conn.execute('SELECT * FROM attachments WHERE attachment_id=? AND rec_number=?',
                                       (source.attachment_id, ref['rec_number'])).fetchone()
                    if row is None:
                        raise ValueError('Citation attachment does not belong to this reference.')
                    attachment = runtime._attachment_status(row)
                    fingerprints[source.attachment_id] = attachment['fingerprint']
                    if attachment['status'] != 'indexed':
                        raise ValueError('Citation PDF is unavailable or changed; reindex before previewing.')
                    import pymupdf
                    with pymupdf.open(attachment['resolved_path']) as document:
                        if (source.end_page or source.start_page) > len(document):
                            raise ValueError('Citation exceeds the physical PDF page count.')
                    pages = conn.execute('SELECT page_number FROM pdf_pages WHERE attachment_id=? AND page_number BETWEEN ? AND ? AND trim(text_content) != ? ',
                                         (source.attachment_id, source.start_page, source.end_page or source.start_page, '')).fetchall()
                    if len(pages) != (source.end_page or source.start_page) - source.start_page + 1:
                        raise ValueError('Citation includes pages without indexed evidence text.')
        return fingerprints

    def _validate_export_binding(self, ref, live):
        """Bind the indexed paper's export to the explicitly configured live library."""
        matches = []
        try:
            for _, record in etree.iterparse(str(self.cfg.endnote_xml), events=('end',), tag='record',
                                             resolve_entities=False, no_network=True):
                if record.findtext('rec-number') == str(ref['rec_number']):
                    matches.append(etree.tostring(record, encoding='unicode'))
                record.clear()
                while record.getprevious() is not None:
                    del record.getparent()[0]
        except (OSError, etree.XMLSyntaxError) as exc:
            raise NativeNoteError('export_identity_unavailable', 'Cannot validate the source export identity; use manual paste.') from exc
        if len(matches) != 1:
            raise NativeNoteError('export_identity_unavailable', 'The source export no longer uniquely identifies the indexed record; reindex or use manual paste.')
        source = snapshot_from_xml('<xml><records>' + matches[0] + '</records></xml>', self.cfg.live_library, ref)
        if source['database_id'] != live['database_id']:
            raise NativeNoteError('identity_conflict', 'Export and live EndNote database identities differ; use manual paste.')

    def preview_session_note(self, rec_number, entry):
        if isinstance(rec_number, bool) or not isinstance(rec_number, int) or rec_number < 1:
            raise ValueError('rec_number must be a positive integer.')
        entry = entry if isinstance(entry, SessionNoteEntry) else SessionNoteEntry.model_validate(entry)
        ref = self._reference(rec_number)
        source_fingerprints = self._validate_sources(ref, entry)
        note_id = str(uuid4())
        created = datetime.now().astimezone().isoformat(timespec='seconds')
        text = render_entry(ref, entry, note_id, created)
        native = {'eligible': False, 'code': 'native_disabled', 'reason': 'Native saving is disabled; use manual paste.'}
        preimage = None
        if self.cfg.native_notes_enabled and self.adapter:
            try:
                preimage = self.adapter.snapshot(reference_identity(ref))
                self._validate_export_binding(reference_identity(ref), preimage)
                native = {'eligible': bool(self.adapter.safe_writes), 'code': 'ready' if self.adapter.safe_writes else 'native_safety_gate',
                          'reason': 'Validated native writer available.' if self.adapter.safe_writes else self.adapter.safety_reason}
            except NativeNoteError as exc:
                native = {'eligible': False, 'code': exc.code, 'reason': str(exc)}
        draft = {'note_id': note_id, 'scope': self.scope, 'status': 'draft', 'created': created,
                 'db_path': str(self.cfg.db_path), 'reference': reference_identity(ref),
                 'reference_hash': digest(ref), 'source_fingerprints': source_fingerprints,
                 'entry': entry.model_dump(), 'rendered_text': text,
                 'native': native, 'preimage': preimage, 'postimage': None}
        if preimage:
            old = preimage['notes_text']
            draft['intended_text'] = old + ('\n\n' if old else '') + text
            if native['eligible']:
                draft['intended_postimage'] = self.adapter.plan_replacement(preimage, draft['intended_text'])
                if (not same_target(preimage, draft['intended_postimage']) or
                        draft['intended_postimage']['notes_text'] != draft['intended_text']):
                    raise NativeNoteError('native_safety_gate', 'Adapter did not plan the exact reviewed replacement.')
        result = {'note_id': note_id, 'status': 'unsaved', 'saved': False, 'text': text,
                  'reference': draft['reference'], 'created': created, 'native': native,
                  'has_preimage': preimage is not None, 'source_text_is_untrusted': True,
                  'target': ({k: preimage[k] for k in ('library_path', 'database_id', 'rec_number')} if preimage else
                             {'library_path': str(self.cfg.live_library) if self.cfg.live_library else None, 'validated': False}),
                  'message': 'Review this exact entry. Request save explicitly, or paste it manually into Research Notes.'}
        if len(json.dumps(result, ensure_ascii=False)) > MAX_PREVIEW:
            raise ValueError('Complete preview exceeds the response limit; shorten the entry or metadata.')
        with self._journal(create=True) as conn:
            self._save(conn, draft)
        return result

    def show_session_note(self, note_id, recovery=False):
        """Read a committed journal snapshot without creating files or locking EndNote."""
        if not self.journal.is_file():
            raise ValueError('No session-note journal exists for this configuration.')
        uri = self.journal.resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            draft = self._load(conn, note_id)
        if recovery:
            return draft
        return {k: draft[k] for k in ('note_id', 'status', 'created', 'reference', 'rendered_text', 'native')}

    def _writer(self, draft):
        if not self.cfg.native_notes_enabled or self.adapter is None:
            raise NativeNoteError('native_disabled', 'Native saving is disabled; this draft remains unsaved.')
        if not self.adapter.safe_writes:
            raise NativeNoteError('native_safety_gate', self.adapter.safety_reason)
        if not draft['native']['eligible'] or not draft['preimage']:
            raise NativeNoteError('preview_required', 'This draft has no eligible native preview; preview again.')
        if str(self.cfg.live_library) != draft['preimage']['library_path']:
            raise NativeNoteError('wrong_library', 'Configured live library changed after preview.')
        if str(self.cfg.db_path) != draft['db_path']:
            raise NativeNoteError('stale_preview', 'Configured index changed after preview.')

    def commit_session_note(self, note_id):
        with self._journal() as conn:
            draft = self._load(conn, note_id)
            self._writer(draft)
            if draft['status'] in ('undoing', 'undone'):
                raise NativeNoteError('invalid_note_state', 'This entry is being undone or was undone; preview a new entry.')
            current = self.adapter.snapshot(draft['reference'])
            if not same_target(current, draft['preimage']):
                raise NativeNoteError('identity_conflict', 'Live record identity changed after preview.')
            if draft['status'] == 'saved':
                if not field_equal(current, draft['postimage']):
                    raise NativeNoteError('live_content_changed', 'This entry was saved, but live notes changed afterward. No retry write was made.')
                return self._saved_result(draft, already_saved=True)
            if draft['status'] == 'saving' and field_equal(current, draft['intended_postimage']):
                draft.update(status='saved', postimage=current)
                self._save(conn, draft)
                return self._saved_result(draft, already_saved=True)
            if not field_equal(current, draft['preimage']):
                raise NativeNoteError('stale_preview', 'Live notes changed; preview again. Recovery artifacts are retained.')
            ref = self._reference(draft['reference']['rec_number'])
            if digest(ref) != draft['reference_hash']:
                raise NativeNoteError('stale_preview', 'Indexed reference changed; preview again.')
            self._validate_export_binding(draft['reference'], current)
            if self._validate_sources(ref, SessionNoteEntry.model_validate(draft['entry'])) != draft['source_fingerprints']:
                raise NativeNoteError('stale_preview', 'A cited PDF changed after preview; preview again.')
            draft['status'] = 'saving'
            self._save(conn, draft)  # Durable preimage and intent precede the external operation.
            self.adapter.replace_notes(current, draft['intended_text'], notes_xml=draft['intended_postimage']['notes_xml'])
            verified = self.adapter.snapshot(draft['reference'])
            if not field_equal(verified, draft['intended_postimage']):
                raise NativeNoteError('write_uncertain', 'Read-back did not match. Do not paste or append again; retry this note_id to reconcile.')
            draft.update(status='saved', postimage=verified)
            self._save(conn, draft)
            return self._saved_result(draft)

    @staticmethod
    def _saved_result(draft, already_saved=False):
        return {'note_id': draft['note_id'], 'status': 'saved', 'saved': True,
                'already_saved': already_saved, 'message': REFRESH, 'refresh_required': True}

    def undo_session_note(self, note_id):
        with self._journal() as conn:
            draft = self._load(conn, note_id)
            self._writer(draft)
            if draft['status'] not in ('saved', 'undoing', 'undone'):
                raise NativeNoteError('invalid_note_state', 'Only a verified saved entry can be undone. Reconcile interrupted saves first.')
            current = self.adapter.snapshot(draft['reference'])
            if draft['status'] in ('undoing', 'undone') and field_equal(current, draft['preimage']):
                draft['status'] = 'undone'
                self._save(conn, draft)
                return {'note_id': note_id, 'status': 'undone', 'message': REFRESH, 'refresh_required': True}
            if draft['status'] == 'undone' or not field_equal(current, draft['postimage']):
                raise NativeNoteError('undo_conflict', 'Live notes changed after saving. Nothing was restored; recovery artifacts are retained.')
            draft['status'] = 'undoing'
            self._save(conn, draft)
            self.adapter.replace_notes(current, draft['preimage']['notes_text'], notes_xml=draft['preimage']['notes_xml'])
            verified = self.adapter.snapshot(draft['reference'])
            if not field_equal(verified, draft['preimage']):
                raise NativeNoteError('undo_uncertain', 'Restore read-back differs from the preimage; recovery artifacts are retained.')
            draft['status'] = 'undone'
            self._save(conn, draft)
            return {'note_id': note_id, 'status': 'undone', 'message': REFRESH, 'refresh_required': True}
