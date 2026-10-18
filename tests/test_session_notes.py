"""Draft fidelity, citations, native gate, and conditional-writer recovery contract."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess

import pymupdf
import pytest
import yaml

from endnote_mcp import db
from endnote_mcp.config import Config
from endnote_mcp.desktop_runtime import DesktopRuntime
from endnote_mcp.locking import FileLock, IndexBusyError
from endnote_mcp.native_notes import MacEndNoteAdapter, NativeNoteError, snapshot_from_xml
from endnote_mcp.session_notes import NoteService, SessionNoteEntry


@pytest.fixture
def notes_env(tmp_path, sample_ref):
    database = tmp_path / 'index.db'
    ref = dict(sample_ref)
    ref.update(authors=json.dumps(ref['authors']), keywords=json.dumps(ref['keywords']))
    conn = db.connect(database)
    db.upsert_reference(conn, ref)
    conn.commit()
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.execute('PRAGMA journal_mode=DELETE')
    conn.close()
    xml = tmp_path / 'library.xml'
    xml.write_text(live_xml(sample_ref, str(tmp_path / 'Test.enl')).replace('<rec-number>7</rec-number>', '<rec-number>42</rec-number>').replace('db-id="stable"', 'db-id="stable-db"'))
    config = tmp_path / 'config.yaml'
    config.write_text(yaml.safe_dump({'endnote_xml': str(xml), 'pdf_dir': str(tmp_path), 'db_path': str(database)}))
    return config, sample_ref


def enable_native(config):
    data = yaml.safe_load(config.read_text())
    data.update(native_notes_enabled=True, live_library=str(config.parent / 'Test.enl'))
    config.write_text(yaml.safe_dump(data))


class ConditionalAdapter:
    """Only a simulated validated writer; shipping AppleScript cannot do this."""
    safe_writes = True
    safety_reason = ''

    def __init__(self, library, notes='Prior Ω notes\n"quoted"'):
        self.current = {'library_path': str(library), 'database_id': 'stable-db', 'rec_number': '7',
                        'notes_text': notes, 'notes_xml': '<research-notes><style face="bold">' + notes + '</style></research-notes>',
                        'record_xml': '<record>faithful preimage</record>'}
        self.writes = 0
        self.crash_after_write = False
        self.change_during_write = False
        self.bad_readback = False

    def snapshot(self, expected):
        return deepcopy(self.current)

    def plan_replacement(self, expected_snapshot, text):
        result = deepcopy(expected_snapshot)
        result['notes_text'] = text
        result['notes_xml'] = expected_snapshot['notes_xml'] + '<new>' + text[len(expected_snapshot['notes_text']):] + '</new>'
        return result

    def replace_notes(self, expected_snapshot, text, notes_xml=None):
        if self.change_during_write:
            self.current['notes_text'] += '\nConcurrent user edit'
            self.current['notes_xml'] += 'changed'
        if self.current != expected_snapshot:
            raise NativeNoteError('stale_preview', 'Atomic conditional update refused.')
        self.writes += 1
        self.current['notes_text'] = text
        # Simulate preserved prior runs plus a new text run, or faithful restore.
        self.current['notes_xml'] = notes_xml if notes_xml is not None else expected_snapshot['notes_xml'] + '<new>' + text[len(expected_snapshot['notes_text']):] + '</new>'
        if self.bad_readback:
            self.current['notes_text'] += 'unexpected edit'
        if self.crash_after_write:
            self.crash_after_write = False
            raise NativeNoteError('native_timeout', 'Interrupted after write.')


def service_with_writer(notes_env):
    config, _ = notes_env
    enable_native(config)
    adapter = ConditionalAdapter(config.parent / 'Test.enl')
    return NoteService(config, adapter=adapter), adapter


def load_draft(service, note_id):
    with service._journal() as conn:
        return service._load(conn, note_id)


def test_complete_preview_durable_private_and_index_untouched(notes_env):
    config, ref = notes_env
    before = {p.name: p.read_bytes() for p in config.parent.iterdir() if p.is_file()}
    service = NoteService(config)
    assert not service.journal.exists()
    entry = {'findings': [{'text': 'Résumé Ω "quotation"\nNext line', 'sources': [{'evidence_type': 'abstract'}]}],
             'interpretation': ['My reading'], 'questions': ['What changes?'], 'hypotheses': ['Possibly X']}
    result = service.preview_session_note(42, entry)
    assert result['status'] == 'unsaved' and result['saved'] is False
    assert all(v in result['text'] for v in ('Résumé Ω "quotation"\nNext line', 'abstract only', ref['doi'], 'Personal interpretation', 'Questions', 'Hypotheses', 'Provenance:', 'Date:'))
    assert result['native']['code'] == 'native_disabled'
    reopened = NoteService(config)
    draft = load_draft(reopened, result['note_id'])
    assert draft['rendered_text'] == result['text']
    assert draft['status'] == 'draft'
    if os.name != 'nt':
        assert service.journal.stat().st_mode & 0o777 == 0o600
    for name, content in before.items():
        assert (config.parent / name).read_bytes() == content
    with pytest.raises(NativeNoteError, match='disabled'):
        reopened.commit_session_note(result['note_id'])


@pytest.mark.parametrize('entry', [
    {}, {'questions': [' ']}, {'questions': ['a\x00b']}, {'unknown': []},
    {'findings': [{'text': 'No citation', 'sources': []}]},
    {'findings': [{'text': 'x', 'sources': [{'evidence_type': 'notes'}]}]},
    {'findings': [{'text': 'x', 'sources': [{'evidence_type': 'abstract', 'start_page': 1}]}]},
    {'findings': [{'text': 'x', 'sources': [{'evidence_type': 'pdf_text', 'attachment_id': 'a', 'start_page': True}]}]},
    {'questions': ['x' * 6001]}, {'questions': ['x' * 6000] * 4},
])
def test_invalid_entries_do_not_create_journal(notes_env, entry):
    service = NoteService(notes_env[0])
    with pytest.raises(ValueError):
        service.preview_session_note(42, entry)
    assert not service.journal.exists()


def test_rendered_size_rejected_without_truncation(notes_env):
    service = NoteService(notes_env[0])
    with pytest.raises(ValueError, match='Rendered'):
        service.preview_session_note(42, {'questions': ['x' * 5000] * 4})
    assert not service.journal.exists()


def add_pdf(config, ref=42, aid='paper'):
    cfg = Config.load(config)
    pdf = config.parent / 'paper.pdf'
    with pymupdf.open() as document:
        for _ in range(2):
            page = document.new_page()
            page.insert_text((72, 72), 'Published text')
        document.save(pdf)
    conn = db.connect(cfg.db_path)
    conn.execute('INSERT INTO attachments VALUES (?,?,?,?,?,?,?)', (aid, ref, 'paper.pdf', str(pdf), hashlib.sha256(pdf.read_bytes()).hexdigest(), 'indexed', ''))
    for page in (1, 2):
        db.insert_pdf_page(conn, ref, page, 'Published text', aid)
    conn.commit()
    conn.close()
    return pdf


def pdf_entry(aid='paper', start=1, end=2):
    return {'findings': [{'text': 'A finding', 'sources': [{'evidence_type': 'pdf_text', 'attachment_id': aid, 'start_page': start, 'end_page': end}]}]}


def test_pdf_physical_pages_and_attachment_membership(notes_env):
    config, _ = notes_env
    pdf = add_pdf(config)
    service = NoteService(config)
    result = service.preview_session_note(42, pdf_entry())
    assert 'physical PDF page(s) 1–2' in result['text']
    for entry in (pdf_entry('foreign'), pdf_entry(end=3), pdf_entry(start=2, end=1)):
        with pytest.raises(ValueError):
            service.preview_session_note(42, entry)
    pdf.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        service.preview_session_note(42, pdf_entry())


def test_missing_abstract_or_blank_pdf_page_rejected(notes_env):
    config, _ = notes_env
    add_pdf(config)
    with sqlite3.connect(Config.load(config).db_path) as conn:
        conn.execute("UPDATE references_ SET abstract='' WHERE rec_number=42")
        conn.execute("UPDATE pdf_pages SET text_content='' WHERE page_number=2")
    service = NoteService(config)
    with pytest.raises(ValueError, match='abstract'):
        service.preview_session_note(42, {'findings': [{'text': 'x', 'sources': [{'evidence_type': 'abstract'}]}]})
    with pytest.raises(ValueError, match='without indexed'):
        service.preview_session_note(42, pdf_entry())


def test_save_retry_deduplicates_and_undo_preserves_styled_preimage(notes_env):
    service, adapter = service_with_writer(notes_env)
    before = deepcopy(adapter.current)
    preview = service.preview_session_note(42, {'questions': ['Ω "quotes"\nnewlines']})
    assert preview['native']['eligible'] is True
    result = service.commit_session_note(preview['note_id'])
    assert result['saved'] and result['refresh_required']
    assert adapter.current['notes_text'] == before['notes_text'] + '\n\n' + preview['text']
    assert adapter.current['notes_xml'].startswith(before['notes_xml'])
    assert service.commit_session_note(preview['note_id'])['already_saved']
    assert adapter.writes == 1
    assert service.undo_session_note(preview['note_id'])['status'] == 'undone'
    assert adapter.current == before
    assert service.undo_session_note(preview['note_id'])['status'] == 'undone'
    assert adapter.writes == 2
    with pytest.raises(NativeNoteError, match='undone'):
        service.commit_session_note(preview['note_id'])


def test_stale_preview_and_edit_between_check_and_write(notes_env):
    service, adapter = service_with_writer(notes_env)
    draft = service.preview_session_note(42, {'questions': ['Question']})
    adapter.change_during_write = True
    with pytest.raises(NativeNoteError, match='Atomic conditional'):
        service.commit_session_note(draft['note_id'])
    assert adapter.writes == 0
    assert adapter.current['notes_text'].endswith('Concurrent user edit')
    assert load_draft(service, draft['note_id'])['status'] == 'saving'
    with pytest.raises(NativeNoteError, match='changed'):
        service.commit_session_note(draft['note_id'])


def test_crash_after_save_reconciles_across_service_restart(notes_env):
    service, adapter = service_with_writer(notes_env)
    draft = service.preview_session_note(42, {'questions': ['Q']})
    adapter.crash_after_write = True
    with pytest.raises(NativeNoteError, match='Interrupted'):
        service.commit_session_note(draft['note_id'])
    assert load_draft(service, draft['note_id'])['status'] == 'saving'
    restarted = NoteService(notes_env[0], adapter=adapter)
    assert restarted.commit_session_note(draft['note_id'])['already_saved']
    assert adapter.writes == 1


def test_crash_after_undo_reconciles(notes_env):
    service, adapter = service_with_writer(notes_env)
    before = deepcopy(adapter.current)
    draft = service.preview_session_note(42, {'questions': ['Q']})
    service.commit_session_note(draft['note_id'])
    adapter.crash_after_write = True
    with pytest.raises(NativeNoteError):
        service.undo_session_note(draft['note_id'])
    assert load_draft(service, draft['note_id'])['status'] == 'undoing'
    assert service.undo_session_note(draft['note_id'])['status'] == 'undone'
    assert adapter.current == before and adapter.writes == 2


def test_verification_failure_never_reports_saved_or_blindly_retries(notes_env):
    service, adapter = service_with_writer(notes_env)
    draft = service.preview_session_note(42, {'questions': ['Q']})
    adapter.bad_readback = True
    with pytest.raises(NativeNoteError) as error:
        service.commit_session_note(draft['note_id'])
    assert error.value.code == 'write_uncertain'
    assert load_draft(service, draft['note_id'])['status'] == 'saving'
    with pytest.raises(NativeNoteError) as error:
        service.commit_session_note(draft['note_id'])
    assert error.value.code == 'stale_preview' and adapter.writes == 1


def test_undo_conflict_retains_recovery_without_overwrite(notes_env):
    service, adapter = service_with_writer(notes_env)
    draft = service.preview_session_note(42, {'questions': ['Q']})
    service.commit_session_note(draft['note_id'])
    adapter.current['notes_xml'] += 'subsequent style edit'
    with pytest.raises(NativeNoteError) as error:
        service.undo_session_note(draft['note_id'])
    assert error.value.code == 'undo_conflict' and adapter.writes == 1
    assert load_draft(service, draft['note_id'])['preimage']['record_xml']


def test_index_and_target_changes_refuse_commit(notes_env):
    service, adapter = service_with_writer(notes_env)
    draft = service.preview_session_note(42, {'questions': ['Q']})
    with sqlite3.connect(service.cfg.db_path) as conn:
        conn.execute("UPDATE references_ SET title='Different paper' WHERE rec_number=42")
    with pytest.raises(NativeNoteError) as error:
        service.commit_session_note(draft['note_id'])
    assert error.value.code == 'stale_preview' and adapter.writes == 0
    adapter.current['database_id'] = 'another-db'
    with pytest.raises(NativeNoteError) as error:
        service.commit_session_note(draft['note_id'])
    assert error.value.code == 'identity_conflict'


def test_shipping_adapter_cannot_be_enabled_as_writer(notes_env, monkeypatch):
    config, _ = notes_env
    enable_native(config)
    service = NoteService(config)
    reader = ConditionalAdapter(config.parent / 'Test.enl')
    monkeypatch.setattr(service.adapter, 'snapshot', reader.snapshot)
    draft = service.preview_session_note(42, {'questions': ['Q']})
    assert draft['has_preimage'] and draft['native']['code'] == 'native_safety_gate'
    with pytest.raises(NativeNoteError) as error:
        service.commit_session_note(draft['note_id'])
    assert error.value.code == 'native_safety_gate'
    with pytest.raises(NativeNoteError):
        service.adapter.replace_notes({}, 'anything')
    assert reader.writes == 0


@pytest.mark.parametrize('code', ['multiple_libraries', 'wrong_library', 'automation_denied', 'native_timeout'])
def test_native_read_failure_still_produces_manual_draft(notes_env, code):
    service, adapter = service_with_writer(notes_env)
    def failed(expected):
        raise NativeNoteError(code, 'Unavailable')
    adapter.snapshot = failed
    draft = service.preview_session_note(42, {'questions': ['Q']})
    assert draft['status'] == 'unsaved' and draft['native']['code'] == code
    assert not draft['has_preimage']


def test_note_journal_excludes_another_process(notes_env):
    service = NoteService(notes_env[0])
    preview = service.preview_session_note(42, {'questions': ['Q']})
    with FileLock(str(service.journal) + '.lock'):
        with pytest.raises(IndexBusyError):
            service.commit_session_note(preview['note_id'])


def live_xml(ref, library='/test.enl', notes='<style face="bold">Ω</style>'):
    from xml.sax.saxutils import escape, quoteattr
    authors = ''.join('<author>' + escape(a) + '</author>' for a in ref['authors'])
    return ('<xml><records><record><database path=' + quoteattr(library) + '/><rec-number>7</rec-number>'
            '<foreign-keys><key app="EN" db-id="stable">7</key></foreign-keys><titles><title>' + escape(ref['title']) + '</title></titles>'
            '<dates><year>' + ref['year'] + '</year></dates><contributors><authors>' + authors + '</authors></contributors>'
            '<electronic-resource-num>' + ref['doi'] + '</electronic-resource-num><research-notes>' + notes + '</research-notes></record></records></xml>')


def test_xml_resolution_preserves_style_and_ignores_export_number(sample_ref):
    xml = live_xml(sample_ref)
    snapshot = snapshot_from_xml(xml, '/test.enl', sample_ref)
    assert snapshot['rec_number'] == '7' and sample_ref['rec_number'] == 42
    assert snapshot['notes_text'] == 'Ω' and 'face="bold"' in snapshot['notes_xml']
    assert snapshot['database_id'] == 'stable'
    record = xml.split('<records>')[1].split('</records>')[0]
    with pytest.raises(NativeNoteError) as error:
        snapshot_from_xml('<xml><records>' + record * 2 + '</records></xml>', '/test.enl', sample_ref)
    assert error.value.code == 'ambiguous_match'
    with pytest.raises(NativeNoteError) as error:
        snapshot_from_xml(xml, '/wrong.enl', sample_ref)
    assert error.value.code == 'wrong_library'
    with pytest.raises(NativeNoteError) as error:
        snapshot_from_xml(xml.replace(sample_ref['title'], 'Wrong'), '/test.enl', sample_ref)
    assert error.value.code == 'identity_conflict'


def test_without_doi_requires_unique_title_year_authors(sample_ref):
    ref = dict(sample_ref, doi='')
    assert snapshot_from_xml(live_xml(ref), '/test.enl', ref)['database_id'] == 'stable'
    with pytest.raises(NativeNoteError):
        snapshot_from_xml(live_xml(ref).replace('<year>2020', '<year>1999'), '/test.enl', ref)


def test_native_helper_uses_arguments_and_bounded_read_failures(monkeypatch):
    import endnote_mcp.native_notes as native
    monkeypatch.setattr(native.platform, 'system', lambda: 'Darwin')
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 1, '', 'ONE_LIBRARY_REQUIRED')
    monkeypatch.setattr(native.subprocess, 'run', run)
    adapter = MacEndNoteAdapter('/test "quotes" Ω.enl')
    with pytest.raises(NativeNoteError) as error:
        adapter.export_xml()
    assert error.value.code == 'multiple_libraries'
    assert calls[0][0][-1] == str(adapter.library_path) and calls[0][1]['shell'] is False
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('osascript', 30)
    monkeypatch.setattr(native.subprocess, 'run', timeout)
    with pytest.raises(NativeNoteError) as error:
        adapter.export_xml()
    assert error.value.code == 'native_timeout'


def test_runtime_note_errors_are_structured_and_no_startup_journal(notes_env):
    config, _ = notes_env
    runtime = DesktopRuntime(config)
    assert not (config.parent / 'session-notes.sqlite3').exists()
    result = runtime.invoke_tool('preview_session_note', {'rec_number': 42, 'entry': {'questions': ['Q']}})
    assert result['status'] == 'unsaved'
    result = runtime.invoke_tool('commit_session_note', {'note_id': result['note_id']})
    assert result['error']['code'] == 'native_disabled'
    assert runtime.invoke_tool('undo_session_note', {'note_id': 'bad'})['error']['code'] == 'invalid_arguments'


@pytest.mark.parametrize('value', ['true', 1, None])
def test_native_opt_in_must_be_boolean(notes_env, value):
    config, _ = notes_env
    data = yaml.safe_load(config.read_text())
    data['native_notes_enabled'] = value
    config.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match='boolean'):
        Config.load(config)


def test_native_opt_in_requires_library(notes_env):
    config, _ = notes_env
    data = yaml.safe_load(config.read_text())
    data['native_notes_enabled'] = True
    config.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match='live_library'):
        Config.load(config)


def test_readonly_recovery_cli_and_configuration_scope(notes_env):
    from click.testing import CliRunner
    from endnote_mcp.desktop_cli import cli
    config, _ = notes_env
    service = NoteService(config)
    draft = service.preview_session_note(42, {'questions': ['Ω quotes "\nnewlines']})
    before = {p.name: p.read_bytes() for p in config.parent.iterdir() if p.is_file()}
    result = CliRunner().invoke(cli, ['note-show', draft['note_id'], '--config', str(config), '--recovery'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['rendered_text'] == draft['text']
    for name, content in before.items():
        assert (config.parent / name).read_bytes() == content
    other = config.with_name('other.yaml')
    other.write_text(config.read_text())
    with pytest.raises(ValueError, match='configuration'):
        NoteService(other).show_session_note(draft['note_id'])


def test_journal_cannot_alias_index(notes_env):
    config, _ = notes_env
    data = yaml.safe_load(config.read_text())
    data['db_path'] = str(config.parent / 'session-notes.sqlite3')
    config.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match='separate'):
        NoteService(config)


def test_missing_note_show_never_creates_files(notes_env):
    config, _ = notes_env
    before = set(config.parent.iterdir())
    with pytest.raises(ValueError, match='No session-note'):
        NoteService(config).show_session_note('not-a-note')
    assert set(config.parent.iterdir()) == before


def test_export_from_another_library_cannot_enable_native_save(notes_env):
    service, adapter = service_with_writer(notes_env)
    service.cfg.endnote_xml.write_text(service.cfg.endnote_xml.read_text().replace('stable-db', 'another-db'))
    preview = service.preview_session_note(42, {'questions': ['Q']})
    assert not preview['native']['eligible'] and preview['native']['code'] == 'identity_conflict'
    with pytest.raises(NativeNoteError):
        service.commit_session_note(preview['note_id'])
    assert adapter.writes == 0


def test_changed_source_export_blocks_commit(notes_env):
    service, adapter = service_with_writer(notes_env)
    preview = service.preview_session_note(42, {'questions': ['Q']})
    service.cfg.endnote_xml.write_text('<xml><records/></xml>')
    with pytest.raises(NativeNoteError) as error:
        service.commit_session_note(preview['note_id'])
    assert error.value.code == 'export_identity_unavailable' and adapter.writes == 0


def test_retry_after_crash_cannot_accept_subsequent_formatting_edit(notes_env):
    service, adapter = service_with_writer(notes_env)
    preview = service.preview_session_note(42, {'questions': ['Q']})
    adapter.crash_after_write = True
    with pytest.raises(NativeNoteError):
        service.commit_session_note(preview['note_id'])
    adapter.current['notes_xml'] += 'user changed formatting without changing text'
    with pytest.raises(NativeNoteError) as error:
        service.commit_session_note(preview['note_id'])
    assert error.value.code == 'stale_preview' and adapter.writes == 1
    assert load_draft(service, preview['note_id'])['status'] == 'saving'


def test_reindexed_changed_pdf_invalidates_reviewed_citation(notes_env):
    config, _ = notes_env
    pdf = add_pdf(config)
    service, adapter = service_with_writer(notes_env)
    preview = service.preview_session_note(42, pdf_entry())
    with pymupdf.open(pdf) as document:
        document[0].insert_text((72, 120), 'Changed evidence')
        document.saveIncr()
    with sqlite3.connect(service.cfg.db_path) as conn:
        conn.execute('UPDATE attachments SET fingerprint=? WHERE attachment_id=?',
                     (hashlib.sha256(pdf.read_bytes()).hexdigest(), 'paper'))
    with pytest.raises(NativeNoteError) as error:
        service.commit_session_note(preview['note_id'])
    assert error.value.code == 'stale_preview' and adapter.writes == 0


def test_real_stdio_note_preview_and_gate(notes_env):
    import asyncio
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    config, _ = notes_env
    index_before = Config.load(config).db_path.read_bytes()
    async def run():
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'endnote_mcp.desktop_cli', 'serve-desktop', '--config', str(config)])
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                assert not (config.parent / 'session-notes.sqlite3').exists()
                preview = await session.call_tool('preview_session_note', {'rec_number': 42, 'entry': {'questions': ['Ω test "\nnewlines']}})
                assert not preview.isError and preview.structuredContent['status'] == 'unsaved'
                result = await session.call_tool('commit_session_note', {'note_id': preview.structuredContent['note_id']})
                assert result.structuredContent['error']['code'] == 'native_disabled'
    asyncio.run(run())
    assert Config.load(config).db_path.read_bytes() == index_before
