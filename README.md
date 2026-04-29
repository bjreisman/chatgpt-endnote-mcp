# ChatGPT EndNote MCP

[![Tests](https://github.com/bjreisman/chatgpt-endnote-mcp/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/bjreisman/chatgpt-endnote-mcp/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/endnote-mcp)](https://pypi.org/project/endnote-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/endnote-mcp)](https://pypi.org/project/endnote-mcp/)
[![License](https://img.shields.io/pypi/l/endnote-mcp)](https://github.com/bjreisman/chatgpt-endnote-mcp/blob/main/LICENSE)

<!-- mcp-name: io.github.bjreisman/chatgpt-endnote-mcp -->

Fork of `gokmengokhan/endnote-mcp` and an active attempt to port the project toward ChatGPT-compatible workflows. It preserves the existing EndNote indexing, PDF extraction, search, and citation core while this repo is adapted from a local Claude Desktop MCP into a ChatGPT-oriented remote app plus local bridge.

## Current Status

This fork is in a transitional state:

- The internal Python package name remains `endnote_mcp`
- The existing CLI and local stdio MCP server are preserved for compatibility
- The final ChatGPT target is a remote app/gateway paired with a local EndNote companion, not the inherited Claude Desktop install flow
- The newer bridge and local app pieces are experimental porting work, not hardened production services

## Security Note

This repository currently includes experimental local HTTP services and a local web app as part of the ChatGPT port attempt. They are intended for trusted local development. Do not expose them to the public internet as-is via tunnels or public hosts without adding authentication, tightening metadata exposure, and reviewing the privacy implications for your EndNote library and OpenAI API usage.

If you are looking for the original Claude Desktop experience, use the upstream project. This fork is the staging ground for the ChatGPT port.

## What It Does

Once the port is complete, you will be able to ask ChatGPT things like:

- *"Search my library for social capital and Bourdieu"*
- *"Find papers about how organisations deal with uncertainty"* (semantic search)
- *"Find references related to paper #3844"*
- *"Give me the APA citation for reference #1234"*
- *"Generate a bibliography for references 12, 45, 78, 102"*
- *"Export references 12, 45, 78 as BibTeX"*
- *"Read pages 5-7 from that Smith et al. paper"*

The long-term design keeps your EndNote library local while exposing approved search and reading actions to ChatGPT through a remote connector.

## How It Works

```
EndNote Library → XML Export → endnote-mcp index → SQLite Database (FTS5 + Embeddings)
                                                          ↕
                           Local companion ↔ remote app/gateway ↔ ChatGPT
```

Your references and PDF text are indexed into a local SQLite database with full-text search. Optionally, AI embeddings enable semantic search. The inherited local MCP server remains in the repo as a compatibility baseline, but it is not the final ChatGPT delivery model.

## Requirements

- **EndNote 20+** (any edition)
- **Python 3.10+**
- **uv** (recommended) or pip

## Migration Note

This repository has been renamed for the ChatGPT port, but the code still uses the original `endnote_mcp` package and `endnote-mcp` CLI internally for now. That is intentional in this first fork phase to avoid a large rename before the new bridge architecture is in place.

## Quick Start

The quick start below describes the inherited local workflow that still exists in the codebase today. It is useful for development and regression testing, but it is **transitional** and **not** the final ChatGPT setup flow.

### 1. Install

```bash
# With uv (recommended)
uv tool install endnote-mcp

# Or with pip
pip install endnote-mcp
```

### 2. Export your library from EndNote

In EndNote: **File → Export** → choose **XML** format → save to a convenient location (e.g., Desktop).

### 3. Run the setup wizard

```bash
endnote-mcp setup
```

The wizard will:
- Auto-detect your XML export and PDF directory
- Create the configuration
- Index your library
- Preserve the current local MCP baseline used during the port

### 4. Transitional local MCP usage

The current codebase still includes the inherited local MCP server and install flow from upstream. That path remains available only as a compatibility baseline while the ChatGPT remote app plus local bridge is being built.

## ChatGPT Port Direction

This fork is being adapted toward:

- A local companion that indexes and queries the EndNote library on your machine
- A remote MCP-compatible app/gateway that ChatGPT can connect to
- A pairing flow that avoids direct local MCP installation inside ChatGPT

## Bridge Foundation

This fork now includes a first-pass bridge foundation for development:

- `endnote-mcp serve-companion` starts a local HTTP companion that executes EndNote tool calls against your local library
- `endnote-mcp serve-gateway` starts an MCP gateway that forwards those same tool calls to the companion
- `endnote-mcp serve` is still preserved as the direct local MCP baseline from upstream

Typical development flow:

```bash
# Terminal 1
endnote-mcp serve-companion

# Terminal 2
endnote-mcp serve-gateway
```

The bridge foundation uses these config keys:

```yaml
companion_host: 127.0.0.1
companion_port: 8765
companion_token: null
request_timeout_seconds: 30
```

For local testing you can also override the gateway target with environment variables:

```bash
export ENDNOTE_MCP_COMPANION_URL=http://127.0.0.1:8765
export ENDNOTE_MCP_COMPANION_TOKEN=your-token-if-set
```

This is still a development foundation. It does not yet include a deployable remote ChatGPT app or public pairing flow.

## Use from ChatGPT with a Local Tunnel

If you want to try this fork from ChatGPT itself, the lowest-friction path is now a tunnel-backed local MCP server.

Important limitation: ChatGPT custom MCP connectors currently need a remote-reachable URL. ChatGPT cannot connect directly to a localhost MCP server, so this mode works by running the MCP server on your machine and then exposing it temporarily through a tunnel.

This mode is:

- personal dev/demo oriented
- read/fetch focused
- not hardened for broad public deployment
- the easiest way to try the MCP workflow in ChatGPT without building a durable hosted gateway first

### Recommended flow

1. Prepare your library locally:

```bash
endnote-mcp setup
endnote-mcp index
```

2. Set a bearer token for the local ChatGPT MCP server:

```bash
export ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN="choose-a-random-secret"
```

3. Start the tunnel-ready local MCP server:

```bash
endnote-mcp serve-chatgpt-local
```

By default it listens on `127.0.0.1:8787`.

4. Expose it with `localtunnel`:

```bash
npx localtunnel --port 8787
```

5. Copy the HTTPS URL from `localtunnel` into ChatGPT developer mode/custom connector setup.

6. Configure ChatGPT to send the bearer token you set above with requests to the connector.

### Optional tunnel alternative

If you want a more stable tunnel than `localtunnel`, `ngrok` is a reasonable alternative:

```bash
ngrok http 8787
```

### Notes

- From ChatGPT's perspective, this is still a remote MCP connection even though the server code runs locally on your machine.
- The tunnel makes your local MCP endpoint remotely reachable while it is running, so treat the token as required.
- Prefer setting `ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN` in your shell instead of storing `chatgpt_local_token` in `config.yaml`, because the config file is plain text on disk.
- The ChatGPT-local MCP server intentionally exposes only read/fetch-style EndNote tools and does not expose `rebuild_index`.

## Local ChatGPT Tunnel vs Local App

There are now two main ways to try this fork:

- `endnote-mcp serve-chatgpt-local` plus a tunnel: use the actual ChatGPT connector experience, but you need a remote-reachable tunnel URL and connector setup.
- `endnote-mcp serve-app`: use the local web app instead of ChatGPT's connector UI; simpler to run, but it uses the OpenAI API directly rather than ChatGPT's MCP connector workflow.

## Local Chat App

This fork also includes a local web app that uses the OpenAI API for the chat layer while keeping EndNote search and PDF access on your machine.

Before starting it, export your API key:

```bash
export OPENAI_API_KEY="your_api_key_here"
```

You can optionally choose a model. By default the app uses `gpt-5-mini`, which OpenAI documents as a faster, cost-efficient GPT-5 model for well-defined tasks:

```bash
export ENDNOTE_MCP_OPENAI_MODEL="gpt-5-mini"
```

Start the app:

```bash
endnote-mcp serve-app
```

For safety, `serve-app` now refuses non-loopback binds unless you pass `--allow-public`. Even with that flag, the app still has no built-in authentication, so avoid exposing it outside your machine unless you are intentionally doing short-lived testing.

Then open:

```text
http://127.0.0.1:8080
```

The local app can:

- ask natural-language questions about your EndNote library
- search references and indexed full text
- inspect specific reference metadata
- read PDF sections when needed for grounded answers
- generate citations and bibliographies during the conversation

## Semantic Search (Optional)

Enable meaning-based search that finds references even when they use different terminology than your query. For example, searching *"how companies prepare for uncertain futures"* finds papers on scenario planning and strategic foresight.

```bash
# Install semantic search dependencies
pip install endnote-mcp[semantic]

# Generate embeddings (~3 min for 4,000 references)
endnote-mcp embed
```

This uses the lightweight [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) model locally — no API keys needed, everything stays on your machine.

## Commands

| Command | What It Does |
|---------|-------------|
| `endnote-mcp setup` | Interactive setup wizard |
| `endnote-mcp index` | Re-index after adding new references (incremental) |
| `endnote-mcp index --full` | Full re-index from scratch |
| `endnote-mcp index --skip-pdfs` | Index metadata only (fast, ~1 sec) |
| `endnote-mcp index --embed` | Re-index and generate embeddings |
| `endnote-mcp embed` | Generate semantic search embeddings |
| `endnote-mcp embed --full` | Regenerate all embeddings from scratch |
| `endnote-mcp status` | Show index statistics |
| `endnote-mcp install` | Transitional inherited command for local Claude Desktop config |
| `endnote-mcp serve` | Transitional inherited local MCP server entrypoint |
| `endnote-mcp serve-chatgpt-local` | Start the local MCP HTTP server for ChatGPT tunnel testing |
| `endnote-mcp serve-companion` | Start the local HTTP companion for bridge development |
| `endnote-mcp serve-gateway` | Start the MCP gateway that forwards to the companion |
| `endnote-mcp serve-app` | Start the local web chat app backed by the OpenAI API |

## Tools Available in the Preserved Core

| Tool | Description |
|------|-------------|
| `search_references` | Search by author, title, year, keywords, abstract (BM25 ranked, with DOI links) |
| `search_fulltext` | Search inside PDF content — find concepts, quotes, methods |
| `search_library` | Combined metadata + PDF search in one call |
| `search_semantic` | Search by meaning using AI embeddings (requires `endnote-mcp[semantic]`) |
| `get_reference_details` | Full metadata for a reference (abstract, keywords, DOI, etc.) |
| `get_citation` | Format as APA 7th, Harvard, Vancouver, Chicago, or IEEE |
| `get_bibtex` | Export references as BibTeX entries for LaTeX |
| `get_bibliography` | Generate a formatted bibliography for multiple references |
| `find_related` | Find similar references (uses embeddings when available) |
| `read_pdf_section` | Read specific pages from a PDF attachment |
| `list_references_by_topic` | Broad topic-based listing |
| `rebuild_index` | Re-index after updating your EndNote library |

## Adding New References

When you add new references to your EndNote library:

1. **Re-export XML** from EndNote (overwrite the same file)
2. Either:
   - Run `endnote-mcp index` from a terminal, **or**
   - Use the local tooling during the transition period

Indexing is **incremental** — it only processes new references and PDFs, not the entire library again. If semantic search is installed, new references are automatically embedded.

## Performance

| Operation | Time (4,000 references) |
|-----------|------------------------|
| Metadata indexing | ~1 second |
| PDF extraction (first time) | ~1 min per 100 PDFs |
| PDF extraction (incremental) | Only new PDFs |
| Embedding generation | ~3 minutes |
| Keyword search | < 50 ms |
| Semantic search | < 200 ms |

## Configuration

Config is stored at:
- **macOS**: `~/Library/Application Support/endnote-mcp/config.yaml`
- **Windows**: `%APPDATA%/endnote-mcp/config.yaml`
- **Linux**: `~/.config/endnote-mcp/config.yaml`

```yaml
endnote_xml: /path/to/your/library.xml
pdf_dir: /path/to/your/Library.Data/PDF
db_path: /path/to/library.db    # auto-set by setup
max_pdf_pages: 30                # max pages per read request
companion_host: 127.0.0.1
companion_port: 8765
companion_token: null
chatgpt_local_host: 127.0.0.1
chatgpt_local_port: 8787
chatgpt_local_token: null
request_timeout_seconds: 30
```

`companion_token` and `chatgpt_local_token` may be left `null` in config and supplied via environment variables instead:

- `ENDNOTE_MCP_COMPANION_TOKEN`
- `ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN`

That is the safer default if you do not want long-lived secrets written to disk in plain text.

## Citation Styles

Five built-in styles:

- **APA 7th** — `get_citation(rec_number=42, style="apa7")`
- **Harvard** — `style="harvard"`
- **Vancouver** — `style="vancouver"`
- **Chicago** (Author-Date, 17th ed.) — `style="chicago"`
- **IEEE** — `style="ieee"`

Use `get_bibliography` to format multiple references at once, sorted by author or year.

## BibTeX Export

Export references as BibTeX entries for use in LaTeX:

- Ask Claude: *"Export references 42 and 100 as BibTeX"*
- Or use the `get_bibtex` tool directly with comma-separated record numbers

Generates complete entries with proper entry types (`@article`, `@book`, `@inproceedings`, etc.), cite keys, and all available fields.

## Troubleshooting

**"No configuration found"** — Run `endnote-mcp setup`

**"XML file not found"** — Re-export from EndNote: File → Export → XML format

**"PDF not found"** — Check that `pdf_dir` in your config points to the correct `.Data/PDF` directory

**Search returns no results** — Run `endnote-mcp index` to rebuild the database

**ChatGPT app support is not wired yet** — This fork is still implementing the remote app plus local bridge architecture

**Claude Desktop doesn't show the tool** — The inherited local install flow is transitional in this fork; use it only if you are testing the pre-port baseline

**"Semantic search is not available"** — Run `pip install endnote-mcp[semantic]` then `endnote-mcp embed`

## Citing This Software

If you use this tool in your research, please cite it:

> Gokmen, G. (2026). *EndNote MCP: Connecting EndNote Reference Libraries to Claude AI* (Version 1.4.5) [Computer software]. https://doi.org/10.5281/zenodo.18617546

For the original project history and citation context, see the upstream repository at [gokmengokhan/endnote-mcp](https://github.com/gokmengokhan/endnote-mcp).

Or use the "Cite this repository" button on GitHub for BibTeX/APA formats.

## License

AGPL-3.0 — free to use, modify, and distribute. See [LICENSE](LICENSE) for details.
