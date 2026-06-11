"""PLAN フェーズの構造化成果物 (plan JSON) のヘルパ (U3 #81).

エージェント出力から ```json ブロックを抽出し、plan_depth に応じた
構造化レコード (Web UI の design.json の前身) を構築する。
レコードは plan_depth に関わらず必ず生成され、ui_impact キーを常に含む
(#91 のエビデンス生成要否の判定ソース)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

PLAN_SCHEMA_VERSION = 1

# 閉じ ``` 直前の改行は省略され得る (LLM 出力ゆらぎ) ため任意にする。
# フェンス言語ラベルの大文字小文字 (```JSON 等) も許容する
_JSON_BLOCK_PATTERN = re.compile(r"```json\s*\n(.*?)\n?```", re.DOTALL | re.IGNORECASE)


def extract_plan_json(output: str) -> tuple[str, dict[str, Any] | None]:
    """エージェント出力から最後の ```json ブロックを抽出する。

    複数ブロックがある場合は最後のもの (成果物サマリ) を採用する。
    パースに成功した場合はそのブロックを除去したテキストと dict を返し、
    失敗した場合は元のテキストと None を返す。

    Args:
        output: エージェントの出力テキスト。

    Returns:
        (JSON ブロック除去後テキスト, パース結果 dict または None)。
    """
    matches = list(_JSON_BLOCK_PATTERN.finditer(output))
    if not matches:
        return output, None
    last = matches[-1]
    try:
        parsed = json.loads(last.group(1))
    except (json.JSONDecodeError, ValueError, RecursionError):
        # 深いネスト (RecursionError) や不正な JSON でも graceful に
        # plan_json=None へフォールバックし、フェーズの SUSPEND を避ける
        logger.warning("plan JSON block found but failed to parse")
        return output, None
    if not isinstance(parsed, dict):
        logger.warning("plan JSON block is not an object, ignoring")
        return output, None
    stripped = (output[: last.start()] + output[last.end() :]).strip()
    return stripped, parsed


def build_plan_record(plan_depth: str, parsed: dict[str, Any] | None) -> dict[str, Any]:
    """plan_depth に応じた構造化レコードを構築する。

    parsed が None (エージェントが JSON を出力しなかった / パース失敗) でも
    最小スキーマのレコードを必ず返す。ui_impact は bool 以外なら None
    (不明) にフォールバックする。

    Args:
        plan_depth: "light" または "full"。
        parsed: extract_plan_json のパース結果。

    Returns:
        構造化 plan レコード。
    """
    src = parsed or {}
    ui_impact = src.get("ui_impact")
    if not isinstance(ui_impact, bool):
        if ui_impact is not None:
            logger.warning("plan JSON ui_impact has invalid type %s, falling back to None", type(ui_impact).__name__)
        ui_impact = None

    record: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_depth": plan_depth,
        "ui_impact": ui_impact,
        "summary": _coerce_text(src.get("summary")),
        "test_cases": _coerce_test_cases(src.get("test_cases")),
    }
    if plan_depth == "full":
        raw_subtasks = src.get("subtasks")
        record["architecture"] = _coerce_text(src.get("architecture"))
        # 消費側が {id, title} を期待するため要素を正規化する (test_cases と同方針)
        record["subtasks"] = [_normalize_subtask(s) for s in raw_subtasks] if isinstance(raw_subtasks, list) else []
    return record


def _coerce_text(value: object) -> str:
    """表示用テキストフィールドを安全な文字列に正規化する。

    LLM が dict/list を返した場合に Python repr が混入するのを防ぎ、
    非文字列は空文字へフォールバックする。

    Args:
        value: 元の値。

    Returns:
        文字列。非文字列なら空文字。
    """
    return value if isinstance(value, str) else ""


def _coerce_test_cases(value: object) -> list[str]:
    """test_cases を list[str] に正規化する。

    LLM が文字列 1 件を返した場合は 1 要素リストに救済し、list の
    各要素は文字列化する。それ以外の型は空リストにフォールバックする。

    Args:
        value: 元の値。

    Returns:
        文字列のリスト。
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(t) for t in value]
    return []


def _normalize_subtask(item: object) -> dict[str, Any]:
    """subtasks の 1 要素を {id, title} スキーマに正規化する。

    LLM が文字列や想定外の型を返しても安全な dict にそろえる。

    Args:
        item: subtasks 配列の 1 要素。

    Returns:
        {"id": int | None, "title": str} 形式の dict。
    """
    if not isinstance(item, dict):
        return {"id": None, "title": str(item)}
    raw_id = item.get("id")
    return {
        "id": raw_id if isinstance(raw_id, int) else None,
        "title": str(item.get("title", "")),
    }


def plan_json_prompt_section(plan_depth: str) -> str:
    """プロンプトに付加する JSON ブロック出力指示を返す。

    Args:
        plan_depth: "light" または "full"。

    Returns:
        プロンプト末尾に付加する指示文。
    """
    if plan_depth == "full":
        schema = (
            "{\n"
            '  "ui_impact": true または false (UI に影響するか),\n'
            '  "summary": "設計の要約 (1〜3文)",\n'
            '  "architecture": "アーキテクチャ説明の要約",\n'
            '  "test_cases": ["主要テストケースの説明", ...],\n'
            '  "subtasks": [{"id": 1, "title": "サブタスク名"}, ...]\n'
            "}"
        )
    else:
        schema = (
            "{\n"
            '  "ui_impact": true または false (UI に影響するか),\n'
            '  "summary": "修正方針の要約 (1〜3文)",\n'
            '  "test_cases": ["主要テストケースの説明", ...]\n'
            "}"
        )
    return (
        "\n\n## 構造化サマリ (必須)\n"
        "出力の最後に、以下のスキーマの JSON を ```json コードブロックで"
        "1つだけ出力してください。\n\n"
        "```json\n" + schema + "\n```\n"
    )
