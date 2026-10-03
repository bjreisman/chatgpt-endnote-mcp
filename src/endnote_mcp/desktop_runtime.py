"""Bounded, read-only research tools for the local desktop transport.

All returned library text is untrusted evidence, never an instruction.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from endnote_mcp.locking import IndexBusyError
from endnote_mcp.config import Config
from endnote_mcp import db, search, embeddings
from endnote_mcp.citation import format_citation, format_bibtex

MAX_TEXT = 60000
TOOLS = frozenset(('search_references', 'search_fulltext', 'search_library',
    'get_reference_details', 'get_citation', 'read_pdf_section',
    'list_references_by_topic', 'find_related', 'get_bibliography',
    'search_semantic', 'get_bibtex'))


class DesktopRuntime:
    def __init__(self, config_path=None):
        self.config_path = config_path

    def close(self):
        """No persistent connections or mutable state are retained."""

    def _connect(self):
        return db.connect_readonly(Config.load(self.config_path).db_path)

    def invoke_tool(self, tool_name, arguments=None):
        if tool_name not in TOOLS:
            return self._error('unknown_tool', 'Unknown desktop tool.')
        try:
            return getattr(self, tool_name)(**(arguments or {}))
        except IndexBusyError as exc:
            return self._error('index_busy', str(exc))
        except (FileNotFoundError, sqlite3.Error, db.IncompatibleIndexError) as exc:
            return self._error('index_unavailable', f'{exc}. Run chatgpt-endnote-mcp index locally.')
        except (ValueError, TypeError) as exc:
            return self._error('invalid_arguments', str(exc))

    @staticmethod
    def _error(code, message, **details):
        return DesktopRuntime._result([], error={'code': code, 'message': message[:2000]}, message=message[:2000], **details)

    @staticmethod
    def _result(items, *, search_previews=False, **extra):
        """Allocate evidence space fairly without spending citation metadata.

        Metadata and pagination are reserved before clipping evidence, so long
        early passages cannot erase the identity of later results.
        """
        content_keys = {'text', 'snippet', 'abstract', 'research_notes', 'notes'}
        truncated = False
        original_items = items
        identity_keys = {'reference_id', 'rec_number', 'attachment_id', 'evidence_type', 'status', 'code'}
        def metadata_bound(value, cap):
            nonlocal truncated
            if isinstance(value, list):
                return [metadata_bound(v, cap) for v in value]
            if not isinstance(value, dict):
                return value
            result, omitted = {}, {}
            for key, val in value.items():
                if key in ('authors', 'keywords') and isinstance(val, list) and len(val) > 20:
                    omitted[key] = len(val) - 20
                    val = val[:20]
                if isinstance(val, str) and key not in content_keys and key not in identity_keys and len(val) > cap:
                    omitted[key] = len(val) - cap
                    val = val[:cap]
                result[key] = metadata_bound(val, cap)
            if omitted:
                truncated = True
                result['metadata_truncated'] = True
                result['metadata_omitted'] = omitted
            return result
        extra = metadata_bound(extra, 2000)
        if len(extra.get('excluded_attachments', [])) > 20:
            extra['excluded_attachments_total'] = len(extra['excluded_attachments'])
            extra['excluded_attachments_omitted'] = len(extra['excluded_attachments']) - 20
            extra['excluded_attachments'] = extra['excluded_attachments'][:20]
            truncated = True
        if len(extra.get('attachments', [])) > 20:
            extra['attachments_omitted'] = len(extra['attachments']) - 20
            extra['attachments'] = extra['attachments'][:20]
            truncated = True
        metadata_cap = 8192
        items = metadata_bound(original_items, metadata_cap)
        def skeleton(value):
            if isinstance(value, list):
                return [skeleton(v) for v in value]
            if isinstance(value, dict):
                return {k: ('' if k in content_keys and isinstance(v, str) else skeleton(v))
                        for k, v in value.items()}
            return value
        def text_count(value):
            if isinstance(value, list):
                return sum(text_count(v) for v in value)
            if isinstance(value, dict):
                return sum(1 if k in content_keys and isinstance(v, str) and v else text_count(v)
                           for k, v in value.items())
            return 0
        # Human-readable text identifies results without duplicating passages.
        lines = []
        for item in items:
            rid = item.get('reference_id', item.get('rec_number', '?'))
            if 'page' in item:
                lines.append(f"[{rid}] attachment {item.get('attachment_id', '?')}, PDF page {item['page']}")
            elif item.get('citation'):
                lines.append(f"[{rid}] Citation supplied in structured results.")
            else:
                lines.append(f"[{rid}] {str(item.get('authors', ''))[:150]} ({item.get('year', '')}). {str(item.get('title', ''))[:250]}")
        text = '\n'.join(lines) or extra.get('error', {}).get('message', 'No results found in this library.')
        reserved = len(json.dumps({'items': skeleton(items), 'text': text, **extra}, ensure_ascii=False))
        while reserved > MAX_TEXT * .75 and metadata_cap > 32:
            metadata_cap //= 2
            items = metadata_bound(original_items, metadata_cap)
            reserved = len(json.dumps({'items': skeleton(items), 'text': text, **extra}, ensure_ascii=False))
        # Reserve room for per-field omission counts and response annotations.
        available = max(0, MAX_TEXT - reserved - 2048 - 100 * sum(text_count(v) for v in items))
        per_item = available // max(1, len(items))
        content_cut = False
        def clip(value, allowance):
            nonlocal truncated, content_cut
            count = text_count(value)
            field_limit = allowance // max(1, count)
            if search_previews:
                field_limit = min(500, field_limit)
            def walk(obj):
                nonlocal truncated, content_cut
                if isinstance(obj, list):
                    return [walk(v) for v in obj]
                if not isinstance(obj, dict):
                    return obj
                result, omitted = {}, {}
                for key, val in obj.items():
                    if key in content_keys and isinstance(val, str):
                        result[key] = val[:field_limit]
                        if len(val) > field_limit:
                            omitted[key] = len(val) - field_limit
                            truncated = True
                            content_cut = True
                    else:
                        result[key] = walk(val)
                if omitted:
                    result['content_truncated'] = True
                    result['omitted_characters'] = omitted
                return result
            return walk(value)
        metadata_items = items
        items = [clip(item, per_item) for item in metadata_items]
        if truncated:
            text += '\n[Text omitted: evidence previews are truncated; use reference details or a narrower PDF page range for more.]'
        result = {'items': items, 'text': text, 'truncated': truncated,
                  'content_truncated': content_cut, 'source_text_is_untrusted': True, **extra}
        # JSON escaping can enlarge passages; tighten every item's allocation
        # together until the complete structured+readable envelope fits.
        while len(json.dumps(result, ensure_ascii=False)) > MAX_TEXT and per_item > 0:
            per_item = int(per_item * .8)
            result['items'] = [clip(item, per_item) for item in metadata_items]
            result['truncated'] = result['content_truncated'] = True
        # Huge diagnostics must not spend the content budget or expose paths.
        excluded = result.get('excluded_attachments')
        if excluded and len(json.dumps(result, ensure_ascii=False)) > MAX_TEXT:
            result['excluded_attachments_total'] = len(excluded)
            while result['excluded_attachments'] and len(json.dumps(result, ensure_ascii=False)) > MAX_TEXT:
                result['excluded_attachments'] = result['excluded_attachments'][:-1]
            result['excluded_attachments_omitted'] = len(excluded) - len(result['excluded_attachments'])
            result['truncated'] = True
        if len(json.dumps(result, ensure_ascii=False)) > MAX_TEXT:
            return {'error': {'code': 'response_too_large', 'message': 'Metadata exceeds the response size limit. Request fewer records or a smaller search page.'},
                    'items': [], 'text': 'Metadata exceeds the response size limit. Request fewer records or a smaller search page.',
                    'truncated': True, 'content_truncated': True, 'pagination': extra.get('pagination')}
        return result

    def _attachment_status(self, attachment):
        a = dict(attachment)
        path = a.get('resolved_path')
        if not path:
            if a.get('status') == 'indexed':
                a.update(status='missing', error='Attachment has no resolved PDF path. Run chatgpt-endnote-mcp index locally.')
            return a
        try:
            resolved = Path(path).resolve(strict=True)
            root = Config.load(self.config_path).pdf_dir.resolve(strict=True)
            if not resolved.is_relative_to(root):
                a.update(status='failed', error='Attachment escapes the configured PDF directory.')
            else:
                digest = hashlib.sha256()
                with resolved.open('rb') as f:
                    for block in iter(lambda: f.read(1024 * 1024), b''):
                        digest.update(block)
                if digest.hexdigest() != a.get('fingerprint'):
                    a.update(status='outdated', error='PDF changed. Run chatgpt-endnote-mcp index locally.')
        except FileNotFoundError:
            a.update(status='missing', error='PDF file is missing.')
        except OSError as exc:
            a.update(status='failed', error=str(exc))
        return a

    @staticmethod
    def _public_attachment(a):
        return {k: v for k, v in a.items() if k not in ('resolved_path', 'fingerprint')}

    def _fulltext(self, conn, query, filters):
        # Check every matching attachment before slicing so stale candidates do
        # not displace valid evidence in the requested page.
        rows = search.search_fulltext(conn, query, limit=2**31-1,
                                      max_snippets_per_ref=2**31-1, **filters)
        checked = {}
        valid, excluded = [], []
        for row in rows:
            snippets = []
            for snippet in row['snippets']:
                aid = snippet['attachment_id']
                if aid not in checked:
                    a = conn.execute('SELECT * FROM attachments WHERE attachment_id=?', (aid,)).fetchone()
                    checked[aid] = self._attachment_status(a) if a else {'status': 'missing', 'attachment_id': aid}
                a = checked[aid]
                if a['status'] == 'indexed':
                    snippets.append(snippet)
                elif not any(e.get('attachment_id') == aid for e in excluded):
                    excluded.append(self._public_attachment(a))
            if snippets:
                row['snippets'] = snippets[:3]
                row['snippets_omitted'] = max(0, len(snippets)-3)
                row['evidence_type'] = 'pdf_text'
                valid.append(row)
        return valid, excluded

    def _semantic(self, conn, query, filters):
        if not embeddings.has_embeddings(conn):
            return [], {'available': False, 'reason': 'Run chatgpt-endnote-mcp embed locally.'}
        if not embeddings.is_available():
            return [], {'available': False, 'reason': 'Install chatgpt-endnote-mcp[semantic], then run chatgpt-endnote-mcp embed locally.'}
        try:
            rows = search.search_semantic(conn, query, limit=2**31-1, **filters)
            return rows, {'available': True, 'used': True, 'evidence_type': 'metadata_similarity'}
        except Exception as exc:
            return [], {'available': False, 'reason': f'Cached model unavailable: {exc}. Run chatgpt-endnote-mcp embed locally.'}

    def _search(self, mode, query, limit=20, offset=0, exclude_rec=None, semantic_query=None, **filters):
        limit, offset = int(limit), int(offset)
        if limit < 1 or offset < 0:
            raise ValueError('limit must be positive and offset must be nonnegative.')
        limit = min(100, limit)
        semantic, excluded = {'available': False, 'used': False, 'reason': 'Not requested.'}, []
        with closing(self._connect()) as conn:
            rows = []
            if mode in ('metadata', 'combined'):
                rows = search.search_references(conn, query, limit=2**31-1, **filters)
                for r in rows:
                    r['evidence_type'] = 'metadata'
                    r['methods'] = ['metadata']
                    details = search.get_reference_details(conn, r['rec_number'])
                    r['evidence'] = [{'evidence_type': name, 'text': details[name]}
                        for name in ('abstract', 'research_notes') if details.get(name)]
            if mode in ('pdf', 'combined'):
                pdf, excluded = self._fulltext(conn, query, filters)
                for r in pdf:
                    r['methods'] = ['pdf']
                if mode == 'pdf':
                    rows = pdf
                else:
                    by_id = {r['rec_number']: r for r in rows}
                    for r in pdf:
                        if r['rec_number'] in by_id:
                            by_id[r['rec_number']]['methods'].append('pdf')
                            by_id[r['rec_number']].update(snippets=r['snippets'], snippets_omitted=r['snippets_omitted'])
                        else:
                            rows.append(r)
            if mode in ('semantic', 'combined'):
                sem, semantic = self._semantic(conn, semantic_query if semantic_query is not None else query, filters)
                existing = {r['rec_number']: r for r in rows}
                for r in sem:
                    if r['rec_number'] in existing:
                        existing[r['rec_number']]['similarity'] = r['similarity']
                        existing[r['rec_number']]['methods'].append('semantic')
                    else:
                        r['evidence_type'] = 'metadata_similarity'
                        r['methods'] = ['semantic']
                        rows.append(r)
            for r in rows:
                r['reference_id'] = r['rec_number']
            if mode == 'combined':
                rows.sort(key=lambda r: -len(r['methods']))
        if exclude_rec is not None:
            rows = [r for r in rows if r['rec_number'] != exclude_rec]
        return self._result(rows[offset:offset+limit], search_previews=True,
            pagination={'offset': offset, 'limit': limit, 'total': len(rows),
                        'has_more': offset+limit < len(rows)}, semantic=semantic,
            excluded_attachments=excluded,
            **({'error': {'code': 'semantic_unavailable', 'message': semantic['reason']}} if mode == 'semantic' and not semantic['available'] else {}))

    def search_references(self, query, year_from=None, year_to=None, author=None, ref_type=None, limit=20, offset=0):
        return self._search('metadata', query, limit, offset, year_from=year_from, year_to=year_to, author=author, ref_type=ref_type)

    def search_fulltext(self, query, limit=20, offset=0, year_from=None, year_to=None, author=None, ref_type=None):
        return self._search('pdf', query, limit, offset, year_from=year_from, year_to=year_to, author=author, ref_type=ref_type)

    def search_library(self, query, year_from=None, year_to=None, author=None, ref_type=None, limit=20, offset=0):
        return self._search('combined', query, limit, offset, year_from=year_from, year_to=year_to, author=author, ref_type=ref_type)

    def search_semantic(self, query, limit=20, offset=0, year_from=None, year_to=None, author=None, ref_type=None):
        return self._search('semantic', query, limit, offset, year_from=year_from, year_to=year_to, author=author, ref_type=ref_type)

    def list_references_by_topic(self, topic, year_from=None, year_to=None, ref_type=None, limit=20, offset=0, author=None):
        return self.search_references(topic, year_from, year_to, author, ref_type, limit, offset)

    def get_reference_details(self, rec_number):
        with closing(self._connect()) as conn:
            ref = search.get_reference_details(conn, rec_number)
            if ref is None:
                return self._error('not_found', f'Reference {rec_number} not found in this library.')
            ref['attachments'] = [self._public_attachment(self._attachment_status(a)) for a in conn.execute('SELECT * FROM attachments WHERE rec_number=?', (rec_number,))]
            ref['reference_id'] = rec_number
            ref['evidence'] = [{'evidence_type': name, 'text': ref[name]} for name in ('abstract', 'research_notes', 'notes') if ref.get(name)]
        return self._result([ref])

    def read_pdf_section(self, rec_number, start_page=1, end_page=5, attachment_id=None):
        start_page, end_page = int(start_page), int(end_page)
        if start_page < 1 or end_page < start_page:
            return self._error('invalid_pages', 'Use a positive, ascending PDF page range.')
        requested_end = end_page
        end_page = min(end_page, start_page + min(30, Config.load(self.config_path).max_pdf_pages) - 1)
        with closing(self._connect()) as conn:
            attachments = [dict(a) for a in conn.execute('SELECT * FROM attachments WHERE rec_number=?', (rec_number,))]
            if not attachments:
                return self._error('no_attachment', 'No PDF attachment found in this library.')
            if len(attachments) > 1 and attachment_id is None:
                return self._error('attachment_selection_required', 'Select an attachment_id explicitly.', attachments=[self._public_attachment(a) for a in attachments])
            a = next((a for a in attachments if attachment_id is None or a['attachment_id'] == attachment_id), None)
            if not a:
                return self._error('attachment_not_found', 'That attachment does not belong to this reference.')
            a = self._attachment_status(a)
            if a['status'] != 'indexed':
                return self._error('attachment_' + a['status'], a.get('error') or f"Attachment is {a['status']}.", attachment=self._public_attachment(a))
            # Indexed text can omit scanned or blank pages, especially at EOF.
            # Obtain the physical page count from the already-validated attachment.
            import pymupdf as fitz
            try:
                with fitz.open(a['resolved_path']) as document:
                    total = len(document)
            except Exception:
                return self._error('attachment_failed', 'Unable to read PDF page count; reindex locally.')
            if start_page > total:
                return self._error('invalid_pages', f'This PDF has {total} pages.')
            pages = [dict(p) for p in conn.execute('SELECT page_number, text_content FROM pdf_pages WHERE attachment_id=? AND page_number BETWEEN ? AND ? ORDER BY page_number', (a['attachment_id'], start_page, end_page))]
            by_page = {p['page_number']: p['text_content'] for p in pages}
            pages = [{'page_number': n, 'text_content': by_page.get(n, '')}
                     for n in range(start_page, min(end_page, total) + 1)]
        items = [{'reference_id': rec_number, 'rec_number': rec_number, 'attachment_id': a['attachment_id'], 'evidence_type': 'pdf_text', 'page': p['page_number'], 'text': p['text_content']} for p in pages]
        return self._result(items, pages={'start': start_page, 'end': min(end_page,total), 'total': total, 'requested_end': requested_end, 'omitted': requested_end > end_page,
            'without_extracted_text': [p['page_number'] for p in pages if not p['text_content']],
            'note': 'PDF page indices; blank or scanned pages may have no extracted text. OCR is not performed.'})

    def find_related(self, rec_number, limit=20, offset=0, year_from=None, year_to=None, author=None, ref_type=None):
        with closing(self._connect()) as conn:
            target = search.get_reference_details(conn, rec_number)
        if not target:
            return self._error('not_found', 'Reference not found in this library.')
        terms = target.get('keywords') or target.get('title', '').split()[:8]
        query = ' OR '.join('"' + t.replace('"', '') + '"' for t in terms)
        return self._search('combined', query, limit, offset, exclude_rec=rec_number,
            semantic_query=' '.join([target.get('title', ''), *terms]),
            year_from=year_from, year_to=year_to, author=author, ref_type=ref_type)

    def _citations(self, rec_numbers, style='apa7', sort='author', bibtex=False):
        numbers = list(dict.fromkeys(int(n.strip()) for n in rec_numbers.split(',') if n.strip()))
        if not numbers or len(numbers) > 100:
            return self._error('invalid_records', 'Provide between 1 and 100 comma-separated record IDs.')
        with closing(self._connect()) as conn:
            refs = search.get_references_batch(conn, numbers)
        if sort == 'year':
            refs.sort(key=lambda r: (r.get('year') or '', r.get('authors') or []))
        elif sort == 'author':
            refs.sort(key=lambda r: (r.get('authors') or [], r.get('year') or ''))
        items = [{'reference_id': r['rec_number'], 'rec_number': r['rec_number'], 'evidence_type': 'citation', 'citation': format_bibtex(r) if bibtex else format_citation(r, style)} for r in refs]
        return self._result(items, missing_reference_ids=[n for n in numbers if n not in {r['rec_number'] for r in refs}])

    def get_citation(self, rec_number, style='apa7'):
        return self._citations(str(rec_number), style)

    def get_bibliography(self, rec_numbers, style='apa7', sort='author'):
        return self._citations(rec_numbers, style, sort)

    def get_bibtex(self, rec_numbers):
        return self._citations(rec_numbers, bibtex=True)
