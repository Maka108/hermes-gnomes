from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_gnomes.secrets_vault import SecretsVaultError, load_secrets_from_age


def test_load_secrets_parses_env_output(tmp_path: Path) -> None:
    age_file = tmp_path / "secrets.age"
    age_file.write_bytes(b"fake encrypted bytes")
    key_file = tmp_path / "age.key"
    key_file.write_text("AGE-SECRET-KEY-FAKE")

    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = b"FOO=bar\nBAZ=qux\n# comment line\nEMPTY_LINE_BELOW=\n\nLAST=ok\n"
    completed.stderr = b""

    with patch("hermes_gnomes.secrets_vault.subprocess.run", return_value=completed) as run:
        secrets = load_secrets_from_age(age_file=age_file, key_file=key_file)

    assert secrets == {
        "FOO": "bar",
        "BAZ": "qux",
        "EMPTY_LINE_BELOW": "",
        "LAST": "ok",
    }
    run.assert_called_once()
    args = run.call_args[0][0]
    assert args[0] == "age"
    assert "-d" in args
    assert str(key_file) in args
    assert str(age_file) in args


def test_load_secrets_raises_on_age_failure(tmp_path: Path) -> None:
    age_file = tmp_path / "secrets.age"
    age_file.write_bytes(b"x")
    key_file = tmp_path / "age.key"
    key_file.write_text("x")

    completed = MagicMock()
    completed.returncode = 1
    completed.stdout = b""
    completed.stderr = b"age: error: bad key"

    with patch("hermes_gnomes.secrets_vault.subprocess.run", return_value=completed):
        with pytest.raises(SecretsVaultError) as exc_info:
            load_secrets_from_age(age_file=age_file, key_file=key_file)

    assert "bad key" in str(exc_info.value)


def test_load_secrets_raises_on_missing_age_file(tmp_path: Path) -> None:
    missing = tmp_path / "no_such.age"
    key = tmp_path / "age.key"
    key.write_text("x")

    with pytest.raises(SecretsVaultError, match="not found"):
        load_secrets_from_age(age_file=missing, key_file=key)


def test_load_secrets_raises_on_missing_key_file(tmp_path: Path) -> None:
    age_file = tmp_path / "secrets.age"
    age_file.write_bytes(b"x")
    missing = tmp_path / "no_such.key"

    with pytest.raises(SecretsVaultError, match="not found"):
        load_secrets_from_age(age_file=age_file, key_file=missing)
