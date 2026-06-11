"""承認判定ロジックの共通化 (U4 #82 + 承認者検証 #102).

タイプ別 (Bug の 👍 / Feature-M の PR approve・LGTM) に分散していた承認・
差し戻しの判定を、純粋関数として 1 か所に集約する。あわせて承認者の
許可リスト検証 (#102) を提供し、許可外ユーザーの承認を無効化する。

GitHub の検知面 (Issue リアクション vs PR レビュー) はポーラー側に残すが、
「承認か差し戻しか」「その承認者が許可されているか」の判断は本モジュールに
一本化する。
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

_THUMBSUP = "+1"


class ApprovalDecision(StrEnum):
    """レビュー/コメントの承認判定結果."""

    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    NONE = "none"


def classify_pr_review(state: str, body: str, approve_comment: str) -> ApprovalDecision:
    """PR レビューの state と本文から承認/差し戻しを判定する。

    - APPROVED: 承認
    - COMMENTED かつ本文が approve_comment と完全一致 (大小無視): 承認 (LGTM)
    - CHANGES_REQUESTED: 差し戻し
    - COMMENTED かつ本文あり (LGTM 以外): 差し戻し (指摘)
    - 本文なしの COMMENTED など: NONE (情報なし)

    Args:
        state: PR レビュー state (APPROVED / CHANGES_REQUESTED / COMMENTED 等)。
        body: レビュー本文。
        approve_comment: 承認とみなすコメント完全一致文字列 (例: "LGTM")。

    Returns:
        ApprovalDecision。
    """
    normalized_state = (state or "").upper()
    text = (body or "").strip()

    if normalized_state == "APPROVED":
        return ApprovalDecision.APPROVED
    if text and text.upper() == approve_comment.upper():
        return ApprovalDecision.APPROVED
    if normalized_state == "CHANGES_REQUESTED":
        return ApprovalDecision.CHANGES_REQUESTED
    if text:
        return ApprovalDecision.CHANGES_REQUESTED
    return ApprovalDecision.NONE


def resolve_approvers(owner: str, configured: list[str] | None) -> list[str]:
    """承認者の許可リストを解決する。

    設定が空/未指定なら owner のみを許可する (セキュアな既定)。

    Args:
        owner: リポジトリ owner の login。
        configured: 設定された承認者 login のリスト (なければ None/空)。

    Returns:
        許可する承認者 login のリスト。
    """
    if configured:
        return list(configured)
    return [owner]


def is_authorized_approver(login: str | None, approvers: Iterable[str]) -> bool:
    """承認者 login が許可リストに含まれるか検証する (#102)。

    比較は大文字小文字を無視する。login が空なら常に不許可。

    Args:
        login: 承認操作を行ったユーザーの login。
        approvers: 許可された承認者 login の集合。

    Returns:
        許可されていれば True。
    """
    if not login:
        return False
    lowered = login.lower()
    return any(lowered == a.lower() for a in approvers)


def has_authorized_approval_reaction(
    reactions: Iterable[object],
    approvers: Iterable[str],
) -> bool:
    """👍 リアクション群に許可された承認者の +1 が含まれるか判定する (#102)。

    リアクションの content が "+1" かつ user.login が許可リストに含まれる
    ものが 1 つでもあれば承認とみなす。user 情報がないリアクションは無視する。

    Args:
        reactions: Reaction オブジェクトのイテラブル (content / user.login を持つ)。
        approvers: 許可された承認者 login の集合。

    Returns:
        許可された承認者の 👍 があれば True。
    """
    approver_list = list(approvers)
    for reaction in reactions:
        if getattr(reaction, "content", None) != _THUMBSUP:
            continue
        user = getattr(reaction, "user", None)
        login = getattr(user, "login", None) if user is not None else None
        if is_authorized_approver(login, approver_list):
            return True
    return False
