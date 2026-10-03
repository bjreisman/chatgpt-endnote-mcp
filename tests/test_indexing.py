"""Integrity checks for staged local imports and attachment provenance."""
from pathlib import Path
import sqlite3

import pymupdf as fitz
import pytest

from endnote_mcp.config import Config
from endnote_mcp import db
from endnote_mcp.indexing import index_library
from endnote_mcp.endnote_parser import parse_endnote_xml
from endnote_mcp.pdf_indexer import find_pdf


def export(cfg, records):
    cfg.endnote_xml.write_text('<xml><records>' + records + '</records></xml>')


def record(number=1, title='Paper', attachments=(), extra=''):
    urls = ''.join(f'<url>internal-pdf://{p}</url>' for p in attachments)
    return f'<record><rec-number>{number}</rec-number><titles><title>{title}</title></titles><urls><pdf-urls>{urls}</pdf-urls></urls>{extra}</record>'


@pytest.fixture
def cfg(tmp_path):
    pdf = tmp_path / 'PDF'
    pdf.mkdir()
    return Config(tmp_path / 'export.xml', pdf, tmp_path / 'index.db')


def pdf(path, text='Evidence from published paper'):
    path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as doc:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
        doc.save(path)


def test_multiple_attachments_nested_notes(cfg):
    pdf(cfg.pdf_dir / 'nested/a.pdf')
    pdf(cfg.pdf_dir / 'nested/b.pdf', 'Second evidence')
    export(cfg, record(attachments=['nested/a.pdf', 'nested/b.pdf'], extra='<research-notes><style>personal hypothesis</style></research-notes><notes>ordinary secretword</notes>'))
    refs = list(parse_endnote_xml(cfg.endnote_xml))
    assert refs[0]['attachments'] == ['nested/a.pdf', 'nested/b.pdf']
    assert refs[0]['research_notes'] == 'personal hypothesis'
    index_library(cfg)
    with db.connect_readonly(cfg.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM attachments').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM pdf_pages').fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM references_fts WHERE references_fts MATCH 'hypothesis'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM references_fts WHERE references_fts MATCH 'secretword'").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            conn.execute('DELETE FROM references_')


def test_attachment_security(cfg, tmp_path):
    pdf(cfg.pdf_dir / 'a/same.pdf')
    pdf(cfg.pdf_dir / 'b/same.pdf')
    assert find_pdf(cfg.pdf_dir, 'same.pdf') is None
    assert find_pdf(cfg.pdf_dir, 'a/same.pdf') == (cfg.pdf_dir / 'a/same.pdf').resolve()
    pdf(tmp_path / 'outside.pdf')
    (cfg.pdf_dir / 'link.pdf').symlink_to(tmp_path / 'outside.pdf')
    assert find_pdf(cfg.pdf_dir, '../outside.pdf') is None
    assert find_pdf(cfg.pdf_dir, '%2e%2e/outside.pdf') is None
    assert find_pdf(cfg.pdf_dir, 'link.pdf') is None


def test_changes_invalidate_embeddings_and_missing_pages(cfg):
    path = cfg.pdf_dir / 'a.pdf'
    pdf(path)
    export(cfg, record(attachments=['a.pdf']))
    index_library(cfg)
    conn = db.connect(cfg.db_path)
    db.upsert_embedding(conn, 1, b'fake', 'test')
    conn.commit()
    conn.close()
    pdf(path, 'Updated experimental evidence')
    stats = index_library(cfg)
    assert stats['references_with_embeddings'] == 0
    assert stats['attachments_changed'] == 1
    with db.connect_readonly(cfg.db_path) as conn:
        assert 'Updated' in conn.execute('SELECT text_content FROM pdf_pages').fetchone()[0]
    path.unlink()
    stats = index_library(cfg)
    assert stats['total_pdf_pages'] == 0
    assert stats['attachment_statuses']['missing'] == 1


def test_malformed_or_interrupted_import_keeps_usable_index(cfg, monkeypatch):
    export(cfg, record())
    index_library(cfg)
    before = cfg.db_path.read_bytes()
    cfg.endnote_xml.write_text('<xml><records>' + record(title='Changed') + '<record>')
    with pytest.raises(Exception):
        index_library(cfg)
    assert cfg.db_path.read_bytes() == before
    export(cfg, record(title='Changed'))
    import endnote_mcp.indexing as indexing
    def interrupted(path):
        yield from parse_endnote_xml(path)
        raise KeyboardInterrupt()
    monkeypatch.setattr(indexing, 'parse_endnote_xml', interrupted)
    with pytest.raises(KeyboardInterrupt):
        index_library(cfg)
    assert cfg.db_path.read_bytes() == before
    assert not list(cfg.db_path.parent.glob('.*-stage-*'))


def test_upsert_and_explicit_deletions(cfg):
    export(cfg, record(1) + record(2))
    index_library(cfg)
    export(cfg, record(1))
    assert index_library(cfg)['total_references'] == 2
    assert index_library(cfg, sync_deletions=True)['total_references'] == 1
    cfg.endnote_xml.write_text('<anything/>')
    with pytest.raises(ValueError):
        index_library(cfg, sync_deletions=True)
    with db.connect_readonly(cfg.db_path) as conn:
        assert db.get_stats(conn)['total_references'] == 1


def test_statuses_and_skip_pdfs(cfg):
    pdf(cfg.pdf_dir / 'blank.pdf', '')
    (cfg.pdf_dir / 'broken.pdf').write_bytes(b'bad pdf')
    export(cfg, record(attachments=['blank.pdf', 'broken.pdf', 'missing.pdf']))
    stats = index_library(cfg)
    assert stats['attachment_statuses'] == {'textless': 1, 'failed': 1, 'missing': 1}
    pdf(cfg.pdf_dir / 'blank.pdf', 'Now text')
    assert index_library(cfg, skip_pdfs=True)['attachment_statuses']['outdated'] == 2
    assert index_library(cfg)['attachment_statuses']['indexed'] == 1


def test_incompatible_schema_rebuilt_only_on_success(cfg):
    conn = sqlite3.connect(cfg.db_path)
    conn.execute('CREATE TABLE legacy(value TEXT)')
    conn.commit()
    conn.close()
    with pytest.raises(db.IncompatibleIndexError):
        db.connect_readonly(cfg.db_path)
    before = cfg.db_path.read_bytes()
    cfg.endnote_xml.write_text('<xml>')
    with pytest.raises(Exception):
        index_library(cfg)
    assert cfg.db_path.read_bytes() == before
    export(cfg, record())
    index_library(cfg)
    with db.connect_readonly(cfg.db_path) as conn:
        assert db.get_stats(conn)['total_references'] == 1


def test_management_lock_rejects_concurrent_import(cfg):
    from endnote_mcp.indexing import management_lock
    export(cfg, record())
    with management_lock(cfg.db_path):
        with pytest.raises(RuntimeError, match="Another index/embed"):
            index_library(cfg)
    assert index_library(cfg)["total_references"] == 1


def test_bounded_progress(cfg):
    export(cfg, "".join(record(i) for i in range(1, 202)))
    calls = []
    index_library(cfg, skip_pdfs=True, progress=calls.append)
    assert calls == [100, 200]
