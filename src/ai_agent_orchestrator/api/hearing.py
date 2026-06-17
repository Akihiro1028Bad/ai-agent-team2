"""ヒアリング (clarify) Q&A の構造化 (#139).

GitHub Issue コメント列から、エージェントの質問と人間の回答を Q&A スレッドへ
分類する純関数群。GitHub API 呼び出しは app 側で行い、本モジュールは取得済みの
コメント列とフェーズ文字列のみを受け取る (テスタブルに保つ)。
"""

from __future__ import annotations

from typing import Any, Literal

from ai_agent_orchestrator.api.schemas import HearingResponse, HearingTurnResponse
from ai_agent_orchestrator.phases.hearing import HEARING_QUESTION_MARKER

# マーカー導入前 (#139 以前) のヒアリング質問コメントを拾う後方互換キーワード
# (next_action_footer("hearing") のテキスト)。
_LEGACY_HEARING_HINT = "コメントで回答"


def _comment_body(comment: object) -> str:
    return str(getattr(comment, "body", "") or "")


def _comment_author(comment: object) -> str:
    user = getattr(comment, "user", None)
    return str(getattr(user, "login", "") or "") if user is not None else ""


def _is_bot(comment: object) -> bool:
    user = getattr(comment, "user", None)
    return getattr(user, "type", "") == "Bot" if user is not None else False


def _created_at(comment: object) -> str | None:
    raw = getattr(comment, "created_at", None)
    if raw is None:
        return None
    # githubkit は datetime を返す。文字列/その他はそのまま str 化。
    iso = getattr(raw, "isoformat", None)
    return iso() if callable(iso) else str(raw)


def _is_hearing_question(comment: object) -> bool:
    """コメントがヒアリングの質問かを判定する.

    マーカー一致を最優先。マーカー導入前の質問は Bot 投稿 + フッター文言で拾う。
    """
    body = _comment_body(comment)
    if HEARING_QUESTION_MARKER in body:
        return True
    return _is_bot(comment) and _LEGACY_HEARING_HINT in body


def _strip_markers(body: str) -> str:
    """表示用に内部マーカー/フッターを取り除く."""
    return body.replace(HEARING_QUESTION_MARKER, "").rstrip()


def build_hearing(comments: list[Any], phase: str) -> HearingResponse:
    """コメント列とフェーズから HearingResponse を構築する (#139).

    最初のヒアリング質問以降を対象に、Bot 質問→人間回答の往復をターン列にする
    (質問前の intake コメント等は除外)。state はフェーズから導出する。

    Args:
        comments: Issue コメント列 (時系列昇順, IssueComment 互換)。
        phase: 現在フェーズ文字列 (clarify / clarify-wait / plan ...)。

    Returns:
        HearingResponse。
    """
    first_q = next((i for i, c in enumerate(comments) if _is_hearing_question(c)), None)

    turns: list[HearingTurnResponse] = []
    rounds = 0
    if first_q is not None:
        for comment in comments[first_q:]:
            if _is_hearing_question(comment):
                rounds += 1
                turns.append(
                    HearingTurnResponse(
                        role="question",
                        author=_comment_author(comment),
                        body=_strip_markers(_comment_body(comment)),
                        created_at=_created_at(comment),
                    )
                )
            elif not _is_bot(comment):
                # 質問以降の人間コメント = 回答
                turns.append(
                    HearingTurnResponse(
                        role="answer",
                        author=_comment_author(comment),
                        body=_comment_body(comment),
                        created_at=_created_at(comment),
                    )
                )

    state = _derive_state(phase, has_turns=bool(turns))
    return HearingResponse(state=state, rounds=rounds, turns=turns)


def _derive_state(phase: str, *, has_turns: bool) -> Literal["waiting", "in_progress", "done", "none"]:
    """フェーズからヒアリング状態を導出する."""
    if phase == "clarify-wait":
        return "waiting"
    if phase == "clarify":
        return "in_progress"
    return "done" if has_turns else "none"
