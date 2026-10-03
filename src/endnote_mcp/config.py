"""Configuration loader for endnote-mcp."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path

import yaml


def get_config_dir() -> Path:
    """Return the platform-appropriate config directory."""
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "chatgpt-endnote-mcp"
    elif platform.system() == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "chatgpt-endnote-mcp"
    else:
        return Path.home() / ".config" / "chatgpt-endnote-mcp"


def get_default_config_path() -> Path:
    """Return the default config file path."""
    return get_config_dir() / "config.yaml"


@dataclass
class Config:
    endnote_xml: Path
    pdf_dir: Path
    db_path: Path
    max_pdf_pages: int = 30

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        """Load configuration from a YAML file.

        Resolution order:
        1. Explicit *path* argument
        2. CHATGPT_ENDNOTE_MCP_CONFIG environment variable
        3. Independent platform config directory (never the Claude configuration)
        """
        if path is None:
            path = os.environ.get("CHATGPT_ENDNOTE_MCP_CONFIG")

        if path is None:
            default = get_default_config_path()
            if default.exists():
                path = default
            else:
                raise FileNotFoundError(
                    f"No configuration found.\n"
                    f"Run 'chatgpt-endnote-mcp setup' to configure your library."
                )

        path = Path(path).expanduser().resolve()

        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}\n"
                "Run 'chatgpt-endnote-mcp setup' to configure your library."
            )

        with open(path) as f:
            raw = yaml.safe_load(f)

        if not isinstance(raw, dict) or not raw.get("endnote_xml") or not raw.get("pdf_dir"):
            raise ValueError("Configuration must contain endnote_xml and pdf_dir paths.")
        if int(raw.get("max_pdf_pages", 30)) < 1:
            raise ValueError("max_pdf_pages must be a positive integer (desktop reads are capped at 30).")

        endnote_xml = Path(raw["endnote_xml"]).expanduser().resolve()
        pdf_dir = Path(raw["pdf_dir"]).expanduser().resolve()

        db_path_raw = raw.get("db_path")
        if db_path_raw:
            db_path = Path(db_path_raw).expanduser().resolve()
        else:
            db_path = path.parent / "library.db"

        return cls(
            endnote_xml=endnote_xml,
            pdf_dir=pdf_dir,
            db_path=db_path,
            max_pdf_pages=int(raw.get("max_pdf_pages", 30)),
        )
