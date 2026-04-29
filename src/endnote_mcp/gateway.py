"""ChatGPT-facing MCP gateway that forwards to the local companion."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from endnote_mcp.bridge_client import make_bridge_client

mcp = FastMCP(
    "ChatGPT EndNote Gateway",
    instructions="Forward EndNote library tools to a paired local companion.",
)


def _invoke(tool_name: str, arguments: dict) -> str:
    client = make_bridge_client()
    return client.invoke(tool_name, arguments)


@mcp.tool()
def search_references(
    query: str,
    year_from: str | None = None,
    year_to: str | None = None,
    author: str | None = None,
    ref_type: str | None = None,
    limit: int = 50,
) -> str:
    """Search your EndNote library by title, author, keywords, or abstract."""
    return _invoke("search_references", locals())


@mcp.tool()
def search_fulltext(query: str, limit: int = 50) -> str:
    """Search inside the PDF content of your references."""
    return _invoke("search_fulltext", locals())


@mcp.tool()
def search_library(
    query: str,
    year_from: str | None = None,
    year_to: str | None = None,
    author: str | None = None,
    ref_type: str | None = None,
    limit: int = 30,
) -> str:
    """Search metadata, PDF content, and semantic similarity in one call."""
    return _invoke("search_library", locals())


@mcp.tool()
def get_reference_details(rec_number: int) -> str:
    """Get full metadata for a reference by its record number."""
    return _invoke("get_reference_details", locals())


@mcp.tool()
def get_citation(rec_number: int, style: str = "apa7") -> str:
    """Format a reference as a citation in a specific style."""
    return _invoke("get_citation", locals())


@mcp.tool()
def read_pdf_section(rec_number: int, start_page: int = 1, end_page: int = 5) -> str:
    """Read specific pages from a reference's PDF attachment."""
    return _invoke("read_pdf_section", locals())


@mcp.tool()
def list_references_by_topic(
    topic: str,
    year_from: str | None = None,
    year_to: str | None = None,
    ref_type: str | None = None,
    limit: int = 50,
) -> str:
    """List references matching a broad topic or theme."""
    return _invoke("list_references_by_topic", locals())


@mcp.tool()
def find_related(rec_number: int, limit: int = 10) -> str:
    """Find references related to a given reference."""
    return _invoke("find_related", locals())


@mcp.tool()
def get_bibliography(rec_numbers: str, style: str = "apa7", sort: str = "author") -> str:
    """Generate a formatted bibliography for multiple references."""
    return _invoke("get_bibliography", locals())


@mcp.tool()
def search_semantic(query: str, limit: int = 20) -> str:
    """Search your library by meaning, not just keywords."""
    return _invoke("search_semantic", locals())


@mcp.tool()
def get_bibtex(rec_numbers: str) -> str:
    """Export references as BibTeX entries for use in LaTeX."""
    return _invoke("get_bibtex", locals())


@mcp.tool()
def rebuild_index() -> str:
    """Re-index your EndNote library after adding new references."""
    return _invoke("rebuild_index", {})
