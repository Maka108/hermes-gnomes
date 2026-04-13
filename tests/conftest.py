"""Shared pytest fixtures."""
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a path for an ephemeral SQLite DB."""
    return tmp_path / "test.db"


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """Return a temporary config directory."""
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture
def tmp_memory_dir(tmp_path: Path) -> Path:
    """Return a temporary memory directory."""
    d = tmp_path / "memory"
    d.mkdir()
    return d
