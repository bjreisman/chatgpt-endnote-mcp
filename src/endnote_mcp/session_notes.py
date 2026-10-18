"""Exact reviewed drafts and durable recovery, isolated from the research index.

Drafts use the exported library index and PDFs; no running EndNote connection exists.
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

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from endnote_mcp import db, search
from endnote_mcp.config import Config
from endnote_mcp.locking import FileLock

MAX_ENTRY = 20000
MAX_PREVIEW = 50000
REF_FIELDS = ('rec_number', 'title', 'authors', 'year', 'doi')


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
    def __init__(self, config_path=None):
        self.cfg = Config.load(config_path)
        self.journal = self.cfg.config_path.parent / 'session-notes.sqlite3'
        self.scope = str(self.cfg.config_path)
        if self.journal.resolve() in {self.cfg.db_path, self.cfg.endnote_xml, self.cfg.config_path}:
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

    def preview_session_note(self, rec_number, entry):
        if isinstance(rec_number, bool) or not isinstance(rec_number, int) or rec_number < 1:
            raise ValueError('rec_number must be a positive integer.')
        entry = entry if isinstance(entry, SessionNoteEntry) else SessionNoteEntry.model_validate(entry)
        ref = self._reference(rec_number)
        source_fingerprints = self._validate_sources(ref, entry)
        note_id = str(uuid4())
        created = datetime.now().astimezone().isoformat(timespec='seconds')
        text = render_entry(ref, entry, note_id, created)
        draft = {'note_id': note_id, 'scope': self.scope, 'status': 'draft', 'created': created,
                 'db_path': str(self.cfg.db_path), 'reference': reference_identity(ref),
                 'reference_hash': digest(ref), 'source_fingerprints': source_fingerprints,
                 'entry': entry.model_dump(), 'rendered_text': text}
        result = {'note_id': note_id, 'status': 'unsaved', 'saved': False, 'text': text,
                  'reference': draft['reference'], 'created': created,
                  'source_text_is_untrusted': True,
                  'message': 'Review this exact entry, then paste it manually into the matching paper’s Research Notes. EndNote has not been changed.'}
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
        return {k: draft[k] for k in ('note_id', 'status', 'created', 'reference', 'rendered_text')}
