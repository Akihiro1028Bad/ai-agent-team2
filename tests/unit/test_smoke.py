"""スモークテスト: パッケージのインポートが成功することを確認."""


def test_import_package() -> None:
    """メインパッケージがインポートできること."""
    import ai_agent_orchestrator

    assert ai_agent_orchestrator.__version__ == "0.1.0"


def test_import_models() -> None:
    """models モジュールがインポートできること."""
    from ai_agent_orchestrator import models  # noqa: F401


def test_import_protocols() -> None:
    """protocols モジュールがインポートできること."""
    from ai_agent_orchestrator import protocols  # noqa: F401
