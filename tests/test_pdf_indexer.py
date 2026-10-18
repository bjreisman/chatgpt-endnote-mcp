"""Tests for PDF file lookup."""

from pathlib import Path
import unicodedata
from urllib.parse import quote

import pytest

from endnote_mcp.pdf_indexer import find_pdf, read_pages, _pdf_cache, _pdf_cache_dir


@pytest.fixture(autouse=True)
def _reset_pdf_cache():
    """Reset the global PDF cache between tests."""
    import endnote_mcp.pdf_indexer as mod
    mod._pdf_cache = {}
    mod._pdf_cache_dir = None
    yield
    mod._pdf_cache = {}
    mod._pdf_cache_dir = None


def test_find_pdf_direct(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    result = find_pdf(tmp_path, "test.pdf")
    assert result == pdf


def test_find_pdf_cache(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    pdf = subdir / "nested.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    # Not at direct path, should be found via cache
    result = find_pdf(tmp_path, "nested.pdf")
    assert result == pdf


def test_find_pdf_not_found(tmp_path):
    result = find_pdf(tmp_path, "nonexistent.pdf")
    assert result is None


def test_find_pdf_empty_filename(tmp_path):
    result = find_pdf(tmp_path, "")
    assert result is None


def test_find_pdf_url_decoded(tmp_path):
    # Create a file with spaces in the name
    pdf = tmp_path / "my paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    # Look up with URL-encoded name
    encoded_name = quote("my paper.pdf")
    result = find_pdf(tmp_path, encoded_name)
    assert result == pdf


@pytest.mark.parametrize('disk_form,query_form', [('NFD', 'NFC'), ('NFC', 'NFD')])
@pytest.mark.parametrize('encoded_query', [False, True])
def test_find_pdf_unicode_forms(tmp_path, disk_form, query_form, encoded_query):
    # Nest the file to exercise cache lookup even on normalization-insensitive macOS.
    folder = tmp_path / 'record'
    folder.mkdir()
    name = 'Müller-ş-é.pdf'
    pdf = folder / unicodedata.normalize(disk_form, name)
    pdf.write_bytes(b'%PDF-1.4 fake')
    query = unicodedata.normalize(query_form, name)
    assert find_pdf(tmp_path, quote(query) if encoded_query else query) == pdf.resolve()


def test_find_pdf_unicode_url_encoded_disk_name(tmp_path):
    folder = tmp_path / 'record'
    folder.mkdir()
    pdf = folder / quote(unicodedata.normalize('NFD', 'Müller.pdf'))
    pdf.write_bytes(b'%PDF-1.4 fake')
    assert find_pdf(tmp_path, 'Müller.pdf') == pdf.resolve()


def test_find_pdf_unicode_ambiguity_preserves_exact_paths(tmp_path):
    paths = []
    for folder, form in [('first', 'NFC'), ('second', 'NFD')]:
        directory = tmp_path / folder
        directory.mkdir()
        pdf = directory / unicodedata.normalize(form, 'Müller.pdf')
        pdf.write_bytes(b'%PDF-1.4 fake')
        paths.append(pdf)
    assert find_pdf(tmp_path, 'Müller.pdf') is None
    for pdf in paths:
        assert find_pdf(tmp_path, pdf.relative_to(tmp_path).as_posix()) == pdf.resolve()


def test_find_pdf_unicode_alias_cannot_escape_root(tmp_path):
    root = tmp_path / 'PDF'
    folder = root / 'record'
    folder.mkdir(parents=True)
    outside = tmp_path / 'outside.pdf'
    outside.write_bytes(b'%PDF-1.4 fake')
    (folder / unicodedata.normalize('NFD', 'Müller.pdf')).symlink_to(outside)
    assert find_pdf(root, 'Müller.pdf') is None
    assert find_pdf(root, quote('../outside.pdf')) is None


def test_read_pages_not_found():
    with pytest.raises(FileNotFoundError):
        read_pages("/nonexistent/path/to.pdf", 1, 5)
