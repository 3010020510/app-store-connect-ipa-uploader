#!/usr/bin/env python3
"""
App Store Connect Build Upload API client.

Supports the full Linux/VPS upload chain:
  JWT -> GET /v1/apps -> POST /v1/buildUploads -> POST /v1/buildUploadFiles
  -> GET uploadOperations -> PUT IPA -> PATCH commit -> poll status -> GET builds

Examples:
  # Step 1-2: list apps
  python appstore_build_upload.py apps \\
    --key-id ABCDE12345 \\
    --issuer-id 00000000-0000-0000-0000-000000000000 \\
    --private-key ./AuthKey_ABCDE12345.p8

  # Step 3 only: create build upload (debug)
  python appstore_build_upload.py create-upload \\
    --key-id ABCDE12345 \\
    --issuer-id 00000000-0000-0000-0000-000000000000 \\
    --private-key ./AuthKey_ABCDE12345.p8 \\
    --app-id 1234567890 \\
    --version 1.2.3 \\
    --build 45

  # Full upload
  python appstore_build_upload.py upload \\
    --key-id ABCDE12345 \\
    --issuer-id 00000000-0000-0000-0000-000000000000 \\
    --private-key ./AuthKey_ABCDE12345.p8 \\
    --app-id 1234567890 \\
    --version 1.2.3 \\
    --build 45 \\
    --ipa ./demo.ipa
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from asc_logger import log_event
from ipa_metadata import read_ipa_metadata


API_BASE_URL = "https://api.appstoreconnect.apple.com"
JWT_AUDIENCE = "appstoreconnect-v1"
VALID_PLATFORMS = {"IOS", "MAC_OS", "TV_OS", "VISION_OS"}
CLIENT_VERSION = "2025-06-15-ipa-priority"

LogFn = Callable[[str, dict[str, Any] | None], None]


class AppStoreConnectError(RuntimeError):
    pass


class SizedFileSlice:
    def __init__(self, file_obj: BinaryIO, offset: int, length: int, chunk_size: int = 1024 * 1024) -> None:
        self.file_obj = file_obj
        self.offset = offset
        self.length = length
        self.chunk_size = chunk_size

    def __iter__(self) -> Iterator[bytes]:
        self.file_obj.seek(self.offset)
        remaining = self.length
        while remaining > 0:
            chunk = self.file_obj.read(min(self.chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk

    def __len__(self) -> int:
        return self.length


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def json_b64url(payload: dict[str, Any]) -> str:
    return b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def load_private_key(private_key_path: str):
    key_bytes = Path(private_key_path).read_bytes()
    key = serialization.load_pem_private_key(key_bytes, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("App Store Connect API private key must be an EC private key.")
    return key


def create_token(key_id: str, issuer_id: str, private_key_path: str, ttl_seconds: int = 20 * 60) -> str:
    now = int(time.time())
    header = {
        "alg": "ES256",
        "kid": key_id,
        "typ": "JWT",
    }
    payload = {
        "iss": issuer_id,
        "iat": now,
        "exp": now + ttl_seconds,
        "aud": JWT_AUDIENCE,
    }

    signing_input = f"{json_b64url(header)}.{json_b64url(payload)}".encode("ascii")
    private_key = load_private_key(private_key_path)
    der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing_input.decode('ascii')}.{b64url(raw_signature)}"


def apple_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def parse_json_response(response: requests.Response) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def extract_build_upload_state(attributes: dict[str, Any] | None) -> str | None:
    if not attributes:
        return None
    state = attributes.get("state")
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        inner = state.get("state")
        if isinstance(inner, str):
            return inner
    return None


def extract_build_upload_state_details(attributes: dict[str, Any] | None) -> dict[str, Any]:
    if not attributes:
        return {"state": None, "errors": [], "warnings": [], "infos": []}
    state = attributes.get("state")
    if isinstance(state, dict):
        return {
            "state": state.get("state"),
            "errors": state.get("errors") or [],
            "warnings": state.get("warnings") or [],
            "infos": state.get("infos") or [],
        }
    if isinstance(state, str):
        return {"state": state, "errors": [], "warnings": [], "infos": []}
    return {"state": None, "errors": [], "warnings": [], "infos": []}


def resolve_ipa_version_build(
    ipa_path: str,
    version: str,
    build: str,
    log: LogFn | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Prefer Version/Build from the main app Info.plist inside the IPA."""
    metadata = read_ipa_metadata(ipa_path)
    ipa_version = metadata.get("version")
    ipa_build = metadata.get("build")
    if not ipa_version or not ipa_build:
        raise ValueError(
            "Could not read CFBundleShortVersionString / CFBundleVersion from the IPA Info.plist."
        )

    requested = {"version": version, "build": build}
    from_ipa = {"version": ipa_version, "build": ipa_build}
    mismatch = from_ipa != requested
    detail = {
        "requested": requested,
        "fromIpa": from_ipa,
        "used": from_ipa,
        "bundleId": metadata.get("bundleId"),
        "bundleName": metadata.get("bundleName"),
        "infoPlistPath": metadata.get("infoPlistPath"),
        "autoCorrected": mismatch,
    }
    if mismatch:
        message = (
            f"Form version/build ({version}/{build}) differ from IPA; "
            f"using IPA values version={ipa_version!r}, build={ipa_build!r}."
        )
        if log is not None:
            log(message, detail)
        log_event("ipa_metadata_mismatch", **detail)
    else:
        if log is not None:
            log("Form version/build match IPA Info.plist", detail)
        log_event("ipa_metadata_ok", **detail)

    return ipa_version, ipa_build, detail


