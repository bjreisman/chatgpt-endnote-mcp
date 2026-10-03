"""Actual worker deadlines, containment, and cross-process locking."""
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
import pymupdf

from endnote_mcp import db, pdf_indexer
from endnote_mcp.config import Config
from endnote_mcp.indexing import index_library
from endnote_mcp.locking import FileLock, IndexBusyError, management_lock, publish_database


def make_pdf(path, text='Synthetic evidence', encrypted=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as document:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
        options = {'encryption': pymupdf.PDF_ENCRYPT_AES_256, 'owner_pw': 'owner', 'user_pw': 'secret'} if encrypted else {}
        document.save(path, **options)


@pytest.mark.parametrize('attachment', ['nested/paper Ω.pdf', 'nested\\paper Ω.pdf', 'nested/paper%20%CE%A9.pdf'])
def test_nested_attachment_formats(tmp_path, attachment):
    target = tmp_path / 'nested/paper Ω.pdf'
    make_pdf(target)
    assert pdf_indexer.find_pdf(tmp_path, attachment) == target.resolve()


@pytest.mark.parametrize('attachment', ['../paper.pdf', '%2e%2e/paper.pdf', '..\\paper.pdf', '/paper.pdf', '\\paper.pdf', 'C:paper.pdf', 'C:/paper.pdf', 'C:\\paper.pdf', '//server/share/paper.pdf', '\\\\server\\share\\paper.pdf', '\\\\?\\C:\\paper.pdf', 'paper.pdf:stream', 'nested/%2e%2e/paper.pdf', 'paper%00.pdf'])
def test_attachment_rejects_unsafe_forms(tmp_path, attachment):
    make_pdf(tmp_path / 'paper.pdf')
    assert pdf_indexer.find_pdf(tmp_path, attachment) is None


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction containment')
def test_attachment_rejects_escaping_junction(tmp_path):
    root, outside = tmp_path / 'PDF', tmp_path / 'outside'
    root.mkdir()
    make_pdf(outside / 'paper.pdf')
    junction = root / 'junction'
    result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(outside)], capture_output=True)
    if result.returncode:
        pytest.skip('Host does not permit creating junctions')
    assert pdf_indexer.find_pdf(root, 'junction/paper.pdf') is None
    assert pdf_indexer.find_pdf(root, 'paper.pdf') is None


@pytest.mark.skipif(os.name != 'nt', reason='Windows case-insensitive lookup')
def test_windows_basename_casefold_and_ambiguity(tmp_path):
    import endnote_mcp.pdf_indexer as module
    module._pdf_cache = {}
    module._pdf_cache_dir = None
    make_pdf(tmp_path / 'a/Paper.PDF')
    assert pdf_indexer.find_pdf(tmp_path, 'paper.pdf') == (tmp_path / 'a/Paper.PDF').resolve()
    make_pdf(tmp_path / 'b/paper.pdf')
    module._pdf_cache = {}
    assert pdf_indexer.find_pdf(tmp_path, 'paper.pdf') is None


def test_worker_corrupt_encrypted_blank_and_text(tmp_path):
    for name, text, encrypted, expected in [('text', 'Evidence', False, 'indexed'), ('blank', '', False, 'textless'), ('encrypted', '', True, 'failed')]:
        path = tmp_path / (name + '.pdf')
        make_pdf(path, text, encrypted)
        pages, status, error = pdf_indexer.extract_pages_checked(path)
        assert status == expected, error
        if expected == 'indexed':
            assert pages == [(1, 'Evidence')]
        else:
            assert pages == []
    corrupt = tmp_path / 'corrupt.pdf'
    corrupt.write_bytes(b'not a PDF')
    assert pdf_indexer.extract_pages_checked(corrupt)[1] == 'failed'


