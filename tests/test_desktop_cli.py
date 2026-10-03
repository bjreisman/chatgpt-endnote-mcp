"""Local setup is separate from Claude, and management commands never start HTTP."""
from pathlib import Path

import yaml
from click.testing import CliRunner

from endnote_mcp.config import Config
from endnote_mcp.desktop_cli import cli


def fixture_paths(tmp_path):
    xml = tmp_path / "export.xml"
    xml.write_text('<xml><records><record><rec-number>1</rec-number><titles><title>Alternative oxidase</title></titles></record></records></xml>')
    pdfs = tmp_path / "PDF"
    pdfs.mkdir()
    return xml, pdfs


def test_setup_import_is_separate_and_never_configures_claude(tmp_path, monkeypatch):
    xml, pdfs = fixture_paths(tmp_path)
    source = tmp_path / "claude.yaml"
    source.write_text(yaml.safe_dump({"endnote_xml": str(xml), "pdf_dir": str(pdfs), "db_path": str(tmp_path / "claude.db")}))
    original = source.read_bytes()
    destination = tmp_path / "new" / "config.yaml"
    runner = CliRunner()
    result = runner.invoke(cli, ["setup", "--import-config", str(source), "--config", str(destination)])
    assert result.exit_code == 0, result.output
    cfg = Config.load(destination)
    assert cfg.db_path == destination.parent / "library.db"
    assert not cfg.db_path.exists()
    assert source.read_bytes() == original
    assert not (tmp_path / "claude.db").exists()
    assert runner.invoke(cli, ["setup", "--xml", str(xml), "--pdf-dir", str(pdfs), "--config", str(destination)]).exit_code != 0


def test_config_precedence_does_not_use_legacy_environment(tmp_path, monkeypatch):
    xml, pdfs = fixture_paths(tmp_path)
    explicit = tmp_path / "explicit.yaml"
    env = tmp_path / "env.yaml"
    for p in (explicit, env):
        p.write_text(yaml.safe_dump({"endnote_xml": str(xml), "pdf_dir": str(pdfs), "db_path": str(p.with_suffix('.db'))}))
    monkeypatch.setenv("ENDNOTE_MCP_CONFIG", str(tmp_path / "nonexistent-claude.yaml"))
    monkeypatch.setenv("CHATGPT_ENDNOTE_MCP_CONFIG", str(env))
    assert Config.load().db_path == env.with_suffix(".db")
    assert Config.load(explicit).db_path == explicit.with_suffix(".db")


def test_setup_index_doctor_local_workflow(tmp_path):
    xml, pdfs = fixture_paths(tmp_path)
    cfg = tmp_path / "new" / "config.yaml"
    runner = CliRunner()
    result = runner.invoke(cli, ["setup", "--xml", str(xml), "--pdf-dir", str(pdfs), "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert runner.invoke(cli, ["doctor", "--config", str(cfg)]).exit_code != 0
    result = runner.invoke(cli, ["index", "--config", str(cfg), "--skip-pdfs"])
    assert result.exit_code == 0, result.output
    before = (cfg.parent / "library.db").read_bytes()
    result = runner.invoke(cli, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert '"ready": true' in result.output
    assert "codex mcp add endnote" in result.output
    result = runner.invoke(cli, ["status", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert (cfg.parent / "library.db").read_bytes() == before


def test_desktop_cli_excludes_experimental_services():
    assert set(cli.commands) == {"setup", "index", "embed", "status", "doctor", "serve-desktop"}


def test_embedding_failure_preserves_index_and_success_promotes(tmp_path, monkeypatch):
    import pytest
    from endnote_mcp import embeddings, db
    from endnote_mcp.desktop_cli import _embed
    xml, pdfs = fixture_paths(tmp_path)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({"endnote_xml": str(xml), "pdf_dir": str(pdfs)}))
    assert CliRunner().invoke(cli, ["index", "--config", str(cfg_path)]).exit_code == 0
    database = tmp_path / "library.db"
    before = database.read_bytes()
    monkeypatch.setattr(embeddings, "is_available", lambda: True)
    monkeypatch.setattr(embeddings, "load_model", lambda **kw: object())
    def fail(*args):
        raise RuntimeError("Interrupted embedding")
    monkeypatch.setattr(embeddings, "encode_batch", fail)
    with pytest.raises(RuntimeError, match="Interrupted"):
        _embed(cfg_path)
    assert database.read_bytes() == before
    assert not list(tmp_path.glob(".embedding-stage-*"))
    monkeypatch.setattr(embeddings, "encode_batch", lambda model, texts: [b"vector" for _ in texts])
    _embed(cfg_path)
    conn = db.connect_readonly(database)
    try:
        assert conn.execute("SELECT COUNT(*) FROM reference_embeddings").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        conn.close()
    assert not Path(str(database) + "-wal").exists()
