"""Shared request and response models for the bridge foundation."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field


@dataclass
class ToolInvokeRequest:
    """Serialized request sent from gateway to local companion."""

    tool_name: str
    arguments: dict = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> "ToolInvokeRequest":
        data = json.loads(raw)
        return cls(
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
            request_id=data.get("request_id") or str(uuid.uuid4()),
        )


@dataclass
class ToolInvokeResponse:
    """Serialized response returned from local companion to gateway."""

    ok: bool
    content: str = ""
    error_code: str | None = None
    error_message: str | None = None
    request_id: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> "ToolInvokeResponse":
        data = json.loads(raw)
        return cls(
            ok=bool(data["ok"]),
            content=data.get("content", ""),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            request_id=data.get("request_id"),
            metadata=data.get("metadata", {}) or {},
        )
