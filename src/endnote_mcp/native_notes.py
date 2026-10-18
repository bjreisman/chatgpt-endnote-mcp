"""Read-only EndNote 2025 probe. No native writer has passed the safety gate."""
from __future__ import annotations

import platform
import subprocess
import unicodedata
from pathlib import Path

from lxml import etree


class NativeNoteError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def normalized(value):
    return ' '.join(unicodedata.normalize('NFC', value or '').casefold().split())


def normalized_doi(value):
    value = normalized(value)
    for prefix in ('https://doi.org/', 'http://doi.org/', 'doi:'):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
    return value


def snapshot_from_xml(xml, library_path, expected):
    """Resolve a unique bibliographic match, never a record-number-only match."""
    root = etree.fromstring(xml.encode('utf-8'), etree.XMLParser(resolve_entities=False, no_network=True))
    def text(record, xpath):
        element = record.find(xpath)
        return ''.join(element.itertext()) if element is not None else ''
    records = root.findall('./records/record')
    doi = normalized_doi(expected.get('doi', ''))
    candidates = [r for r in records if normalized_doi(text(r, 'electronic-resource-num')) == doi] if doi else [
        r for r in records if normalized(text(r, './titles/title')) == normalized(expected['title'])]
    if len(candidates) != 1:
        raise NativeNoteError('ambiguous_match', 'No unique live paper match; use manual paste.')
    record = candidates[0]
    database = record.find('database')
    if database is None or not database.get('path') or Path(database.get('path')).resolve() != Path(library_path).resolve():
        raise NativeNoteError('wrong_library', 'Live XML does not identify the configured library.')
    authors = [''.join(a.itertext()) for a in record.findall('./contributors/authors/author')]
    if (not expected.get('title') or not expected.get('year') or not expected.get('authors') or
        normalized(text(record, './titles/title')) != normalized(expected['title']) or
        normalized(text(record, './dates/year')) != normalized(expected['year']) or
        [normalized(a) for a in authors] != [normalized(a) for a in expected['authors']]):
        raise NativeNoteError('identity_conflict', 'Live title, year, or authors differ from the snapshot.')
    keys = record.findall('./foreign-keys/key[@app="EN"]')
    if len(keys) != 1 or not keys[0].get('db-id'):
        raise NativeNoteError('identity_unavailable', 'Live XML lacks a unique EndNote database identity.')
    notes = record.find('research-notes')
    return {'library_path': str(Path(library_path).resolve()), 'database_id': keys[0].get('db-id'),
            'rec_number': text(record, 'rec-number'), 'notes_text': text(record, 'research-notes'),
            'notes_xml': etree.tostring(notes, encoding='unicode') if notes is not None else '',
            'record_xml': etree.tostring(record, encoding='unicode')}


class MacEndNoteAdapter:
    # A local lock cannot exclude edits from EndNote's UI or other automation.
    # Neither field/set field nor XML replacement supplies compare-and-swap.
    safe_writes = False
    safety_reason = ('EndNote AppleScript has no validated atomic conditional field update. '
                     'Formatting-preserving append and restore are also unvalidated. Use manual paste.')

    def __init__(self, library_path):
        self.library_path = Path(library_path).resolve()

    def export_xml(self):
        if platform.system() != 'Darwin':
            raise NativeNoteError('native_unavailable', 'Native Research Notes saving is a macOS prototype only.')
        helper = Path(__file__).with_name('native_notes.applescript')
        try:
            result = subprocess.run(['osascript', str(helper), str(self.library_path)],
                                    capture_output=True, text=True, timeout=30, shell=False)
        except subprocess.TimeoutExpired as exc:
            raise NativeNoteError('native_timeout', 'EndNote did not answer within 30 seconds.') from exc
        except OSError as exc:
            raise NativeNoteError('native_unavailable', 'Cannot run the EndNote scripting helper.') from exc
        if result.returncode:
            error = result.stderr
            code = ('automation_denied' if '-1743' in error else
                    'multiple_libraries' if 'ONE_LIBRARY_REQUIRED' in error else
                    'wrong_library' if 'WRONG_LIBRARY' in error else 'native_unavailable')
            raise NativeNoteError(code, 'EndNote read failed: ' + error.strip()[:1000])
        if len(result.stdout.encode('utf-8')) > 32 * 1024 * 1024:
            raise NativeNoteError('native_response_too_large', 'Live XML exceeds the prototype read limit.')
        return result.stdout

    def snapshot(self, expected):
        try:
            return snapshot_from_xml(self.export_xml(), self.library_path, expected)
        except etree.XMLSyntaxError as exc:
            raise NativeNoteError('native_invalid_xml', 'EndNote returned invalid XML.') from exc

    def plan_replacement(self, expected_snapshot, text):
        raise NativeNoteError('native_safety_gate', self.safety_reason)

    def replace_notes(self, expected_snapshot, text, notes_xml=None):
        raise NativeNoteError('native_safety_gate', self.safety_reason)