def test_worker_timeout_reaps_process_without_partial_text(tmp_path, monkeypatch):
    # Exercise the real worker command, including Windows venv redirection.
    pid = tmp_path / 'paper.pid'
    (tmp_path / 'pymupdf.py').write_text('''import os, pathlib, sys, time
class Diagnostics:
    def mupdf_display_errors(self, value): pass
    def mupdf_display_warnings(self, value): pass
TOOLS = Diagnostics()
def open(path):
    pathlib.Path(path).with_suffix('.pid').write_text(str(os.getpid()))
    print('partial output', flush=True)
    time.sleep(60)
''', encoding='utf-8')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv('PYTHONPATH', str(tmp_path) + os.pathsep + os.environ.get('PYTHONPATH', ''))
    real_popen = subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(pdf_indexer.subprocess, 'Popen', spawn)
    make_pdf(tmp_path / 'paper.pdf')
    start = time.monotonic()
    pages, status, error = pdf_indexer.extract_pages_checked(tmp_path / 'paper.pdf', timeout=3)
    assert time.monotonic() - start < 10
    assert (pages, status) == ([], 'failed')
    assert 'timed out' in error
    assert children[0].poll() is not None
    assert pid.exists()
    actual_pid = int(pid.read_text())
    assert actual_pid == children[0].pid
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, actual_pid)
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 0) == 0
            finally:
                kernel.CloseHandle(handle)
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(actual_pid, 0)


def test_worker_crash_and_interrupt_reap(tmp_path, monkeypatch):
    make_pdf(tmp_path / 'paper.pdf')
    monkeypatch.setattr(pdf_indexer, '_worker_command', lambda path: pdf_indexer._python_command('import os; os._exit(7)'))
    assert pdf_indexer.extract_pages_checked(tmp_path / 'paper.pdf')[1] == 'failed'
    monkeypatch.setattr(pdf_indexer, '_worker_command', lambda path: pdf_indexer._python_command('import time; time.sleep(60)'))
    real_popen = subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        real_communicate = child.communicate
        def interrupt(*args, **kwargs):
            if 'timeout' in kwargs:
                raise KeyboardInterrupt()
            return real_communicate(*args, **kwargs)
        child.communicate = interrupt
        return child
    monkeypatch.setattr(pdf_indexer.subprocess, 'Popen', spawn)
    with pytest.raises(KeyboardInterrupt):
        pdf_indexer.extract_pages(tmp_path / 'paper.pdf', strict=True)
    assert children[0].poll() is not None


