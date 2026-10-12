from __future__ import annotations

import json
import os
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOG_DIR = Path(os.environ.get("ASC_LOG_DIR", "logs"))
_log_context: ContextVar[dict[str, Any] | None] = ContextVar("asc_log_context", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_log_context(context: dict[str, Any] | None) -> Any:
    return _log_context.set(context)


def reset_log_context(token: Any) -> None:
    _log_context.reset(token)


def get_log_context() -> dict[str, Any] | None:
    return _log_context.get()


def _log_file_path(day: str | None = None) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return LOG_DIR / f"asc-{day}.jsonl"


def write_log(record: dict[str, Any]) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **record,
    }
    path = _log_file_path()
    with path.open("a", encoding="utf-8") as file_obj:
        file_obj.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def log_event(event: str, **fields: Any) -> None:
    context = get_log_context() or {}
    write_log(
        {
            "requestId": context.get("requestId"),
            "source": context.get("source"),
            "event": event,
            **fields,
        }
    )


def read_logs(*, limit: int = 100, day: str | None = None) -> list[dict[str, Any]]:
    path = _log_file_path(day)
    if not path.is_file():
        return []

    lines = path.read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"raw": line})
    return records


def sanitize_form_params(form: dict[str, Any], files: dict[str, Any] | None = None) -> dict[str, Any]:
    safe = {
        "issuerId": form.get("issuerId"),
        "keyId": form.get("keyId"),
        "appId": form.get("appId"),
        "platform": form.get("platform"),
        "version": form.get("version"),
        "build": form.get("build"),
    }
    if files:
        for name, storage in files.items():
            if storage is None:
                continue
            filename = getattr(storage, "filename", None)
            if filename:
                safe[f"{name}FileName"] = filename
    return safe
