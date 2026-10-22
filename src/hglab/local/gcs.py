"""Cloud Storage through a service account HMAC key: Signature V4 over the XML API, nothing on disk.

Organisations now block JSON keys for service accounts by default (``iam.disableServiceAccountKeyCreation``),
while HMAC keys for a service account stay available and are short enough for any OS keyring. This client
signs each request with ``GOOG4-HMAC-SHA256`` and offers the two calls the backups need, with the same
shape as the Google client library: ``bucket(name).blob(path).upload_from_filename(file)`` and
``list_blobs(bucket, prefix)``. The secret never leaves memory.
"""

from __future__ import annotations

import hashlib
import hmac
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

HOST = "storage.googleapis.com"
ALGORITHM = "GOOG4-HMAC-SHA256"
SCOPE_TAIL = "auto/storage/goog4_request"


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _quote(segment: str) -> str:
    return urllib.parse.quote(segment, safe="-_.~")


def sign(
    access_id: str,
    secret: str,
    method: str,
    bucket: str,
    object_name: str = "",
    query: dict[str, str] | None = None,
    payload: bytes = b"",
    when: datetime | None = None,
) -> tuple[str, dict[str, str]]:
    """The URL and the signed headers for one request (the pure part: testable without a network)."""
    when = when or datetime.now(UTC)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    date = stamp[:8]
    path = (
        "/"
        + _quote(bucket)
        + ("/" + "/".join(_quote(p) for p in object_name.split("/")) if object_name else "")
    )
    canonical_query = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted((query or {}).items()))
    payload_hash = hashlib.sha256(payload).hexdigest()
    headers = {"host": HOST, "x-goog-content-sha256": payload_hash, "x-goog-date": stamp}
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted(headers.items()))
    signed = ";".join(sorted(headers))
    canonical = (
        f"{method}\n{path}\n{canonical_query}\n{canonical_headers}\n{signed}\n{payload_hash}"
    )
    scope = f"{date}/{SCOPE_TAIL}"
    to_sign = "\n".join(
        [ALGORITHM, stamp, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()]
    )
    key = _hmac(
        _hmac(_hmac(_hmac(("GOOG4" + secret).encode("utf-8"), date), "auto"), "storage"),
        "goog4_request",
    )
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"{ALGORITHM} Credential={access_id}/{scope}, SignedHeaders={signed}, Signature={signature}"
    )
    url = f"https://{HOST}{path}" + (f"?{canonical_query}" if canonical_query else "")
    return url, headers


@dataclass
class Listed:
    name: str
    size: int | None
    updated: datetime | None


class HmacStorage:
    """The two calls the backups use, shaped like ``google.cloud.storage.Client``."""

    def __init__(self, access_id: str, secret: str, timeout: float = 120.0) -> None:
        self._access_id = access_id
        self._secret = secret
        self._timeout = timeout

    def bucket(self, name: str) -> _Bucket:
        return _Bucket(self, name)

    def list_blobs(self, bucket: str, prefix: str = "") -> list[Listed]:
        out: list[Listed] = []
        token: str | None = None
        while True:
            query = {"list-type": "2", "prefix": prefix}
            if token:
                query["continuation-token"] = token
            url, headers = sign(self._access_id, self._secret, "GET", bucket, "", query)
            response = httpx.get(url, headers=headers, timeout=self._timeout)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            ns = {"s": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
            prefix_ns = "s:" if ns else ""
            for item in root.findall(f"{prefix_ns}Contents", ns):
                key = item.findtext(f"{prefix_ns}Key", "", ns)
                size = item.findtext(f"{prefix_ns}Size", "", ns)
                modified = item.findtext(f"{prefix_ns}LastModified", "", ns)
                updated = datetime.fromisoformat(modified) if modified else None
                out.append(Listed(key, int(size) if size.isdigit() else None, updated))
            token = root.findtext(f"{prefix_ns}NextContinuationToken", "", ns) or None
            if not token:
                return out

    def _put(self, bucket: str, object_name: str, payload: bytes, content_type: str) -> None:
        url, headers = sign(
            self._access_id, self._secret, "PUT", bucket, object_name, None, payload
        )
        headers["content-type"] = content_type
        response = httpx.put(url, headers=headers, content=payload, timeout=self._timeout)
        response.raise_for_status()


class _Bucket:
    def __init__(self, client: HmacStorage, name: str) -> None:
        self._client = client
        self._name = name

    def blob(self, path: str) -> _Blob:
        return _Blob(self._client, self._name, path)


class _Blob:
    def __init__(self, client: HmacStorage, bucket: str, path: str) -> None:
        self._client, self._bucket, self.name = client, bucket, path

    def upload_from_filename(self, filename: str, content_type: str = "application/gzip") -> None:
        self._client._put(self._bucket, self.name, Path(filename).read_bytes(), content_type)


def client_from_keyring(get_secret: Any) -> HmacStorage | None:
    access_id, secret = get_secret("GCP_HMAC_ACCESS_ID"), get_secret("GCP_HMAC_SECRET")
    return HmacStorage(access_id, secret) if access_id and secret else None


__all__ = ["ALGORITHM", "HOST", "HmacStorage", "Listed", "client_from_keyring", "sign"]
