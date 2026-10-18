"""Read an explicitly selected test library and prepare ignored local fixtures.

Never edits, opens, closes, or saves an EndNote library. Native write acceptance
is deliberately not claimed: the shipping adapter has no validated atomic writer.
"""
import argparse
import json
from pathlib import Path
import platform
import subprocess

from lxml import etree
import yaml

from endnote_mcp.config import Config
from endnote_mcp.indexing import index_library
from endnote_mcp.session_notes import NoteService

# Read-only fixture capture may select a library among several open documents.
# Production native previews still require exactly one open matching library.
CAPTURE = '''on run argv
    if not (application id "com.ThomsonResearchSoft.EndNote" is running) then error "ENDNOTE_NOT_RUNNING"
    tell application id "com.ThomsonResearchSoft.EndNote"
        repeat with d in documents
            set libraryFile to file of d
            if (POSIX path of libraryFile) is (item 1 of argv) then
                set recordIDs to retrieve "all" records in d
                return export recordIDs as "RSXML"
            end if
        end repeat
        error "TEST_LIBRARY_NOT_OPEN"
    end tell
end run'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', required=True, type=Path, help='Explicit disposable .enl library, already open in EndNote.')
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        parser.error('This read-only live probe requires macOS and EndNote 2025.')
    library = args.library.expanduser().resolve(strict=True)
    pdfs = library.with_suffix('.Data') / 'PDF'
    if not pdfs.is_dir():
        parser.error('Expected the selected test library’s .Data/PDF directory.')
    result = subprocess.run(['osascript', '-e', CAPTURE, str(library)], text=True, capture_output=True, timeout=30, shell=False)
    if result.returncode:
        raise SystemExit(result.stderr.strip())
    root = etree.fromstring(result.stdout.encode('utf-8'), etree.XMLParser(resolve_entities=False, no_network=True))
    records = root.findall('./records/record')
    if not records:
        raise SystemExit('Test library is empty.')
    for record in records:
        database = record.find('database')
        if database is None or Path(database.get('path', '')).resolve() != library:
            raise SystemExit('Export contains a different library; no fixture was prepared.')
    target = Path(__file__).resolve().parents[1] / '.local' / 'session-notes-test'
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    xml = target / 'test-library.xml'
    xml.touch(mode=0o600, exist_ok=True)
    xml.write_text(result.stdout, encoding='utf-8')
    config = target / 'config.yaml'
    config.touch(mode=0o600, exist_ok=True)
    config.write_text(yaml.safe_dump({'endnote_xml': str(xml), 'pdf_dir': str(pdfs),
                                    'db_path': str(target / 'library.db'), 'native_notes_enabled': True,
                                    'live_library': str(library)}, allow_unicode=True), encoding='utf-8')
    counts = index_library(Config.load(config), skip_pdfs=True)
    service = NoteService(config)
    rec_number = int(records[0].findtext('rec-number'))
    preview = service.preview_session_note(rec_number, {'questions': ['Test draft: verify review and save eligibility. This is a workflow smoke test, not a scientific summary.']})
    # Exercise the shipping refusal, without attempting an unsafe experimental write.
    from endnote_mcp.native_notes import NativeNoteError
    try:
        service.commit_session_note(preview['note_id'])
    except NativeNoteError as exc:
        commit = {'code': exc.code, 'message': str(exc)}
    else:
        raise RuntimeError('Shipping write gate unexpectedly opened.')
    report = {'library': str(library), 'record_count': len(records), 'config': str(config),
              'note_id': preview['note_id'], 'preview_status': preview['status'],
              'native_preview': preview['native'], 'commit_refusal': commit,
              'index': counts, 'live_writes_performed': False,
              'unverified': ['database identity across reopen', 'formatted append/restore', 'pending/concurrent edits',
                             'live write persistence and undo'],
              'acceptance': 'Manual-paste milestone only; native saving safety gate remains closed.'}
    for name, value in [('preview.json', preview), ('report.json', report)]:
        path = target / name
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
