"""SQLite schema with FTS5 full-text search indexes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2


class IncompatibleIndexError(RuntimeError):
    """The derived index must be rebuilt locally."""


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Index missing. Run chatgpt-endnote-mcp index locally.")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        required = {
            "references_": {"rec_number", "research_notes", "fingerprint"},
            "attachments": {"attachment_id", "relative_path", "status", "fingerprint"},
            "pdf_pages": {"attachment_id", "text_content", "page_number"},
            "reference_embeddings": {"rec_number", "embedding", "model_name"},
            "references_fts": {"research_notes"},
            "pdf_fts": {"text_content"},
        }
        valid = conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        for table, columns in required.items():
            present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            valid = valid and columns.issubset(present)
        if not valid:
            raise IncompatibleIndexError("Index schema incompatible. Run chatgpt-endnote-mcp index locally.")
    except (sqlite3.DatabaseError, IncompatibleIndexError) as exc:
        conn.close()
        raise IncompatibleIndexError("Index missing or incompatible. Run chatgpt-endnote-mcp index locally.") from exc
    return conn


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the database and ensure the schema exists."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='references_'").fetchone()
    if exists and version != SCHEMA_VERSION:
        conn.close()
        raise IncompatibleIndexError("Index schema incompatible. Rebuild into a replacement database.")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_schema(conn)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        -- Main references table
        CREATE TABLE IF NOT EXISTS references_ (
            rec_number   INTEGER PRIMARY KEY,
            ref_type     TEXT,
            title        TEXT,
            authors      TEXT,          -- JSON array of author names
            year         TEXT,
            journal      TEXT,
            volume       TEXT,
            issue        TEXT,
            pages        TEXT,
            abstract     TEXT,
            keywords     TEXT,          -- JSON array
            doi          TEXT,
            url          TEXT,
            publisher    TEXT,
            place_published TEXT,
            edition      TEXT,
            isbn         TEXT,
            label        TEXT,
            notes        TEXT,
            research_notes TEXT,
            fingerprint TEXT,
            pdf_path     TEXT           -- relative to pdf_dir
        );

        -- FTS5 index over reference metadata (weighted BM25)
        CREATE VIRTUAL TABLE IF NOT EXISTS references_fts USING fts5(
            title,
            authors,
            abstract,
            keywords,
            journal,
            research_notes,
            content='references_',
            content_rowid='rec_number',
            tokenize='porter unicode61'
        );

        -- Triggers to keep references_fts in sync
        CREATE TRIGGER IF NOT EXISTS references_ai AFTER INSERT ON references_
        BEGIN
            INSERT INTO references_fts(rowid, title, authors, abstract, keywords, journal, research_notes)
            VALUES (NEW.rec_number, NEW.title, NEW.authors, NEW.abstract, NEW.keywords, NEW.journal, NEW.research_notes);
        END;

        CREATE TRIGGER IF NOT EXISTS references_ad AFTER DELETE ON references_
        BEGIN
            INSERT INTO references_fts(references_fts, rowid, title, authors, abstract, keywords, journal, research_notes)
            VALUES ('delete', OLD.rec_number, OLD.title, OLD.authors, OLD.abstract, OLD.keywords, OLD.journal, OLD.research_notes);
        END;

        CREATE TRIGGER IF NOT EXISTS references_au AFTER UPDATE ON references_
        BEGIN
            INSERT INTO references_fts(references_fts, rowid, title, authors, abstract, keywords, journal, research_notes)
            VALUES ('delete', OLD.rec_number, OLD.title, OLD.authors, OLD.abstract, OLD.keywords, OLD.journal, OLD.research_notes);
            INSERT INTO references_fts(rowid, title, authors, abstract, keywords, journal, research_notes)
            VALUES (NEW.rec_number, NEW.title, NEW.authors, NEW.abstract, NEW.keywords, NEW.journal, NEW.research_notes);
        END;

        CREATE TABLE IF NOT EXISTS attachments (
            attachment_id TEXT PRIMARY KEY,
            rec_number INTEGER NOT NULL REFERENCES references_(rec_number) ON DELETE CASCADE,
            relative_path TEXT NOT NULL,
            resolved_path TEXT,
            fingerprint TEXT,
            status TEXT NOT NULL CHECK(status IN ('indexed','missing','failed','textless','outdated')),
            error TEXT
        );

        -- PDF page content
        CREATE TABLE IF NOT EXISTS pdf_pages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            rec_number   INTEGER NOT NULL REFERENCES references_(rec_number) ON DELETE CASCADE,
            attachment_id TEXT REFERENCES attachments(attachment_id) ON DELETE CASCADE,
            page_number  INTEGER NOT NULL,
            text_content TEXT,
            UNIQUE(rec_number, attachment_id, page_number)
        );

        -- FTS5 index over PDF text
        CREATE VIRTUAL TABLE IF NOT EXISTS pdf_fts USING fts5(
            text_content,
            content='pdf_pages',
            content_rowid='id',
            tokenize='porter unicode61'
        );

        -- Triggers for pdf_fts sync
        CREATE TRIGGER IF NOT EXISTS pdf_pages_ai AFTER INSERT ON pdf_pages
        BEGIN
            INSERT INTO pdf_fts(rowid, text_content)
            VALUES (NEW.id, NEW.text_content);
        END;

        CREATE TRIGGER IF NOT EXISTS pdf_pages_ad AFTER DELETE ON pdf_pages
        BEGIN
            INSERT INTO pdf_fts(pdf_fts, rowid, text_content)
            VALUES ('delete', OLD.id, OLD.text_content);
        END;

        CREATE TRIGGER IF NOT EXISTS pdf_pages_au AFTER UPDATE ON pdf_pages
        BEGIN
            INSERT INTO pdf_fts(pdf_fts, rowid, text_content)
            VALUES ('delete', OLD.id, OLD.text_content);
            INSERT INTO pdf_fts(rowid, text_content)
            VALUES (NEW.id, NEW.text_content);
        END;

        -- Indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_references_year ON references_(year);
        CREATE INDEX IF NOT EXISTS idx_references_doi ON references_(doi);
        CREATE INDEX IF NOT EXISTS idx_pdf_pages_rec ON pdf_pages(rec_number);

        -- Embedding vectors for semantic search
        CREATE TABLE IF NOT EXISTS reference_embeddings (
            rec_number  INTEGER PRIMARY KEY REFERENCES references_(rec_number) ON DELETE CASCADE,
            embedding   BLOB NOT NULL,
            model_name  TEXT NOT NULL
        );
    """)


