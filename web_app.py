#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from appstore_build_upload import CLIENT_VERSION, VALID_PLATFORMS, create_token, list_apps, run_full_upload
from asc_logger import log_event, new_request_id, read_logs, reset_log_context, sanitize_form_params, set_log_context


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "4096")) * 1024 * 1024


@dataclass(frozen=True)
class Credentials:
    key_id: str
    issuer_id: str
    private_key_path: str


def require_form(name: str) -> str:
    value = request.form.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required field: {name}")
    return value


def require_file(name: str) -> FileStorage:
    uploaded = request.files.get(name)
    if uploaded is None or not uploaded.filename:
        raise ValueError(f"Missing required file: {name}")
    return uploaded


def save_upload(uploaded: FileStorage, directory: str, fallback_name: str) -> str:
    filename = secure_filename(uploaded.filename or fallback_name) or fallback_name
    path = os.path.join(directory, filename)
    uploaded.save(path)
    return path


def run_with_logging(endpoint: str, handler):
    request_id = new_request_id()
    token = set_log_context({"requestId": request_id, "source": "web"})
    started = time.time()
    params = sanitize_form_params(request.form.to_dict(), request.files.to_dict())
    log_event("web_request", endpoint=endpoint, method=request.method, params=params)

    try:
        result = handler(request_id)
        duration_ms = int((time.time() - started) * 1000)
        if isinstance(result, tuple):
            body, status = result
        else:
            body, status = result, 200
        if isinstance(body, dict):
            body.setdefault("requestId", request_id)
            body.setdefault("clientVersion", CLIENT_VERSION)
        log_event(
            "web_response",
            endpoint=endpoint,
            statusCode=status,
            durationMs=duration_ms,
            ok=body.get("ok", True) if isinstance(body, dict) else True,
            result=body if status < 400 else None,
            error=body.get("error") if isinstance(body, dict) and status >= 400 else None,
        )
        return jsonify(body), status
    except Exception as exc:
        duration_ms = int((time.time() - started) * 1000)
        error_body = {
            "ok": False,
            "requestId": request_id,
            "clientVersion": CLIENT_VERSION,
            "error": str(exc),
        }
        log_event(
            "web_response",
            endpoint=endpoint,
            statusCode=400,
            durationMs=duration_ms,
            ok=False,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        return jsonify(error_body), 400
    finally:
        reset_log_context(token)


@app.get("/api/version")
def api_version():
    return jsonify({"clientVersion": CLIENT_VERSION})


@app.get("/api/logs")
def api_logs():
    try:
        limit = min(int(request.args.get("limit", "100")), 500)
    except ValueError:
        limit = 100
    day = request.args.get("day")
    return jsonify(
        {
            "clientVersion": CLIENT_VERSION,
            "day": day,
            "count": limit,
            "logs": read_logs(limit=limit, day=day),
        }
    )


@app.get("/")
def index():
    return render_template("index.html", platforms=sorted(VALID_PLATFORMS))


@app.post("/api/apps")
def api_apps():
    def handler(request_id: str):
        with tempfile.TemporaryDirectory(prefix="asc-key-") as temp_dir:
            key_path = save_upload(require_file("privateKey"), temp_dir, "AuthKey.p8")
            credentials = Credentials(
                key_id=require_form("keyId"),
                issuer_id=require_form("issuerId"),
                private_key_path=key_path,
            )
            token = create_token(credentials.key_id, credentials.issuer_id, credentials.private_key_path)
            result = list_apps(token)
            if isinstance(result, dict):
                result["requestId"] = request_id
                result["clientVersion"] = CLIENT_VERSION
            return result

    return run_with_logging("/api/apps", handler)


@app.post("/api/upload")
def api_upload():
    def handler(request_id: str):
        platform = require_form("platform").upper()
        if platform not in VALID_PLATFORMS:
            raise ValueError(f"Invalid platform: {platform}")

        with tempfile.TemporaryDirectory(prefix="asc-upload-") as temp_dir:
            key_path = save_upload(require_file("privateKey"), temp_dir, "AuthKey.p8")
            ipa_path = save_upload(require_file("ipa"), temp_dir, "app.ipa")
            if Path(ipa_path).suffix.lower() != ".ipa":
                raise ValueError("The uploaded build file must be an .ipa file.")

            ipa_size = os.path.getsize(ipa_path)
            log_event("upload_files_saved", ipaPath=ipa_path, ipaSize=ipa_size, keyPath=key_path)

            result = run_full_upload(
                key_id=require_form("keyId"),
                issuer_id=require_form("issuerId"),
                private_key_path=key_path,
                app_id=require_form("appId"),
                version=require_form("version"),
                build=require_form("build"),
                platform=platform,
                ipa_path=ipa_path,
            )
            result["requestId"] = request_id
            return result

    return run_with_logging("/api/upload", handler)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
