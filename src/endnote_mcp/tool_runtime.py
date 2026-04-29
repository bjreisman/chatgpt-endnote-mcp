"""Shared tool runtime for local MCP and bridge-based execution."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from endnote_mcp.config import Config
from endnote_mcp.db import connect
from endnote_mcp.search import (
    find_related as _find_related,
    get_reference_details as _get_details,
    get_references_batch as _get_refs_batch,
    list_by_topic as _list_topic,
    search_fulltext as _search_ft,
    search_library as _search_lib,
    search_references as _search_refs,
    search_semantic as _search_semantic,
)
from endnote_mcp.citation import format_bibtex, format_citation
from endnote_mcp.pdf_indexer import find_pdf, read_pages


def _doi_link(doi: str) -> str:
    """Format a DOI as a clickable link, or return empty string."""
    if not doi:
        return ""
    doi = doi.strip()
    if doi.startswith("http"):
        return f"  DOI: {doi}"
    return f"  DOI: https://doi.org/{doi}"


class EndNoteToolRuntime:
    """Execute EndNote tools against local config and database."""

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path).expanduser().resolve() if config_path else None
        self._config: Config | None = None

    def _get_config(self) -> Config:
        if self._config is None:
            self._config = Config.load(self.config_path)
        return self._config

    def _connect(self):
        cfg = self._get_config()
        return connect(cfg.db_path)

    def invoke_tool(self, tool_name: str, arguments: dict | None = None) -> str:
        """Invoke a runtime method by name."""
        arguments = arguments or {}
        try:
            method = getattr(self, tool_name)
        except AttributeError as exc:
            raise ValueError(f"Unknown tool: {tool_name}") from exc
        return method(**arguments)

    def search_references(
        self,
        query: str,
        year_from: str | None = None,
        year_to: str | None = None,
        author: str | None = None,
        ref_type: str | None = None,
        limit: int = 50,
    ) -> str:
        with self._connect() as conn:
            results = _search_refs(
                conn,
                query,
                year_from=year_from,
                year_to=year_to,
                author=author,
                ref_type=ref_type,
                limit=limit,
            )
        if not results:
            return f"No references found for: {query}"
        lines = [f"Found {len(results)} reference(s):\n"]
        for r in results:
            kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
            lines.append(
                f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}."
                + (f" *{r['journal']}*." if r.get("journal") else "")
                + _doi_link(r.get("doi", ""))
                + (f"  Keywords: {kw}" if kw else "")
            )
        return "\n".join(lines)

    def search_fulltext(self, query: str, limit: int = 50) -> str:
        with self._connect() as conn:
            results = _search_ft(conn, query, limit=limit)
        if not results:
            return f"No fulltext matches for: {query}"
        total_snippets = sum(len(r["snippets"]) for r in results)
        lines = [f"Found {total_snippets} match(es) across {len(results)} reference(s):\n"]
        for r in results:
            lines.append(
                f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}"
                + _doi_link(r.get("doi", ""))
            )
            for s in r["snippets"]:
                lines.append(f"      — page {s['page']}: ...{s['snippet']}...")
        return "\n".join(lines)

    def search_library(
        self,
        query: str,
        year_from: str | None = None,
        year_to: str | None = None,
        author: str | None = None,
        ref_type: str | None = None,
        limit: int = 30,
    ) -> str:
        with self._connect() as conn:
            results = _search_lib(
                conn,
                query,
                year_from=year_from,
                year_to=year_to,
                author=author,
                ref_type=ref_type,
                limit=limit,
            )
        if not results:
            return f"No references found for: {query}"

        with_pdf = sum(1 for r in results if r.get("snippets"))
        lines = [f"Found {len(results)} reference(s) ({with_pdf} with PDF matches):\n"]
        for r in results:
            kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
            lines.append(
                f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}."
                + (f" *{r['journal']}*." if r.get("journal") else "")
                + _doi_link(r.get("doi", ""))
            )
            if kw:
                lines.append(f"    Keywords: {kw}")
            if r.get("snippets"):
                lines.append("    PDF matches:")
                for s in r["snippets"]:
                    lines.append(f"      — page {s['page']}: ...{s['snippet']}...")
        return "\n".join(lines)

    def get_reference_details(self, rec_number: int) -> str:
        with self._connect() as conn:
            ref = _get_details(conn, rec_number)
        if ref is None:
            return f"Reference #{rec_number} not found."

        lines = [f"Reference #{rec_number}:"]
        lines.append(f"  Type: {ref.get('ref_type', 'Unknown')}")
        lines.append(f"  Title: {ref.get('title', '')}")
        authors = ref.get("authors", [])
        if authors:
            lines.append(f"  Authors: {'; '.join(authors)}")
        lines.append(f"  Year: {ref.get('year', '')}")
        if ref.get("journal"):
            lines.append(f"  Journal: {ref['journal']}")
        if ref.get("volume"):
            vol = ref["volume"]
            if ref.get("issue"):
                vol += f"({ref['issue']})"
            lines.append(f"  Volume: {vol}")
        if ref.get("pages"):
            lines.append(f"  Pages: {ref['pages']}")
        if ref.get("doi"):
            lines.append(f"  DOI: {ref['doi']}")
        if ref.get("url"):
            lines.append(f"  URL: {ref['url']}")
        if ref.get("publisher"):
            lines.append(f"  Publisher: {ref['publisher']}")
        if ref.get("isbn"):
            lines.append(f"  ISBN: {ref['isbn']}")
        keywords = ref.get("keywords", [])
        if keywords:
            lines.append(f"  Keywords: {', '.join(keywords)}")
        if ref.get("abstract"):
            lines.append(f"  Abstract: {ref['abstract']}")
        lines.append(f"  Indexed PDF pages: {ref.get('indexed_pdf_pages', 0)}")
        if ref.get("pdf_path"):
            lines.append(f"  PDF: {ref['pdf_path']}")
        return "\n".join(lines)

    def get_citation(self, rec_number: int, style: str = "apa7") -> str:
        with self._connect() as conn:
            ref = _get_details(conn, rec_number)
        if ref is None:
            return f"Reference #{rec_number} not found."
        try:
            citation = format_citation(ref, style)
        except ValueError as exc:
            return str(exc)
        return f"[{style.upper()}] {citation}"

    def read_pdf_section(self, rec_number: int, start_page: int = 1, end_page: int = 5) -> str:
        cfg = self._get_config()
        with self._connect() as conn:
            ref = _get_details(conn, rec_number)
        if ref is None:
            return f"Reference #{rec_number} not found."

        pdf_filename = ref.get("pdf_path", "")
        if not pdf_filename:
            return f"No PDF attachment for reference #{rec_number}."

        pdf_path = find_pdf(cfg.pdf_dir, pdf_filename)
        if pdf_path is None:
            return f"PDF file not found: {pdf_filename}"

        max_pages = cfg.max_pdf_pages
        if end_page - start_page + 1 > max_pages:
            end_page = start_page + max_pages - 1

        try:
            pages = read_pages(pdf_path, start_page, end_page)
        except Exception as exc:
            return f"Error reading PDF: {exc}"

        if not pages:
            return f"No text extracted from pages {start_page}-{end_page}."

        lines = [f"PDF: {ref.get('title', '')} — pages {start_page}-{end_page} (of {pages[0]['total_pages']})\n"]
        for p in pages:
            lines.append(f"--- Page {p['page']} ---")
            lines.append(p["text"])
            lines.append("")
        return "\n".join(lines)

    def list_references_by_topic(
        self,
        topic: str,
        year_from: str | None = None,
        year_to: str | None = None,
        ref_type: str | None = None,
        limit: int = 50,
    ) -> str:
        with self._connect() as conn:
            results = _list_topic(conn, topic, year_from=year_from, year_to=year_to, ref_type=ref_type, limit=limit)
        if not results:
            return f"No references found for topic: {topic}"
        lines = [f"Found {len(results)} reference(s) on '{topic}':\n"]
        for r in results:
            kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
            lines.append(
                f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}."
                + (f" *{r['journal']}*." if r.get("journal") else "")
                + _doi_link(r.get("doi", ""))
                + (f"  Keywords: {kw}" if kw else "")
            )
        return "\n".join(lines)

    def find_related(self, rec_number: int, limit: int = 10) -> str:
        with self._connect() as conn:
            ref = _get_details(conn, rec_number)
            if ref is None:
                return f"Reference #{rec_number} not found."
            results = _find_related(conn, rec_number, limit=limit)
        if not results:
            return f"No related references found for #{rec_number}."
        title = ref.get("title", "")
        lines = [f"References related to [{rec_number}] {title}:\n"]
        for r in results:
            kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
            lines.append(
                f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}."
                + (f" *{r['journal']}*." if r.get("journal") else "")
                + _doi_link(r.get("doi", ""))
                + (f"  Keywords: {kw}" if kw else "")
            )
        return "\n".join(lines)

    def get_bibliography(self, rec_numbers: str, style: str = "apa7", sort: str = "author") -> str:
        try:
            numbers = [int(x.strip()) for x in rec_numbers.split(",") if x.strip()]
        except ValueError:
            return "Invalid rec_numbers format. Use comma-separated integers (e.g. '12,45,78')."
        if not numbers:
            return "No record numbers provided."

        with self._connect() as conn:
            refs = _get_refs_batch(conn, numbers)
        if not refs:
            return "None of the specified references were found."

        entries: list[dict] = []
        not_found = set(numbers) - {r["rec_number"] for r in refs}
        for ref in refs:
            try:
                citation = format_citation(ref, style)
            except ValueError:
                citation = f"{ref.get('title', 'Unknown title')} (formatting error)"
            authors = ref.get("authors", [])
            first_author = authors[0] if authors else ""
            entries.append(
                {
                    "citation": citation,
                    "author_sort": first_author.lower(),
                    "year": ref.get("year", ""),
                    "rec_number": ref["rec_number"],
                }
            )

        if sort == "year":
            entries.sort(key=lambda e: (e["year"] or "0", e["author_sort"]))
        else:
            entries.sort(key=lambda e: (e["author_sort"], e["year"] or "0"))

        lines = [f"Bibliography ({len(entries)} references, {style.upper()}):\n"]
        for i, e in enumerate(entries, 1):
            lines.append(f"  {i}. {e['citation']}")
        if not_found:
            lines.append(f"\nNot found: {', '.join(str(n) for n in sorted(not_found))}")
        return "\n".join(lines)

    def search_semantic(self, query: str, limit: int = 20) -> str:
        from endnote_mcp import embeddings

        if not embeddings.is_available():
            return (
                "Semantic search is not available. Install the required dependencies:\n"
                "  pip install endnote-mcp[semantic]\n"
                "Then run: endnote-mcp embed"
            )

        with self._connect() as conn:
            if not embeddings.has_embeddings(conn):
                return "No embeddings found. Generate them first:\n  endnote-mcp embed"
            results = _search_semantic(conn, query, limit=limit)
        if not results:
            return f"No semantic matches for: {query}"

        lines = [f"Found {len(results)} reference(s) by semantic similarity:\n"]
        for r in results:
            sim_pct = f"{r.get('similarity', 0):.0%}"
            kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
            lines.append(
                f"  [{r['rec_number']}] ({sim_pct}) {r['authors']} ({r['year']}). {r['title']}."
                + (f" *{r['journal']}*." if r.get("journal") else "")
                + _doi_link(r.get("doi", ""))
                + (f"  Keywords: {kw}" if kw else "")
            )
        return "\n".join(lines)

    def get_bibtex(self, rec_numbers: str) -> str:
        try:
            numbers = [int(x.strip()) for x in rec_numbers.split(",") if x.strip()]
        except ValueError:
            return "Invalid rec_numbers format. Use comma-separated integers (e.g. '12,45,78')."
        if not numbers:
            return "No record numbers provided."

        with self._connect() as conn:
            refs = _get_refs_batch(conn, numbers)
        if not refs:
            return "None of the specified references were found."

        entries = [format_bibtex(ref) for ref in refs]
        not_found = set(numbers) - {r["rec_number"] for r in refs}
        result = "\n\n".join(entries)
        if not_found:
            result += f"\n\n% Not found: {', '.join(str(n) for n in sorted(not_found))}"
        return result

    def rebuild_index(self) -> str:
        result = subprocess.run(
            [sys.executable, "-m", "endnote_mcp.cli", "index"],
            capture_output=True,
            text=True,
            timeout=7200,
        )
        output = result.stdout
        if result.returncode != 0:
            err = result.stderr.strip() or output.strip() or "Unknown error"
            return f"Re-index failed: {err}"
        return output.strip() or "Re-index complete."
