"""RepositoryConfig のエビデンス関連フィールド (#91) のテスト."""

from __future__ import annotations

from pathlib import Path

from ai_agent_orchestrator.config.settings import RepositoryConfig, load_config


def test_evidence_fields_defaults() -> None:
    """エビデンス関連フィールドの既定値。"""
    repo = RepositoryConfig(owner="o", repo="r")
    assert repo.dev_command is None
    assert repo.dev_url is None
    assert repo.dev_ready_timeout_sec == 60
    assert repo.dev_ready_log is None
    assert repo.test_command is None


def test_evidence_fields_from_yaml(tmp_path: Path) -> None:
    """YAML からエビデンス関連フィールドを読み込める。"""
    config = tmp_path / "config.yaml"
    config.write_text(
        "repositories:\n"
        "  - owner: o\n"
        "    repo: r\n"
        "    dev_command: npm run dev\n"
        "    dev_url: http://localhost:3000\n"
        "    dev_ready_timeout_sec: 30\n"
        "    dev_ready_log: Ready in\n"
        "    test_command: uv run pytest\n",
        encoding="utf-8",
    )
    settings = load_config(config)
    repo = settings.repositories[0]
    assert repo.dev_command == "npm run dev"
    assert repo.dev_url == "http://localhost:3000"
    assert repo.dev_ready_timeout_sec == 30
    assert repo.dev_ready_log == "Ready in"
    assert repo.test_command == "uv run pytest"
