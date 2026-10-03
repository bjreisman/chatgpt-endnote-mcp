"""Extract text from PDFs using PyMuPDF (fitz)."""

from __future__ import annotations

import contextlib
import logging
import os
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote

import pymupdf as fitz


@contextlib.contextmanager
def _suppress_stderr():
    """Suppress stderr to silence harmless MuPDF warnings."""
    stderr_fd = sys.stderr.fileno()
    old_fd = os.dup(stderr_fd)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, stderr_fd)
        yield
    finally:
        os.dup2(old_fd, stderr_fd)
        os.close(old_fd)
        os.close(devnull)


logger = logging.getLogger(__name__)

# Cached filename → path mapping (built once per pdf_dir)
_pdf_cache: dict[str, list[Path]] = {}
_pdf_cache_dir: Path | None = None


def _build_pdf_cache(pdf_dir: Path) -> None:
    """Scan pdf_dir once and cache all PDF paths by filename."""
    global _pdf_cache, _pdf_cache_dir
    if _pdf_cache_dir == pdf_dir and _pdf_cache:
        return
    logger.info("Building PDF file cache for %s...", pdf_dir)
    _pdf_cache = {}
    for path in pdf_dir.rglob("*.[pP][dD][fF]"):
        key = path.name.casefold() if os.name == 'nt' else path.name
        _pdf_cache.setdefault(key, []).append(path)
        # Also index URL-decoded name
        decoded = unquote(path.name)
        if decoded != path.name:
            key = decoded.casefold() if os.name == 'nt' else decoded
            _pdf_cache.setdefault(key, []).append(path)
    _pdf_cache_dir = pdf_dir
    logger.info("Cached %d PDF files.", len(_pdf_cache))


def _worker_command(path):
    return [sys.executable, '-m', 'endnote_mcp.pdf_worker', str(path)]


def extract_pages(pdf_path: str | Path, timeout: int = 30, *, strict: bool = False) -> list[tuple[int, str]]:
    """Extract all pages under a portable deadline; never return partial text."""
    process = None
    try:
        process = subprocess.Popen(_worker_command(Path(pdf_path).resolve()),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError('PDF extraction timed out') from exc
        if process.returncode:
            raise RuntimeError('PDF extraction worker failed: ' + stderr.decode('utf-8', errors='replace')[-2000:])
        result = json.loads(stdout.decode('utf-8'))
        if result.get('error'):
            raise ValueError(result['error'])
        return [(int(n), text) for n, text in result['pages']]
    except Exception as exc:
        if strict:
            raise
        logger.warning('Failed to extract PDF %s: %s', Path(pdf_path).name, exc)
        return []
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate()


def read_pages(pdf_path: str | Path, start: int, end: int) -> list[dict]:
    """Read specific pages from a PDF.

    Args:
        pdf_path: Path to the PDF file.
        start: First page to read (1-based, inclusive).
        end: Last page to read (1-based, inclusive).

    Returns:
        List of dicts with 'page' and 'text' keys.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    with _suppress_stderr():
        doc = fitz.open(str(pdf_path))
    results = []
    try:
        total = len(doc)
        start = max(1, start)
        end = min(total, end)
        with _suppress_stderr():
            for page_num in range(start, end + 1):
                page = doc[page_num - 1]
                text = page.get_text("text").strip()
                results.append({"page": page_num, "text": text, "total_pages": total})
    finally:
        doc.close()

    return results


def find_pdf(pdf_dir: Path, pdf_filename: str) -> Path | None:
    """Resolve exact relative paths first, then only a unique basename.

    Invalid paths and symlinks outside the configured root never resolve.
    """
    if not pdf_filename:
        return None
    root = Path(pdf_dir).resolve()
    decoded = unquote(pdf_filename)
    windows = PureWindowsPath(decoded)
    relative = PurePosixPath(decoded.replace('\\', '/'))
    if (windows.drive or windows.root or relative.is_absolute()
            or '..' in relative.parts or ':' in decoded or '\0' in decoded):
        return None
    direct = root / relative
    if direct.exists():
        resolved = direct.resolve()
        return resolved if resolved.is_relative_to(root) and resolved.is_file() else None
    _build_pdf_cache(root)
    candidates = set()
    key = relative.name.casefold() if os.name == 'nt' else relative.name
    for path in _pdf_cache.get(key, []):
        resolved = path.resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            candidates.add(resolved)
    return next(iter(candidates)) if len(candidates) == 1 else None


def fingerprint_file(path: str | Path) -> str:
    """Hash file content so changed PDFs invalidate cached evidence."""
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pages_checked(pdf_path: str | Path, timeout: int = 30) -> tuple[list[tuple[int, str]], str, str]:
    """Return pages, extraction status and diagnostic without partial success."""
    path = Path(pdf_path)
    if path.stat().st_size > 200 * 1024 * 1024:
        return [], "failed", "PDF exceeds 200 MB extraction limit"
    try:
        pages = extract_pages(path, timeout=timeout, strict=True)
    except Exception as exc:
        return [], "failed", str(exc)
    return pages, "indexed" if pages else "textless", ""
