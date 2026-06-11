"""承認判定ロジック (U4 #82) のテスト.

タイプ別に分散していた承認/差し戻し判定を共通化し、承認者検証 (#102) を
含む純粋関数として検証する。
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# ApprovalDecision / classify_pr_review
# ---------------------------------------------------------------------------


class TestClassifyPrReview:
    """PR レビュー状態の承認/差し戻し分類."""

    def test_approved_state_is_approved(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import ApprovalDecision, classify_pr_review

        assert classify_pr_review("APPROVED", "", "LGTM") is ApprovalDecision.APPROVED

    def test_lgtm_comment_review_is_approved(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import ApprovalDecision, classify_pr_review

        assert classify_pr_review("COMMENTED", "LGTM", "LGTM") is ApprovalDecision.APPROVED

    def test_lgtm_is_case_insensitive(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import ApprovalDecision, classify_pr_review

        assert classify_pr_review("COMMENTED", "lgtm", "LGTM") is ApprovalDecision.APPROVED

    def test_changes_requested_is_changes(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import ApprovalDecision, classify_pr_review

        assert classify_pr_review("CHANGES_REQUESTED", "要修正", "LGTM") is ApprovalDecision.CHANGES_REQUESTED

    def test_plain_comment_is_changes(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import ApprovalDecision, classify_pr_review

        assert classify_pr_review("COMMENTED", "ここを直して", "LGTM") is ApprovalDecision.CHANGES_REQUESTED

    def test_empty_comment_is_none(self) -> None:
        """本文なしの COMMENTED は差し戻しでも承認でもない (情報なし)."""
        from ai_agent_orchestrator.orchestrator.approval import ApprovalDecision, classify_pr_review

        assert classify_pr_review("COMMENTED", "", "LGTM") is ApprovalDecision.NONE

    def test_changes_requested_with_lgtm_body_stays_changes(self) -> None:
        """明示的な CHANGES_REQUESTED は本文が LGTM でも差し戻し (安全側)."""
        from ai_agent_orchestrator.orchestrator.approval import ApprovalDecision, classify_pr_review

        assert classify_pr_review("CHANGES_REQUESTED", "LGTM", "LGTM") is ApprovalDecision.CHANGES_REQUESTED


# ---------------------------------------------------------------------------
# 承認者検証 (#102)
# ---------------------------------------------------------------------------


class TestResolveApprovers:
    """承認者許可リストの解決."""

    def test_configured_list_is_used(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import resolve_approvers

        assert resolve_approvers("owner1", ["alice", "bob"]) == ["alice", "bob"]

    def test_defaults_to_owner_when_unset(self) -> None:
        """approvers 未設定なら owner のみを許可する (セキュアな既定)."""
        from ai_agent_orchestrator.orchestrator.approval import resolve_approvers

        assert resolve_approvers("owner1", None) == ["owner1"]
        assert resolve_approvers("owner1", []) == ["owner1"]


class TestIsAuthorizedApprover:
    """承認者検証."""

    def test_member_is_authorized(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import is_authorized_approver

        assert is_authorized_approver("alice", ["alice", "bob"]) is True

    def test_case_insensitive_match(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import is_authorized_approver

        assert is_authorized_approver("Alice", ["alice"]) is True

    def test_non_member_is_rejected(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import is_authorized_approver

        assert is_authorized_approver("mallory", ["alice", "bob"]) is False

    def test_empty_login_is_rejected(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import is_authorized_approver

        assert is_authorized_approver("", ["alice"]) is False
        assert is_authorized_approver(None, ["alice"]) is False


class TestHasAuthorizedApprovalReaction:
    """👍 リアクションの承認者検証込み判定."""

    def _reaction(self, content: str, login: str | None) -> object:
        from unittest.mock import MagicMock

        r = MagicMock()
        r.content = content
        if login is None:
            r.user = None
        else:
            r.user = MagicMock()
            r.user.login = login
        return r

    def test_authorized_thumbsup_is_approval(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import has_authorized_approval_reaction

        reactions = [self._reaction("+1", "alice")]
        assert has_authorized_approval_reaction(reactions, ["alice"]) is True

    def test_unauthorized_thumbsup_is_not_approval(self) -> None:
        """許可外ユーザーの 👍 は承認として扱わない (#102)."""
        from ai_agent_orchestrator.orchestrator.approval import has_authorized_approval_reaction

        reactions = [self._reaction("+1", "mallory")]
        assert has_authorized_approval_reaction(reactions, ["alice"]) is False

    def test_non_thumbsup_is_ignored(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import has_authorized_approval_reaction

        reactions = [self._reaction("heart", "alice")]
        assert has_authorized_approval_reaction(reactions, ["alice"]) is False

    def test_reaction_without_user_is_ignored(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import has_authorized_approval_reaction

        reactions = [self._reaction("+1", None)]
        assert has_authorized_approval_reaction(reactions, ["alice"]) is False

    def test_mixed_reactions_authorized_wins(self) -> None:
        from ai_agent_orchestrator.orchestrator.approval import has_authorized_approval_reaction

        reactions = [
            self._reaction("+1", "mallory"),
            self._reaction("+1", "alice"),
        ]
        assert has_authorized_approval_reaction(reactions, ["alice"]) is True


# ---------------------------------------------------------------------------
# ApprovalMethod enum
# ---------------------------------------------------------------------------


class TestApprovalMethod:
    """承認方法の enum."""

    def test_methods_exist(self) -> None:
        from ai_agent_orchestrator.models import ApprovalMethod

        assert ApprovalMethod.REACTION.value == "reaction"
        assert ApprovalMethod.PR_APPROVE.value == "pr-approve"
        assert ApprovalMethod.LGTM.value == "lgtm"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
