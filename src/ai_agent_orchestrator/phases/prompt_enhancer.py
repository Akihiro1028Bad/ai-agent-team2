"""プロンプト強化モジュール.

各フェーズの build_prompt() に品質要件を一元的に追加する。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# フェーズ別に追加するセクション定義
# ---------------------------------------------------------------------------

_TEST_REQUIREMENTS = """\

## テスト要件
- テストカバレッジ 80% 以上を維持すること
- pytest + pytest-asyncio (auto mode) のパターンに従うこと
- テストファイルは tests/unit/ または tests/integration/ に配置
- Protocol の Fake 実装を使ったテストを優先
- 境界値テスト・異常系テストを必ず含めること
- `uv run pytest tests/unit/ -v --cov=ai_agent_orchestrator --cov-report=term-missing` で確認
"""

_SECURITY_REQUIREMENTS = """\

## セキュリティ要件
- ハードコードされたシークレット (API キー、パスワード、トークン) を含めないこと
- ユーザー入力は必ずバリデーションすること
- 外部入力を信頼せず、型チェック・サニタイズを行うこと
- 実装完了後に `uv run bandit -r src/` で静的セキュリティ分析を実行すること
"""

_CODING_STANDARDS = """\

## コーディング規約
- mypy strict モード準拠: 全関数に型アノテーション必須
- async/await を基本とし、ブロッキング呼び出し禁止
- typing.Protocol でインターフェースを定義
- 具体的な例外クラスを使用 (裸の `except:` 禁止)
- docstring: クラスと公開メソッドに必須 (Google style)
- snake_case (変数・関数)、PascalCase (クラス)、UPPER_CASE (定数)
- `uv run ruff check src/ tests/` および `uv run ruff format src/ tests/` を実行して確認
- `uv run mypy src/` で型チェックを通すこと
"""

_DESIGN_TEST_STRATEGY = """\

## 設計書に含めるべきテスト戦略
- ユニットテスト対象のモジュールとテスト方針
- Protocol の Fake 実装方針
- テストカバレッジ目標 (80% 以上)
"""

_DESIGN_SECURITY = """\

## 設計書に含めるべきセキュリティ考慮事項
- 外部入力のバリデーション方針
- 秘密情報の管理方法
- エラーメッセージで機密情報を露出しないこと
"""

_BROWSER_VERIFICATION = """\

## ブラウザ検証 (エビデンスが必要な場合のみ)
- UIの見た目を確認したい場合は Playwright でスクリーンショットを取得してください
- アクセシビリティ・パフォーマンスの検証が必要な場合は Chrome DevTools の Lighthouse を使用してください
- 毎回使う必要はありません。エビデンスが必要な場合のみ使用してください
- ブラウザ操作後は必ずブラウザを閉じてください
"""

# ---------------------------------------------------------------------------
# フェーズ別マッピング
# ---------------------------------------------------------------------------

_PHASE_SECTIONS: dict[str, list[str]] = {
    "implement": [_TEST_REQUIREMENTS, _SECURITY_REQUIREMENTS, _CODING_STANDARDS, _BROWSER_VERIFICATION],
    "fix": [_TEST_REQUIREMENTS, _SECURITY_REQUIREMENTS, _CODING_STANDARDS, _BROWSER_VERIFICATION],
    "ci-fix": [_CODING_STANDARDS],
    "impl-revise": [_TEST_REQUIREMENTS, _CODING_STANDARDS, _BROWSER_VERIFICATION],
    "design": [_DESIGN_TEST_STRATEGY, _DESIGN_SECURITY, _CODING_STANDARDS, _TEST_REQUIREMENTS],
    "design-revise": [_DESIGN_TEST_STRATEGY, _CODING_STANDARDS],
}

# 強化対象外のフェーズ (hearing, type-detection 等) はマッピングに含めない


def enhance_prompt(base_prompt: str, phase: str) -> str:
    """フェーズに応じた品質要件をプロンプトに追加する.

    Args:
        base_prompt: フェーズ固有の元プロンプト。
        phase: フェーズ名 (Phase enum の .value と一致)。

    Returns:
        品質要件セクションが追加されたプロンプト。
    """
    sections = _PHASE_SECTIONS.get(phase, [])
    if not sections:
        return base_prompt
    return base_prompt + "".join(sections)