def child_process(code, *args):
    return subprocess.Popen([sys.executable, '-u', '-c', code, *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_management_lock_recovers_after_process_killed(tmp_path):
    target = tmp_path / 'index.db'
    child = child_process("from endnote_mcp.locking import management_lock; import sys,time\nwith management_lock(sys.argv[1]):\n print('locked',flush=True); time.sleep(60)", target)
    try:
        assert child.stdout.readline().strip() == 'locked'
        with pytest.raises(RuntimeError, match='Another index/embed'):
            with management_lock(target):
                pass
    finally:
        child.kill()
        child.communicate(timeout=10)
    # An obsolete fallback directory is not an active OS lock.
    Path(str(target) + '.lock.d').mkdir()
    with management_lock(target):
        pass


@pytest.mark.skipif(os.name == 'nt', reason='Unix legacy flock compatibility')
def test_unix_management_lock_interoperates_with_legacy_manager(tmp_path):
    target = tmp_path / 'index.db'
    child = child_process("import fcntl,sys,time\nwith open(sys.argv[1]+'.lock','a+b') as stream:\n fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB); print('locked',flush=True); time.sleep(60)", target)
    try:
        assert child.stdout.readline().strip() == 'locked'
        with pytest.raises(RuntimeError, match='Another index/embed'):
            with management_lock(target):
                pass
    finally:
        child.kill()
        child.communicate(timeout=10)
    with management_lock(target):
        pass


@pytest.mark.skipif(os.name == 'nt', reason='Unix open-inode atomic publication')
def test_unix_publication_preserves_active_reader_snapshot(tmp_path):
    target, stage = tmp_path / 'index.db', tmp_path / 'stage.db'
    for path, version in [(target, 1), (stage, 2)]:
        with closing(db.connect(path)) as connection:
            connection.execute('CREATE TABLE acceptance(version)')
            connection.execute('INSERT INTO acceptance VALUES (?)', (version,))
            connection.commit()
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            connection.execute('PRAGMA journal_mode=DELETE')
    with closing(db.connect_readonly(target)) as reader:
        publisher = child_process('from endnote_mcp.locking import publish_database; import sys; publish_database(sys.argv[1],sys.argv[2])', stage, target)
        try:
            _, stderr = publisher.communicate(timeout=10)
            assert publisher.returncode == 0, stderr
            assert reader.execute('SELECT version FROM acceptance').fetchone()[0] == 1
            with closing(db.connect_readonly(target)) as current:
                assert current.execute('SELECT version FROM acceptance').fetchone()[0] == 2
        finally:
            if publisher.poll() is None:
                publisher.kill()
            publisher.communicate()


@pytest.mark.skipif(os.name != 'nt', reason='Windows reader/publication gate')
def test_reader_blocks_publication_then_releases(tmp_path):
    target = tmp_path / 'index.db'
    stage = tmp_path / 'stage.db'
    for path, version in [(target, 1), (stage, 2)]:
        with closing(db.connect(path)) as connection:
            connection.execute('CREATE TABLE acceptance(version)')
            connection.execute('INSERT INTO acceptance VALUES (?)', (version,))
            connection.commit()
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            connection.execute('PRAGMA journal_mode=DELETE')
    reader = db.connect_readonly(target)
    publisher = child_process("from endnote_mcp.locking import publish_database; import sys\nprint('starting',flush=True); publish_database(sys.argv[1],sys.argv[2]); print('published',flush=True)", stage, target)
    try:
        assert publisher.stdout.readline().strip() == 'starting'
        time.sleep(.25)
        assert publisher.poll() is None
        assert reader.execute('SELECT version FROM acceptance').fetchone()[0] == 1
        reader.close()
        stdout, stderr = publisher.communicate(timeout=10)
        assert publisher.returncode == 0, stderr
        assert 'published' in stdout
        with closing(db.connect_readonly(target)) as connection:
            assert connection.execute('SELECT version FROM acceptance').fetchone()[0] == 2
    finally:
        reader.close()
        if publisher.poll() is None:
            publisher.kill()
        publisher.communicate()


@pytest.mark.skipif(os.name != 'nt', reason='Windows reader/publication gate')
def test_failed_publication_preserves_index_and_mcp_busy(tmp_path, monkeypatch):
    from endnote_mcp import locking
    from endnote_mcp.desktop_runtime import DesktopRuntime
    pdfs = tmp_path / 'PDF'
    pdfs.mkdir()
    xml = tmp_path / 'export.xml'
    xml.write_text('<xml><records><record><rec-number>1</rec-number></record></records></xml>')
    cfg = Config(xml, pdfs, tmp_path / 'index.db')
    index_library(cfg)
    before = cfg.db_path.read_bytes()
    reader = db.connect_readonly(cfg.db_path)
    monkeypatch.setattr(locking, 'LOCK_TIMEOUT', .15)
    try:
        with pytest.raises(IndexBusyError):
            index_library(cfg, full=True)
        assert cfg.db_path.read_bytes() == before
        assert not list(tmp_path.glob('.*-stage-*'))
        config = tmp_path / 'config.yaml'
        import yaml
        config.write_text(yaml.safe_dump({'endnote_xml': str(xml), 'pdf_dir': str(pdfs), 'db_path': str(cfg.db_path)}), encoding='utf-8')
        result = DesktopRuntime(config).invoke_tool('search_references', {'query': 'test'})
        assert result['error']['code'] == 'index_busy'
    finally:
        reader.close()
    assert index_library(cfg)['total_references'] == 1


def test_config_utf8_and_powershell_command(tmp_path):
    from endnote_mcp.desktop_cli import shell_command
    import yaml
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump({'endnote_xml': str(tmp_path / "export Ω'.xml"), 'pdf_dir': str(tmp_path / 'PDF Ω')}, allow_unicode=True), encoding='utf-8')
    assert 'Ω' in str(Config.load(path).endnote_xml)
    if os.name == 'nt':
        command = shell_command(['codex', 'mcp', 'add', 'endnote', '--', r"C:\a b\run.exe", '--config', r"C:\a'b\Ω & $!.yaml"])
        assert r"'C:\a''b\Ω & $!.yaml'" in command


def test_optional_native_dependency_failure_is_unavailable(monkeypatch):
    import builtins
    from endnote_mcp import embeddings
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == 'numpy':
            raise OSError('Native DLL unavailable')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', unavailable)
    assert not embeddings.is_available()