def request_apple(
    method: str,
    path: str,
    token: str,
    *,
    expected: set[int],
    payload: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    started = time.time()
    log_event(
        "apple_request",
        method=method,
        path=path,
        requestBody=payload,
    )
    response = requests.request(
        method,
        f"{API_BASE_URL}{path}",
        headers=apple_headers(token),
        json=payload,
        timeout=timeout,
    )
    body = parse_json_response(response)
    duration_ms = int((time.time() - started) * 1000)
    log_event(
        "apple_response",
        method=method,
        path=path,
        statusCode=response.status_code,
        durationMs=duration_ms,
        responseBody=body,
    )
    if response.status_code not in expected:
        pretty = json.dumps(body, ensure_ascii=False, indent=2)
        raise AppStoreConnectError(f"{method} {path} failed with HTTP {response.status_code}:\n{pretty}")
    return body


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_upload_payload(app_id: str, version: str, build: str, platform: str) -> dict[str, Any]:
    platform = platform.upper()
    if platform not in VALID_PLATFORMS:
        allowed = ", ".join(sorted(VALID_PLATFORMS))
        raise ValueError(f"Invalid platform {platform!r}; allowed values: {allowed}")

    return {
        "data": {
            "type": "buildUploads",
            "attributes": {
                "cfBundleShortVersionString": version,
                "cfBundleVersion": build,
                "platform": platform,
            },
            "relationships": {
                "app": {
                    "data": {
                        "type": "apps",
                        "id": app_id,
                    }
                }
            },
        }
    }


def list_apps(token: str, limit: int = 200) -> dict[str, Any]:
    return request_apple("GET", f"/v1/apps?limit={limit}", token, expected={200})


def create_build_upload(
    token: str,
    app_id: str,
    version: str,
    build: str,
    platform: str,
) -> dict[str, Any]:
    payload = build_upload_payload(app_id, version, build, platform)
    return request_apple("POST", "/v1/buildUploads", token, expected={201}, payload=payload)


def create_build_upload_file(token: str, build_upload_id: str, ipa_path: str) -> dict[str, Any]:
    file_name = os.path.basename(ipa_path)
    file_size = os.path.getsize(ipa_path)
    payload = {
        "data": {
            "type": "buildUploadFiles",
            "attributes": {
                "assetType": "ASSET",
                "fileName": file_name,
                "fileSize": file_size,
                "uti": "com.apple.ipa",
            },
            "relationships": {
                "buildUpload": {
                    "data": {
                        "type": "buildUploads",
                        "id": build_upload_id,
                    }
                }
            },
        }
    }
    return request_apple("POST", "/v1/buildUploadFiles", token, expected={201}, payload=payload)


def get_build_upload_file(token: str, build_upload_file_id: str) -> dict[str, Any]:
    return request_apple("GET", f"/v1/buildUploadFiles/{build_upload_file_id}", token, expected={200})


def get_upload_operations(file_response: dict[str, Any]) -> list[dict[str, Any]]:
    attributes = file_response.get("data", {}).get("attributes", {})
    operations = attributes.get("uploadOperations") or []
    if not operations:
        raise AppStoreConnectError("Apple did not return uploadOperations for this build upload file.")
    return sorted(operations, key=lambda item: (item.get("partNumber") or 0, item.get("offset") or 0))


def upload_ipa_to_operations(
    ipa_path: str,
    operations: list[dict[str, Any]],
    log: LogFn | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    file_size = os.path.getsize(ipa_path)
    with open(ipa_path, "rb") as file_obj:
        for index, operation in enumerate(operations, start=1):
            method = (operation.get("method") or "PUT").upper()
            url = operation.get("url")
            offset = int(operation.get("offset") or 0)
            length = int(operation.get("length") or file_size)
            if not url:
                raise AppStoreConnectError(f"Upload operation #{index} did not include a url.")
            if method != "PUT":
                raise AppStoreConnectError(f"Unsupported upload method {method!r}; expected PUT.")

            headers = {
                header.get("name"): header.get("value", "")
                for header in operation.get("requestHeaders", [])
                if header.get("name")
            }
            headers.setdefault("Content-Length", str(length))

            if log is not None:
                log(
                    f"PUT IPA part {index}/{len(operations)}",
                    {"offset": offset, "length": length, "urlHost": requests.utils.urlparse(url).netloc},
                )
            log_event(
                "apple_put_ipa",
                part=index,
                totalParts=len(operations),
                offset=offset,
                length=length,
                urlHost=requests.utils.urlparse(url).netloc,
            )
            started = time.time()
            response = requests.put(
                url,
                headers=headers,
                data=SizedFileSlice(file_obj, offset, length),
                timeout=None,
            )
            duration_ms = int((time.time() - started) * 1000)
            log_event(
                "apple_put_ipa_response",
                part=index,
                statusCode=response.status_code,
                durationMs=duration_ms,
                etag=response.headers.get("ETag"),
            )
            if response.status_code not in {200, 201, 202, 204}:
                raise AppStoreConnectError(
                    f"PUT upload part #{index} failed with HTTP {response.status_code}: {response.text[:2000]}"
                )
            results.append(
                {
                    "partNumber": operation.get("partNumber"),
                    "offset": offset,
                    "length": length,
                    "statusCode": response.status_code,
                    "etag": response.headers.get("ETag"),
                }
            )
    return results


def commit_build_upload_file(token: str, build_upload_file_id: str) -> dict[str, Any]:
    return commit_build_upload(token, build_upload_id="", build_upload_file_id=build_upload_file_id)


def commit_build_upload(
    token: str,
    *,
    build_upload_id: str,
    build_upload_file_id: str,
    log: LogFn | None = None,
) -> dict[str, Any]:
    # Never send sourceFileChecksums for build uploads — Apple rejects SHA_256 with 409.
    attempts: list[tuple[str, str, dict[str, Any]]] = [
        (
            "PATCH",
            f"/v1/buildUploadFiles/{build_upload_file_id}",
            {
                "data": {
                    "type": "buildUploadFiles",
                    "id": build_upload_file_id,
                    "attributes": {"uploaded": True},
                }
            },
        ),
    ]
    if build_upload_id:
        attempts.append(
            (
                "PATCH",
                f"/v1/buildUploads/{build_upload_id}",
                {
                    "data": {
                        "type": "buildUploads",
                        "id": build_upload_id,
                        "attributes": {"uploaded": True},
                    }
                },
            )
        )

    errors: list[str] = []
    for method, path, payload in attempts:
        if log is not None:
            log("Commit request prepared", {"method": method, "path": path, "payload": payload})
        log_event("apple_request", method=method, path=path, requestBody=payload)
        started = time.time()
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            headers=apple_headers(token),
            json=payload,
            timeout=120,
        )
        body = parse_json_response(response)
        duration_ms = int((time.time() - started) * 1000)
        log_event(
            "apple_response",
            method=method,
            path=path,
            statusCode=response.status_code,
            durationMs=duration_ms,
            responseBody=body,
        )
        if response.status_code in {200, 201}:
            if log is not None:
                log("Commit succeeded", {"method": method, "path": path, "statusCode": response.status_code})
            return body
        pretty = json.dumps(body, ensure_ascii=False, indent=2)
        errors.append(f"{method} {path} failed with HTTP {response.status_code}:\n{pretty}")

    raise AppStoreConnectError("\n\n".join(errors))


def get_build_upload(token: str, build_upload_id: str) -> dict[str, Any]:
    return request_apple("GET", f"/v1/buildUploads/{build_upload_id}", token, expected={200})


def list_builds(token: str, app_id: str, limit: int = 10) -> dict[str, Any]:
    return request_apple(
        "GET",
        f"/v1/apps/{app_id}/builds?limit={limit}",
        token,
        expected={200},
    )


def poll_build_upload(
    token: str,
    build_upload_id: str,
    *,
    timeout_seconds: int = 30 * 60,
    interval_seconds: int = 15,
    log: LogFn | None = None,
) -> dict[str, Any]:
    terminal_states = {"COMPLETE", "FAILED"}
    deadline = time.time() + timeout_seconds
    latest = get_build_upload(token, build_upload_id)

    while True:
        attributes = latest.get("data", {}).get("attributes", {})
        details = extract_build_upload_state_details(attributes)
        state = details["state"]
        if log is not None:
            log("Build Upload status polled", details)
        if state in terminal_states:
            if state == "FAILED":
                errors = details.get("errors") or []
                if errors:
                    formatted = json.dumps(errors, ensure_ascii=False, indent=2)
                    raise AppStoreConnectError(
                        f"Build upload failed during Apple processing:\n{formatted}"
                    )
                raise AppStoreConnectError("Build upload failed during Apple processing.")
            return latest
        if time.time() >= deadline:
            raise AppStoreConnectError(
                f"Timed out waiting for build upload {build_upload_id!r} to finish; last state={state!r}"
            )
        time.sleep(interval_seconds)
        latest = get_build_upload(token, build_upload_id)


def run_full_upload(
    *,
    key_id: str,
    issuer_id: str,
    private_key_path: str,
    app_id: str,
    version: str,
    build: str,
    platform: str,
    ipa_path: str,
    poll: bool = True,
    poll_timeout_seconds: int = 30 * 60,
    poll_interval_seconds: int = 15,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []

    def log(message: str, detail: dict[str, Any] | None = None) -> None:
        item = {"message": message}
        if detail is not None:
            item["detail"] = detail
        steps.append(item)

    token = create_token(key_id, issuer_id, private_key_path)
    ipa_size = os.path.getsize(ipa_path)
    ipa_sha256 = sha256_file(ipa_path)
    version, build, ipa_meta = resolve_ipa_version_build(ipa_path, version, build, log)
    log("JWT generated")
    log("IPA inspected", {
        "fileName": os.path.basename(ipa_path),
        "fileSize": ipa_size,
        "sha256": ipa_sha256,
        "ipaMetadata": ipa_meta,
    })

    build_upload = create_build_upload(token, app_id, version, build, platform)
    build_upload_id = build_upload["data"]["id"]
    log("Build Upload created", {"buildUploadId": build_upload_id})

    build_file = create_build_upload_file(token, build_upload_id, ipa_path)
    build_upload_file_id = build_file["data"]["id"]
    log("Build Upload File reservation created", {"buildUploadFileId": build_upload_file_id})

    if not build_file.get("data", {}).get("attributes", {}).get("uploadOperations"):
        build_file = get_build_upload_file(token, build_upload_file_id)
        log("Upload operations fetched")

    operations = get_upload_operations(build_file)
    log("Upload operations ready", {"count": len(operations)})

    put_results = upload_ipa_to_operations(ipa_path, operations, log)
    log("IPA bytes uploaded", {"parts": put_results})

    committed_file = commit_build_upload(
        token,
        build_upload_id=build_upload_id,
        build_upload_file_id=build_upload_file_id,
        log=log,
    )
    log("Build Upload committed")

    if poll:
        final_build_upload = poll_build_upload(
            token,
            build_upload_id,
            timeout_seconds=poll_timeout_seconds,
            interval_seconds=poll_interval_seconds,
            log=log,
        )
    else:
        final_build_upload = get_build_upload(token, build_upload_id)
        state = extract_build_upload_state(final_build_upload.get("data", {}).get("attributes"))
        log("Build Upload status fetched", {"state": state})

    builds: dict[str, Any] | None = None
    try:
        builds = list_builds(token, app_id)
        log("Recent builds fetched", {"count": len(builds.get("data", []))})
    except AppStoreConnectError as exc:
        log("Recent builds fetch skipped", {"error": str(exc)})

    return {
        "ok": True,
        "clientVersion": CLIENT_VERSION,
        "steps": steps,
        "ipaMetadata": ipa_meta,
        "ids": {
            "buildUploadId": build_upload_id,
            "buildUploadFileId": build_upload_file_id,
        },
        "sha256": ipa_sha256,
        "buildUpload": final_build_upload,
        "buildUploadFile": committed_file,
        "recentBuilds": builds,
    }


def post_build_upload(
    *,
    key_id: str,
    issuer_id: str,
    private_key_path: str,
    app_id: str,
    version: str,
    build: str,
    platform: str,
    timeout: int,
) -> dict[str, Any]:
    token = create_token(key_id, issuer_id, private_key_path)
    payload = build_upload_payload(app_id, version, build, platform)

    response = requests.post(
        f"{API_BASE_URL}/v1/buildUploads",
        headers=apple_headers(token),
        json=payload,
        timeout=timeout,
    )
    body = parse_json_response(response)
    if response.status_code != 201:
        pretty = json.dumps(body, ensure_ascii=False, indent=2)
        raise AppStoreConnectError(f"HTTP {response.status_code} from Apple:\n{pretty}")
    return body


def env_or_empty(name: str) -> str:
    return os.environ.get(name, "")


def add_credential_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--key-id", default=env_or_empty("ASC_KEY_ID"), help="API key ID.")
    parser.add_argument("--issuer-id", default=env_or_empty("ASC_ISSUER_ID"), help="Issuer ID.")
    parser.add_argument(
        "--private-key",
        default=env_or_empty("ASC_PRIVATE_KEY_PATH"),
        help="Path to AuthKey_XXXXXXXXXX.p8.",
    )
    parser.add_argument("--app-id", default=env_or_empty("ASC_APP_ID"), help="App Store Connect app ID.")


def require_credentials(args: argparse.Namespace, *, require_app_id: bool = False) -> None:
    missing = [
        name
        for name, value in {
            "--key-id or ASC_KEY_ID": args.key_id,
            "--issuer-id or ASC_ISSUER_ID": args.issuer_id,
            "--private-key or ASC_PRIVATE_KEY_PATH": args.private_key,
            **({"--app-id or ASC_APP_ID": args.app_id} if require_app_id else {}),
        }.items()
        if not value
    ]
    if missing:
        raise ValueError("Missing required value(s): " + ", ".join(missing))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="App Store Connect Build Upload API client.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    apps_parser = subparsers.add_parser("apps", help="List apps visible to the API key (GET /v1/apps).")
    add_credential_args(apps_parser)

    create_parser = subparsers.add_parser(
        "create-upload",
        help="Create a build upload only (POST /v1/buildUploads).",
    )
    add_credential_args(create_parser)
    create_parser.add_argument("--version", required=True, help="CFBundleShortVersionString, for example 1.2.3.")
    create_parser.add_argument("--build", required=True, help="CFBundleVersion, for example 45.")
    create_parser.add_argument(
        "--platform",
        default="IOS",
        choices=sorted(VALID_PLATFORMS),
        help="Apple platform. Default: IOS.",
    )
    create_parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds.")

    upload_parser = subparsers.add_parser("upload", help="Run the full IPA upload chain.")
    add_credential_args(upload_parser)
    upload_parser.add_argument("--version", required=True, help="CFBundleShortVersionString, for example 1.2.3.")
    upload_parser.add_argument("--build", required=True, help="CFBundleVersion, for example 45.")
    upload_parser.add_argument("--ipa", required=True, help="Path to the .ipa file.")
    upload_parser.add_argument(
        "--platform",
        default="IOS",
        choices=sorted(VALID_PLATFORMS),
        help="Apple platform. Default: IOS.",
    )
    upload_parser.add_argument("--no-poll", action="store_true", help="Skip polling build upload status after commit.")
    upload_parser.add_argument("--poll-timeout", type=int, default=30 * 60, help="Poll timeout in seconds.")
    upload_parser.add_argument("--poll-interval", type=int, default=15, help="Poll interval in seconds.")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "apps":
            require_credentials(args)
            token = create_token(args.key_id, args.issuer_id, args.private_key)
            result = list_apps(token)
        elif args.command == "create-upload":
            require_credentials(args, require_app_id=True)
            result = post_build_upload(
                key_id=args.key_id,
                issuer_id=args.issuer_id,
                private_key_path=args.private_key,
                app_id=args.app_id,
                version=args.version,
                build=args.build,
                platform=args.platform,
                timeout=args.timeout,
            )
        elif args.command == "upload":
            require_credentials(args, require_app_id=True)
            ipa_path = Path(args.ipa)
            if not ipa_path.is_file():
                raise ValueError(f"IPA file not found: {ipa_path}")
            if ipa_path.suffix.lower() != ".ipa":
                raise ValueError("The build file must use the .ipa extension.")
            result = run_full_upload(
                key_id=args.key_id,
                issuer_id=args.issuer_id,
                private_key_path=args.private_key,
                app_id=args.app_id,
                version=args.version,
                build=args.build,
                platform=args.platform,
                ipa_path=str(ipa_path),
                poll=not args.no_poll,
                poll_timeout_seconds=args.poll_timeout,
                poll_interval_seconds=args.poll_interval,
            )
        else:
            raise ValueError(f"Unknown command: {args.command}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