def upsert_reference(conn: sqlite3.Connection, ref: dict) -> None:
    """Insert or update a reference record.

    Uses ON CONFLICT DO UPDATE instead of INSERT OR REPLACE to avoid
    triggering ON DELETE CASCADE on pdf_pages and reference_embeddings.
    """
    ref = {"research_notes": "", "fingerprint": "", **ref}
    conn.execute("""
        INSERT INTO references_(
            rec_number, ref_type, title, authors, year, journal,
            volume, issue, pages, abstract, keywords, doi, url,
            publisher, place_published, edition, isbn, label, notes, pdf_path, research_notes, fingerprint
        ) VALUES (
            :rec_number, :ref_type, :title, :authors, :year, :journal,
            :volume, :issue, :pages, :abstract, :keywords, :doi, :url,
            :publisher, :place_published, :edition, :isbn, :label, :notes, :pdf_path, :research_notes, :fingerprint
        )
        ON CONFLICT(rec_number) DO UPDATE SET
            ref_type=excluded.ref_type, title=excluded.title,
            authors=excluded.authors, year=excluded.year,
            journal=excluded.journal, volume=excluded.volume,
            issue=excluded.issue, pages=excluded.pages,
            abstract=excluded.abstract, keywords=excluded.keywords,
            doi=excluded.doi, url=excluded.url,
            publisher=excluded.publisher, place_published=excluded.place_published,
            edition=excluded.edition, isbn=excluded.isbn,
            label=excluded.label, notes=excluded.notes,
            pdf_path=excluded.pdf_path, research_notes=excluded.research_notes,
            fingerprint=excluded.fingerprint
    """, ref)


def insert_pdf_page(conn: sqlite3.Connection, rec_number: int, page_number: int, text: str, attachment_id: str | None = None) -> None:
    """Insert a single PDF page's text."""
    conn.execute("DELETE FROM pdf_pages WHERE rec_number=? AND page_number=? AND attachment_id IS ?",
                 (rec_number, page_number, attachment_id))
    conn.execute("INSERT INTO pdf_pages(rec_number,page_number,text_content,attachment_id) VALUES (?,?,?,?)",
                 (rec_number, page_number, text, attachment_id))


def clear_all(conn: sqlite3.Connection) -> None:
    """Drop all data for a full re-index."""
    conn.executescript("""
        DELETE FROM reference_embeddings;
        DELETE FROM pdf_pages;
        DELETE FROM attachments;
        DELETE FROM references_;
        -- Rebuild FTS indexes
        INSERT INTO references_fts(references_fts) VALUES('rebuild');
        INSERT INTO pdf_fts(pdf_fts) VALUES('rebuild');
    """)


def upsert_embedding(conn: sqlite3.Connection, rec_number: int, embedding: bytes, model_name: str) -> None:
    """Insert or replace an embedding vector for a reference."""
    conn.execute(
        "INSERT OR REPLACE INTO reference_embeddings(rec_number, embedding, model_name) VALUES (?, ?, ?)",
        (rec_number, embedding, model_name),
    )


def clear_embeddings(conn: sqlite3.Connection) -> None:
    """Delete all embeddings."""
    conn.execute("DELETE FROM reference_embeddings")
    conn.commit()


def get_stats(conn: sqlite3.Connection) -> dict:
    """Return index statistics."""
    ref_count = conn.execute("SELECT COUNT(*) FROM references_").fetchone()[0]
    pdf_page_count = conn.execute("SELECT COUNT(*) FROM pdf_pages").fetchone()[0]
    refs_with_pdf = conn.execute(
        "SELECT COUNT(DISTINCT rec_number) FROM pdf_pages"
    ).fetchone()[0]
    embeddings_count = conn.execute("SELECT COUNT(*) FROM reference_embeddings").fetchone()[0]
    attachment_statuses = dict(conn.execute("SELECT status,COUNT(*) FROM attachments GROUP BY status"))
    return {
        "attachment_statuses": attachment_statuses,
        "total_attachments": sum(attachment_statuses.values()),
        "schema_version": SCHEMA_VERSION,
        "total_references": ref_count,
        "total_pdf_pages": pdf_page_count,
        "references_with_pdf": refs_with_pdf,
        "references_with_embeddings": embeddings_count,
    }
