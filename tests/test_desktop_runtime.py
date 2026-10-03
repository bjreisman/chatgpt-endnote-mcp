"""Research contract checks against an actual read-only derived index."""
import hashlib
import json

import pytest
import yaml

from endnote_mcp.db import connect, insert_pdf_page, upsert_reference
from endnote_mcp.desktop_runtime import DesktopRuntime


@pytest.fixture
def desktop(tmp_path, sample_ref):
    pdf_dir = tmp_path / 'PDF'
    pdf_dir.mkdir()
    pdf = pdf_dir / 'paper.pdf'
    import fitz
    with fitz.open() as document:
        for n in range(36):
            page = document.new_page()
            if n < 35:
                page.insert_text((72, 72), 'AOX electron transport bypass experimental tool')
        document.save(pdf)
    db_path = tmp_path / 'library.db'
    with connect(db_path) as conn:
        for n in range(1, 26):
            ref = {**sample_ref, 'rec_number': n, 'title': 'Electron transport AOX',
                   'authors': json.dumps(['Smith' if n % 2 else 'Jones']),
                   'keywords': json.dumps(['AOX']), 'year': '2020' if n % 2 else '2010',
                   'research_notes': 'personal bypass observations', 'notes': 'ordinary secretword'}
            upsert_reference(conn, ref)
        conn.execute("INSERT INTO attachments(attachment_id,rec_number,relative_path,resolved_path,fingerprint,status) VALUES (?,?,?,?,?,?)",
            ('a1', 1, 'paper.pdf', str(pdf), hashlib.sha256(pdf.read_bytes()).hexdigest(), 'indexed'))
        for page in range(1, 36):
            insert_pdf_page(conn, 1, page, 'AOX electron transport bypass experimental tool', 'a1')
    config = tmp_path / 'config.yaml'
    config.write_text(yaml.safe_dump({'endnote_xml': str(tmp_path/'export.xml'), 'pdf_dir': str(pdf_dir), 'db_path': str(db_path)}))
    return DesktopRuntime(config), pdf, db_path


def test_pagination_and_note_evidence(desktop):
    runtime, _, _ = desktop
    result = runtime.search_references('AOX')
    assert len(result['items']) == 20
    assert result['pagination'] == {'offset': 0, 'limit': 20, 'total': 25, 'has_more': True}
    second = runtime.search_references('AOX', offset=20)
    assert len(second['items']) == 5
    assert {r['rec_number'] for r in result['items']}.isdisjoint(r['rec_number'] for r in second['items'])
    assert runtime.search_references('secretword')['items'] == []
    personal = runtime.search_references('observations')['items'][0]['evidence']
    assert any(e['evidence_type'] == 'research_notes' for e in personal)


def test_consistent_filters(desktop, monkeypatch):
    runtime, _, _ = desktop
    monkeypatch.setattr('endnote_mcp.embeddings.is_available', lambda: False)
    for method in (runtime.search_references, runtime.search_fulltext, runtime.search_library):
        assert method('AOX', author='Jones', year_from='2015')['items'] == []
    result = runtime.search_library('AOX', author='Smith', year_from='2015')
    assert len(result['items']) == 13
    assert result['semantic']['available'] is False


def test_attachment_integrity_and_page_cap(desktop):
    runtime, pdf, _ = desktop
    result = runtime.read_pdf_section(1, 1, 35)
    assert len(result['items']) == 30
    assert result['pages']['omitted']
    assert result['items'][0]['attachment_id'] == 'a1'
    assert result['pages']['total'] == 36
    blank = runtime.read_pdf_section(1, 36, 36)
    assert blank['items'][0]['text'] == ''
    assert blank['pages']['without_extracted_text'] == [36]
    assert runtime.read_pdf_section(1, 37, 37)['error']['code'] == 'invalid_pages'
    pdf.write_bytes(b'changed source')
    assert runtime.read_pdf_section(1)['error']['code'] == 'attachment_outdated'
    result = runtime.search_fulltext('AOX')
    assert result['items'] == []
    assert result['excluded_attachments'][0]['status'] == 'outdated'
    pdf.unlink()
    assert runtime.read_pdf_section(1)['error']['code'] == 'attachment_missing'


def test_multiple_attachments_and_readonly(desktop):
    runtime, _, db_path = desktop
    with connect(db_path) as conn:
        conn.execute("INSERT INTO attachments(attachment_id,rec_number,relative_path,status) VALUES ('a2',1,'missing.pdf','missing')")
    original = db_path.read_bytes()
    assert runtime.read_pdf_section(1)['error']['code'] == 'attachment_selection_required'
    assert runtime.read_pdf_section(1, attachment_id='a2')['error']['code'] == 'attachment_missing'
    runtime.search_references('AOX')
    assert db_path.read_bytes() == original
    with runtime._connect() as conn:
        with pytest.raises(Exception, match='readonly'):
            conn.execute('DELETE FROM references_')


