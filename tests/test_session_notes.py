"""Draft fidelity, citations, source isolation, and durable local recovery."""
import hashlib
import json
import os
import sqlite3
import subprocess

import pymupdf
import pytest
import yaml

from endnote_mcp import db
from endnote_mcp.config import Config
from endnote_mcp.desktop_runtime import DesktopRuntime
from endnote_mcp.locking import FileLock, IndexBusyError
from endnote_mcp.session_notes import NoteService


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
    xml.write_text('<xml><records/></xml>', encoding='utf-8')
    config = tmp_path / 'config.yaml'
    config.write_text(yaml.safe_dump({'endnote_xml': str(xml), 'pdf_dir': str(tmp_path), 'db_path': str(database)}), encoding='utf-8')
    return config, sample_ref


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
    reopened = NoteService(config)
    draft = load_draft(reopened, result['note_id'])
    assert draft['rendered_text'] == result['text']
    assert draft['status'] == 'draft'
    if os.name != 'nt':
        assert service.journal.stat().st_mode & 0o777 == 0o600
    for name, content in before.items():
        assert (config.parent / name).read_bytes() == content


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


def test_note_journal_excludes_another_process(notes_env):
    service = NoteService(notes_env[0])
    preview = service.preview_session_note(42, {'questions': ['Q']})
    with FileLock(str(service.journal) + '.lock'):
        with pytest.raises(IndexBusyError):
            service.preview_session_note(42, {'questions': ['Another draft']})


def test_runtime_note_errors_are_structured_and_no_startup_journal(notes_env):
    config, _ = notes_env
    runtime = DesktopRuntime(config)
    assert not (config.parent / 'session-notes.sqlite3').exists()
    result = runtime.invoke_tool('preview_session_note', {'rec_number': 42, 'entry': {'questions': ['Q']}})
    assert result['status'] == 'unsaved'
    assert runtime.invoke_tool('commit_session_note', {'note_id': result['note_id']})['error']['code'] == 'unknown_tool'
    assert runtime.invoke_tool('undo_session_note', {'note_id': 'bad'})['error']['code'] == 'unknown_tool'


def test_legacy_native_settings_cannot_contact_endnote(notes_env, monkeypatch):
    config, _ = notes_env
    add_pdf(config)
    data = yaml.safe_load(config.read_text(encoding='utf-8'))
    data.update(native_notes_enabled=True, live_library=str(config.parent / 'Test.enl'))
    config.write_text(yaml.safe_dump(data), encoding='utf-8')
    protected = [config, Config.load(config).db_path, Config.load(config).endnote_xml]
    before = {path: path.read_bytes() for path in protected}

    def refuse_process(*args, **kwargs):
        raise AssertionError('Drafting must not launch an external application')

    monkeypatch.setattr(subprocess, 'run', refuse_process)
    monkeypatch.setattr(subprocess, 'Popen', refuse_process)
    service = NoteService(config)
    preview = service.preview_session_note(42, pdf_entry())
    assert preview['status'] == 'unsaved' and preview['saved'] is False
    assert service.show_session_note(preview['note_id'])['rendered_text'] == preview['text']
    assert all(path.read_bytes() == content for path, content in before.items())


def test_existing_prototype_draft_remains_recoverable(notes_env):
    service = NoteService(notes_env[0])
    preview = service.preview_session_note(42, {'questions': ['Keep my existing draft']})
    with service._journal() as conn:
        draft = service._load(conn, preview['note_id'])
        draft.update(native={'eligible': False}, preimage={'notes_text': 'Prior test notes'})
        service._save(conn, draft)
    before = service.journal.read_bytes()
    assert service.show_session_note(preview['note_id'])['rendered_text'] == preview['text']
    assert service.show_session_note(preview['note_id'], recovery=True)['preimage']['notes_text'] == 'Prior test notes'
    assert service.journal.read_bytes() == before


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
    other.write_text(config.read_text(encoding='utf-8'), encoding='utf-8')
    with pytest.raises(ValueError, match='configuration'):
        NoteService(other).show_session_note(draft['note_id'])


def test_journal_cannot_alias_index(notes_env):
    config, _ = notes_env
    data = yaml.safe_load(config.read_text(encoding='utf-8'))
    data['db_path'] = str(config.parent / 'session-notes.sqlite3')
    config.write_text(yaml.safe_dump(data), encoding='utf-8')
    with pytest.raises(ValueError, match='separate'):
        NoteService(config)


def test_missing_note_show_never_creates_files(notes_env):
    config, _ = notes_env
    before = set(config.parent.iterdir())
    with pytest.raises(ValueError, match='No session-note'):
        NoteService(config).show_session_note('not-a-note')
    assert set(config.parent.iterdir()) == before


def test_real_stdio_note_preview_without_live_connection(notes_env):
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
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert 'commit_session_note' not in tools and 'undo_session_note' not in tools
    asyncio.run(run())
    assert Config.load(config).db_path.read_bytes() == index_before


def test_manual_draft_survives_restart_and_cli_recovery(notes_env):
    """Exercise the copyable draft through real transport and fresh processes."""
    import asyncio
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    config, _ = notes_env
    pdf = add_pdf(config)
    cfg = Config.load(config)
    protected = [config, cfg.db_path, cfg.endnote_xml, pdf]
    before = {path: path.read_bytes() for path in protected}
    entry = pdf_entry()
    entry.update(interpretation=['My interpretation: Ω "quoted"\nsecond line'],
                 questions=['What next?'], hypotheses=['A separate hypothesis'])

    async def session_cycle(note_id=None):
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'endnote_mcp.desktop_cli', 'serve-desktop', '--config', str(config)])
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                if note_id is None:
                    result = await session.call_tool('preview_session_note', {'rec_number': 42, 'entry': entry})
                    assert not result.isError
                    return result.structuredContent
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert 'commit_session_note' not in tools and 'undo_session_note' not in tools

    preview = asyncio.run(session_cycle())
    assert preview['status'] == 'unsaved' and not preview['saved']
    for heading in ('Published findings', 'Personal interpretation', 'Questions', 'Hypotheses'):
        assert heading in preview['text']
    assert 'attachment paper, physical PDF page(s) 1–2' in preview['text']
    assert entry['interpretation'][0] in preview['text']
    # Recovery must retain every character even through a non-Unicode pipe.
    recovered = subprocess.run([sys.executable, '-m', 'endnote_mcp.desktop_cli',
        'note-show', preview['note_id'], '--config', str(config)],
        env={**os.environ, 'PYTHONIOENCODING': 'ascii'}, capture_output=True, timeout=30)
    assert recovered.returncode == 0, recovered.stderr
    draft = json.loads(recovered.stdout)
    assert draft['rendered_text'] == preview['text'] and draft['status'] == 'draft'
    asyncio.run(session_cycle(preview['note_id']))
    assert all(path.read_bytes() == content for path, content in before.items())
