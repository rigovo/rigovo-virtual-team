"""Tests for database backend config loading."""

from __future__ import annotations

from rigovo.config import load_config


def test_load_config_uses_yaml_database_defaults(tmp_path):
    (tmp_path / "rigovo.yml").write_text(
        (
            "version: '1'\n"
            "database:\n"
            "  backend: postgres\n"
            "  local_path: .rigovo/custom.db\n"
        ),
        encoding="utf-8",
    )

    cfg = load_config(tmp_path)
    assert cfg.db_backend == "postgres"
    assert cfg.local_db_path == ".rigovo/custom.db"