def test_errors_citations_and_size(desktop, monkeypatch):
    runtime, _, _ = desktop
    monkeypatch.setattr('endnote_mcp.embeddings.is_available', lambda: False)
    assert runtime.search_semantic('AOX')['error']['code'] == 'semantic_unavailable'
    assert runtime.invoke_tool('rebuild_index')['error']['code'] == 'unknown_tool'
    assert runtime.get_citation(1)['items'][0]['citation']
    assert '@article' in runtime.get_bibtex('1')['items'][0]['citation']
    bounded = runtime._result([{'text': 'a'*100000}])
    assert bounded['truncated'] and 'Text omitted' in bounded['text']
    assert len(bounded['items'][0]['text']) < 60000


def test_errors_limits_and_public_attachment_fields(desktop):
    runtime, _, _ = desktop
    assert runtime.invoke_tool('search_references', {'query': 'AOX', 'limit': -1})['error']['code'] == 'invalid_arguments'
    assert runtime.invoke_tool('search_references', {'query': 'AOX', 'offset': -1})['error']['code'] == 'invalid_arguments'
    attachment = runtime.get_reference_details(1)['items'][0]['attachments'][0]
    assert 'resolved_path' not in attachment and 'fingerprint' not in attachment
    assert runtime.read_pdf_section(1)['items'][0]['evidence_type'] == 'pdf_text'


def test_malformed_fts_is_argument_error(desktop):
    runtime, _, _ = desktop
    for method in ('search_references', 'search_fulltext', 'search_library'):
        result = runtime.invoke_tool(method, {'query': '"unterminated'})
        assert result['error']['code'] == 'invalid_arguments'


def test_combined_attributes_equal_methods(desktop, monkeypatch):
    runtime, _, _ = desktop
    base = {'authors': 'Smith', 'year': '2020', 'title': 'AOX'}
    monkeypatch.setattr('endnote_mcp.search.search_references', lambda *args, **kwargs: [dict(base, rec_number=1), dict(base, rec_number=3)])
    monkeypatch.setattr(runtime, '_fulltext', lambda *args: ([dict(base, rec_number=2, snippets=[{'page': 1}], snippets_omitted=0), dict(base, rec_number=3, snippets=[{'page': 1}], snippets_omitted=0)], []))
    monkeypatch.setattr(runtime, '_semantic', lambda *args: ([], {'available': False}))
    rows = runtime.search_library('AOX')['items']
    assert [r['rec_number'] for r in rows] == [3, 1, 2]
    assert rows[0]['methods'] == ['metadata', 'pdf']
    assert rows[1]['methods'] == ['metadata']
    assert rows[2]['methods'] == ['pdf']


def test_related_semantic_uses_natural_text(desktop, monkeypatch):
    runtime, _, _ = desktop
    seen = []
    monkeypatch.setattr(runtime, '_semantic', lambda conn, query, filters: (seen.append(query) or [], {'available': False}))
    runtime.find_related(1)
    assert seen and 'Electron transport AOX' in seen[0]
    assert ' OR ' not in seen[0] and '"' not in seen[0]


def test_large_search_passages_preserve_all_twenty_identities():
    items = [{'reference_id': n, 'rec_number': n, 'title': f'Paper title {n}',
              'year': '2020', 'authors': f'Smith {n}', 'doi': f'10.1234/{n}',
              'snippets': [{'attachment_id': f'a{n}', 'page': p, 'snippet': 'evidence '*1000} for p in range(1, 4)],
              'evidence': [{'evidence_type': 'abstract', 'text': 'abstract '*1000}, {'evidence_type': 'research_notes', 'text': 'personal '*1000}]}
             for n in range(1, 21)]
    result = DesktopRuntime._result(items, search_previews=True,
        pagination={'offset': 0, 'limit': 20, 'total': 30, 'has_more': True})
    assert result['truncated'] and result['content_truncated']
    assert result['pagination']['has_more']
    assert len(json.dumps(result, ensure_ascii=False)) <= 60000
    for original, returned in zip(items, result['items']):
        for key in ('reference_id', 'title', 'year', 'authors', 'doi'):
            assert returned[key] == original[key]
        assert all(100 <= len(s['snippet']) <= 500 for s in returned['snippets'])
        assert all(s['content_truncated'] for s in returned['snippets'])


def test_pathological_metadata_and_error_attachment_list_are_bounded():
    result = DesktopRuntime._result([{'reference_id': n, 'title': 'title'*10000,
                'authors': ['author'*1000]*100, 'keywords': ['keyword'*1000]*100,
                'citation': 'citation'*10000} for n in range(100)])
    assert len(json.dumps(result, ensure_ascii=False)) <= 60000
    assert result['truncated']
    if result['items']:
        assert all(r['title'] and r['metadata_truncated'] for r in result['items'])
    error = DesktopRuntime._error('attachment_selection_required', 'Select an attachment.',
        attachments=[{'attachment_id': str(n), 'relative_path': 'path'*10000} for n in range(100)])
    assert len(json.dumps(error, ensure_ascii=False)) <= 60000
    assert error['attachments_omitted'] == 80
    assert 'Select an attachment' in error['text']
