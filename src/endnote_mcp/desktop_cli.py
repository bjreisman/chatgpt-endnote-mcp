"""Local-only entry point; never starts an HTTP service or configures Claude."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import click
import yaml

from endnote_mcp.config import Config, get_default_config_path
from endnote_mcp.locking import publish_database


def shell_command(arguments):
    """Render copyable commands for the user's native shell."""
    if os.name == 'nt':
        def quote(value):
            value = str(value)
            if value and all(c.isalnum() or c in '-_.' for c in value):
                return value
            return "'" + value.replace("'", "''") + "'"
        prefix = '& ' if any(c in str(arguments[0]) for c in ' \\/:') else ''
        return prefix + ' '.join(quote(a) for a in arguments)
    return shlex.join([str(a) for a in arguments])


def _config_path(value=None):
    return Path(value or os.environ.get("CHATGPT_ENDNOTE_MCP_CONFIG") or get_default_config_path()).expanduser().resolve()


@click.group()
@click.version_option(package_name="chatgpt-endnote-mcp")
def cli():
    """Search a local EndNote library from Codex desktop over stdio."""


@cli.command()
@click.option("--xml", "xml_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--pdf-dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--config", type=click.Path(path_type=Path))
@click.option("--import-config", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--force", is_flag=True, help="Replace this product's existing configuration.")
def setup(xml_path, pdf_dir, config, import_config, force):
    """Save local paths. Import copies paths only, never the old database."""
    target = _config_path(config)
    if import_config:
        if target == import_config.resolve():
            raise click.ClickException("Import source and destination must be different.")
        old = Config.load(import_config)
        xml_path = xml_path or old.endnote_xml
        pdf_dir = pdf_dir or old.pdf_dir
    if not xml_path:
        xml_path = Path(click.prompt("EndNote XML export", type=click.Path(exists=True, dir_okay=False)))
    if not pdf_dir:
        pdf_dir = Path(click.prompt("PDF attachment directory", type=click.Path(exists=True, file_okay=False)))
    if target.exists() and not force:
        raise click.ClickException("Configuration exists; use --force to replace it.")
    if not xml_path.is_file() or not pdf_dir.is_dir():
        raise click.ClickException("XML and PDF directory must exist.")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {"endnote_xml": str(xml_path.resolve()), "pdf_dir": str(pdf_dir.resolve()),
            "db_path": str(target.parent / "library.db"), "max_pdf_pages": 30}
    if import_config and Path(data["db_path"]).resolve() == old.db_path:
        raise click.ClickException("Choose a destination directory separate from the imported index.")
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    target.chmod(0o600)
    click.echo(f"Saved {target}\nNext: {shell_command(['chatgpt-endnote-mcp', 'index', '--config', str(target)])}")


@cli.command()
@click.option("--config", type=click.Path(exists=True, path_type=Path))
@click.option("--full", is_flag=True, help="Rebuild a replacement index from this export.")
@click.option("--skip-pdfs", is_flag=True)
@click.option("--sync-deletions", is_flag=True, help="Treat the XML as a full-library export and remove absent records.")
@click.option("--embed", "with_embeddings", is_flag=True, help="Explicitly prepare local semantic embeddings after indexing.")
def index(config, full, skip_pdfs, sync_deletions, with_embeddings):
    """Stage and atomically replace the derived index. Source files are read-only."""
    from endnote_mcp.indexing import index_library
    path = _config_path(config)
    cfg = Config.load(path)
    click.echo("Indexing local XML and attachments; this may take several minutes.")
    result = index_library(cfg, full=full, skip_pdfs=skip_pdfs, sync_deletions=sync_deletions,
                           progress=lambda n: click.echo(f"Processed {n} references..."))
    click.echo(json.dumps(result, indent=2))
    if with_embeddings:
        _embed(path, full=False)


def _embed(config, full=False):
    from endnote_mcp import embeddings
    from endnote_mcp.db import connect_readonly, connect, upsert_embedding
    from endnote_mcp.indexing import management_lock
    cfg = Config.load(config)
    with closing(connect_readonly(cfg.db_path)):
        pass
    if not embeddings.is_available():
        raise click.ClickException("Install chatgpt-endnote-mcp[semantic] to enable embeddings.")
    click.echo(f"Preparing {embeddings.MODEL_NAME}; a model download may be needed.")
    model = embeddings.load_model(local_files_only=False)
    # Both management commands publish complete DELETE-journal databases, so
    # serving never creates target WAL/SHM files and can survive atomic swaps.
    with management_lock(cfg.db_path):
        fd, name = tempfile.mkstemp(prefix=".embedding-stage-", suffix=".db", dir=cfg.db_path.parent)
        os.close(fd)
        stage = Path(name)
        conn = None
        try:
            with closing(connect_readonly(cfg.db_path)) as source, closing(sqlite3.connect(stage)) as destination:
                source.backup(destination)
            conn = connect(stage)
            rows = conn.execute("SELECT * FROM references_").fetchall()
            existing = {r[0] for r in conn.execute("SELECT rec_number FROM reference_embeddings WHERE model_name=?", (embeddings.MODEL_NAME,))}
            rows = [dict(r) for r in rows if full or r["rec_number"] not in existing]
            if full:
                conn.execute("DELETE FROM reference_embeddings")
            for start in range(0, len(rows), 64):
                batch = rows[start:start + 64]
                vectors = embeddings.encode_batch(model, [embeddings.build_search_text(r) for r in batch])
                for ref, vector in zip(batch, vectors):
                    upsert_embedding(conn, ref["rec_number"], vector, embeddings.MODEL_NAME)
                conn.commit()
                click.echo(f"Embedded {min(start + 64, len(rows))}/{len(rows)} references...")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.close()
            conn = None
            publish_database(stage, cfg.db_path)
            click.echo(f"Embedded {len(rows)} references.")
        finally:
            if conn is not None:
                conn.close()
            for suffix in ("", "-wal", "-shm", "-journal"):
                Path(str(stage) + suffix).unlink(missing_ok=True)


@cli.command()
@click.option("--config", type=click.Path(exists=True, path_type=Path))
@click.option("--full", is_flag=True)
def embed(config, full):
    """Explicitly prepare/download the local model and generate embeddings."""
    _embed(_config_path(config), full)


@cli.command()
@click.option("--config", type=click.Path(exists=True, path_type=Path))
def status(config):
    """Read index counts without changing the database."""
    from endnote_mcp.db import connect_readonly, get_stats
    cfg = Config.load(_config_path(config))
    conn = connect_readonly(cfg.db_path)
    try:
        click.echo(json.dumps(get_stats(conn), indent=2))
    finally:
        conn.close()


@cli.command()
@click.option("--config", type=click.Path(exists=True, path_type=Path))
def doctor(config):
    """Check local readiness and print a registration command; no library scan."""
    from endnote_mcp.db import connect_readonly, get_stats
    from importlib.util import find_spec
    path = _config_path(config)
    cfg = Config.load(path)
    report = {"xml_exists": cfg.endnote_xml.is_file(), "pdf_directory_exists": cfg.pdf_dir.is_dir(),
              "transport": "stdio", "semantic_dependencies": find_spec("sentence_transformers") is not None}
    try:
        conn = connect_readonly(cfg.db_path)
        try:
            report["index"] = get_stats(conn)
        finally:
            conn.close()
    except Exception as exc:
        report["index_error"] = str(exc)
    executable = shutil.which("chatgpt-endnote-mcp")
    command = [str(Path(executable).absolute()), "serve-desktop"] if executable else [sys.executable, "-m", "endnote_mcp.desktop_cli", "serve-desktop"]
    command += ["--config", str(path)]
    report["registration_command"] = shell_command(["codex", "mcp", "add", "endnote", "--", *command])
    report["ready"] = report["xml_exists"] and report["pdf_directory_exists"] and "index_error" not in report
    click.echo(json.dumps(report, indent=2))
    if not report["ready"]:
        raise click.ClickException("Fix the reported paths/index, then run doctor again.")


@cli.command("serve-desktop")
@click.option("--config", type=click.Path(exists=True, path_type=Path))
def serve_desktop(config):
    """Start the read-only MCP server over process input/output. No sockets."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from endnote_mcp.desktop_server import main as serve
    serve(config_path=str(_config_path(config)))


def main():
    try:
        cli()
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
