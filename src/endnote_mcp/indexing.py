"""Atomic local imports into a product-specific derived index."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from endnote_mcp.locking import management_lock, publish_database
from endnote_mcp import db
from endnote_mcp.endnote_parser import parse_endnote_xml
from endnote_mcp.pdf_indexer import extract_pages_checked, find_pdf, fingerprint_file


def attachment_id(rec_number: int, relative_path: str) -> str:
    return hashlib.sha256(f"{rec_number}\0{relative_path}".encode()).hexdigest()



def index_library(cfg, full=False, skip_pdfs=False, sync_deletions=False, progress=None) -> dict:
    """Serialize a staged import; optional progress reports every 100 records."""
    with management_lock(cfg.db_path):
        return _index_library(cfg, full, skip_pdfs, sync_deletions, progress)


def _index_library(cfg, full=False, skip_pdfs=False, sync_deletions=False, progress=None) -> dict:
    """Upsert a complete parsed export in a stage; promote only on success.

    A failed parse, extraction interruption, or schema rebuild leaves the previous
    database untouched. The public wrapper serializes management operations.
    """
    target = Path(cfg.db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}-stage-", suffix=".db", dir=target.parent)
    os.close(fd)
    stage = Path(name)
    conn = None
    counters = {"records_imported": 0, "records_changed": 0, "attachments_changed": 0, "records_deleted": 0}
    try:
        if target.exists() and not full:
            try:
                source = db.connect_readonly(target)
            except db.IncompatibleIndexError:
                source = None  # Rebuild incompatible derived schemas in the stage.
            if source is not None:
                try:
                    destination = sqlite3.connect(stage)
                    try:
                        source.backup(destination)
                    finally:
                        destination.close()
                finally:
                    source.close()
        conn = db.connect(stage)
        # Avoid stale filename caches across separate indexing runs.
        from endnote_mcp import pdf_indexer
        pdf_indexer._pdf_cache = {}
        pdf_indexer._pdf_cache_dir = None
        seen = set()
        for ref in parse_endnote_xml(cfg.endnote_xml):
            rec = ref["rec_number"]
            if rec in seen:
                raise ValueError(f"Duplicate record ID {rec} in export")
            seen.add(rec)
            counters["records_imported"] += 1
            if progress is not None and counters["records_imported"] % 100 == 0:
                progress(counters["records_imported"])
            fingerprint = hashlib.sha256(json.dumps(ref, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            previous = conn.execute("SELECT fingerprint FROM references_ WHERE rec_number=?", (rec,)).fetchone()
            if previous is None or previous[0] != fingerprint:
                counters["records_changed"] += 1
                conn.execute("DELETE FROM reference_embeddings WHERE rec_number=?", (rec,))
                db.upsert_reference(conn, {**ref, "fingerprint": fingerprint})
            paths = ref["attachments"]
            wanted = {attachment_id(rec, path) for path in paths}
            for old in conn.execute("SELECT attachment_id FROM attachments WHERE rec_number=?", (rec,)).fetchall():
                if old[0] not in wanted:
                    conn.execute("DELETE FROM attachments WHERE attachment_id=?", (old[0],))
                    conn.execute("DELETE FROM reference_embeddings WHERE rec_number=?", (rec,))
            for relative in paths:
                ident = attachment_id(rec, relative)
                old = conn.execute("SELECT * FROM attachments WHERE attachment_id=?", (ident,)).fetchone()
                resolved = find_pdf(Path(cfg.pdf_dir), relative)
                content_hash = fingerprint_file(resolved) if resolved else ""
                if old and old["fingerprint"] == content_hash and old["status"] in ("indexed", "textless") and str(resolved) == old["resolved_path"]:
                    continue
                counters["attachments_changed"] += 1
                conn.execute("DELETE FROM reference_embeddings WHERE rec_number=?", (rec,))
                conn.execute("DELETE FROM pdf_pages WHERE attachment_id=?", (ident,))
                if resolved is None:
                    pages, status, error = [], "missing", "Attachment missing, unsafe, or filename ambiguous"
                elif skip_pdfs:
                    pages, status, error = [], "outdated", "Run indexing without --skip-pdfs to extract text"
                else:
                    timeout = 120 if resolved.stat().st_size > 50 * 1024 * 1024 else 30
                    pages, status, error = extract_pages_checked(resolved, timeout=timeout)
                    # A PDF changed while being extracted must never become current evidence.
                    if fingerprint_file(resolved) != content_hash:
                        pages, status, error = [], "outdated", "PDF changed during extraction; reindex locally"
                conn.execute("""INSERT INTO attachments VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(attachment_id) DO UPDATE SET resolved_path=excluded.resolved_path,
                    fingerprint=excluded.fingerprint,status=excluded.status,error=excluded.error""",
                    (ident, rec, relative, str(resolved) if resolved else None, content_hash, status, error))
                for page, text in pages:
                    db.insert_pdf_page(conn, rec, page, text, ident)
        # This point is reached only when iterparse consumed a well-formed full document.
        if sync_deletions:
            for row in conn.execute("SELECT rec_number FROM references_").fetchall():
                if row[0] not in seen:
                    conn.execute("DELETE FROM references_ WHERE rec_number=?", (row[0],))
                    counters["records_deleted"] += 1
        conn.commit()
        stats = {**db.get_stats(conn), **counters}
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.close()
        conn = None
        publish_database(stage, target)
        return stats
    finally:
        if conn is not None:
            conn.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(stage) + suffix).unlink(missing_ok=True)
