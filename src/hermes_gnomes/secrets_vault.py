"""age-encrypted secrets vault.

Decrypts `secrets.age` to an in-memory dict via subprocess to the `age` binary.
Never writes plaintext to disk. Never logs the decrypted contents.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class SecretsVaultError(RuntimeError):
    """Raised when secrets cannot be decrypted or parsed."""


def load_secrets_from_age(*, age_file: Path, key_file: Path) -> dict[str, str]:
    """Decrypt an age-encrypted env file and parse KEY=VALUE lines.

    Lines starting with '#' are comments. Empty lines are ignored.
    Values with '=' in them are supported (only the first '=' is the separator).
    """
    if not age_file.exists():
        raise SecretsVaultError(f"age file not found: {age_file}")
    if not key_file.exists():
        raise SecretsVaultError(f"age key file not found: {key_file}")

    result = subprocess.run(
        ["age", "-d", "-i", str(key_file), str(age_file)],
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise SecretsVaultError(f"age decrypt failed: {stderr}")

    return _parse_env(result.stdout.decode("utf-8", errors="replace"))


def _parse_env(text: str) -> dict[str, str]:
    secrets: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        secrets[key.strip()] = value
    return secrets
