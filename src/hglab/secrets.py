"""Credential lookup without exposing secret values to logs or output."""

from __future__ import annotations

import os
import re
from pathlib import Path

import keyring
from dotenv import dotenv_values


def secret_name(agent: str) -> str:
    normalized = agent.upper().replace("-", "_")
    if not re.fullmatch(r"[A-Z0-9_]+", normalized):
        raise ValueError("agent name cannot be used as a secret name")
    return f"HG_KEY_{normalized}"


def get_api_key(agent: str, root: Path | None = None) -> str | None:
    """Look up env, then OS keyring, then the gitignored dotenv file."""
    name = secret_name(agent)
    if value := os.environ.get(name):
        return value
    try:
        if value := keyring.get_password("hglab", agent):
            return value
    except (keyring.errors.KeyringError, RuntimeError):
        pass
    path = (root or Path.cwd()) / ".env"
    if path.is_file():
        return dotenv_values(path).get(name) or None
    return None


def get_secret(name: str, root: Path | None = None) -> str | None:
    if not re.fullmatch(r"[A-Z0-9_]+", name):
        raise ValueError("secret name may contain only uppercase letters, digits, and underscores")
    if value := os.environ.get(name):
        return value
    try:
        if value := _read_chunked(name):
            return value
    except (keyring.errors.KeyringError, RuntimeError):
        pass
    path = (root or Path.cwd()) / ".env"
    if path.is_file():
        return dotenv_values(path).get(name) or None
    return None


CHUNK = 1000  # the Windows vault refuses blobs above about 2.5 KB; a service account key is about 2.3 KB


def _store_chunked(name: str, value: str) -> None:
    if len(value) <= CHUNK:
        keyring.set_password("hglab", name, value)
        return
    parts = [value[i : i + CHUNK] for i in range(0, len(value), CHUNK)]
    for i, part in enumerate(parts, 1):
        keyring.set_password("hglab", f"{name}__{i}", part)
    keyring.set_password("hglab", name, f"chunked:{len(parts)}")


def _read_chunked(name: str) -> str | None:
    value = keyring.get_password("hglab", name)
    if value and value.startswith("chunked:"):
        count = int(value.split(":", 1)[1])
        parts = [keyring.get_password("hglab", f"{name}__{i}") or "" for i in range(1, count + 1)]
        return "".join(parts) or None
    return value


def store_api_key(agent: str, value: str) -> None:
    if not value:
        raise ValueError("cannot store an empty API key")
    try:
        keyring.set_password("hglab", agent, value)
    except (keyring.errors.KeyringError, RuntimeError):
        store_secret(secret_name(agent), value)


def store_secret(name: str, value: str) -> None:
    if not value:
        raise ValueError("cannot store an empty secret")
    if not re.fullmatch(r"[A-Z0-9_]+", name):
        raise ValueError("secret name may contain only uppercase letters, digits, and underscores")
    try:
        _store_chunked(name, value)
    except (keyring.errors.KeyringError, RuntimeError):
        from dotenv import set_key

        path = Path.cwd() / ".env"
        set_key(str(path), name, value, quote_mode="always")
        path.chmod(0o600)


def set_github_secret(agent: str, value: str) -> None:
    """Pipe a credential to gh stdin; never place it in argv or print it."""
    import subprocess

    subprocess.run(
        ["gh", "secret", "set", secret_name(agent)],
        input=value,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )
