"""EventRouter (イベント→フェーズ遷移).

PollEvent を受け取り、StateMachineManager で遷移を実行し、
TaskQueue にタスクをエンキューする。
イベントを統一パイプライン (INTAKE→…→DONE) のフェーズ遷移にルーティングする。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ai_agent_orchestrator.models import PHASE_MIGRATION, EventType, IssueKey, Phase, PollEvent, make_issue_key
from ai_agent_orchestrator.orchestrator.task_queue import Priority, TaskRequest

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import RepositoryConfig
    from ai_agent_orchestrator.github.client import GitHubClient
    from ai_agent_orchestrator.orchestrator.execution_guard import ExecutionGuard
    from ai_agent_orchestrator.orchestrator.orchestrator import Notifier
    from ai_agent_orchestrator.orchestrator.state_machine import StateMachineManager
    from ai_agent_orchestrator.orchestrator.task_queue import TaskQueue
    from ai_agent_orchestrator.protocols import GitHubClientProtocol

logger = logging.getLogger(__name__)


def _opt_str(value: object) -> str | None:
    """githubkit の Unset / None / str を str | None へ正規化する (#142).

    Issue.body などは型上 ``Unset | str | None`` を取り得る。state へ渡す前に
    文字列以外 (Unset / None) を None へ畳む。
    """
    return value if isinstance(value, str) else None


_IMPL_REVIEW_PROMPT = """\
@claude /review

## レビュー観点（実装レビュー）

以下の観点でこのPRの実装をレビューしてください。

### チェック項目
- **バグ・潜在的なバグ（最重要）**: ロジックエラー、エッジケース、競合状態、None 参照
- **コード品質・可読性**: 関数分割、命名、複雑度
- **設計品質**: 責務分離、Protocol 準拠、依存関係の適切さ
- **セキュリティ**: 認証・認可、入力検証、シークレット漏洩リスク
- **CLAUDE.md規約との整合性**:
  - mypy strict モード準拠（全関数に型アノテーション）
  - async/await の正しい使用（ブロッキング呼び出し禁止）
  - docstring（クラスと公開メソッドに必須、Google style）
  - 具体的な例外クラスの使用（裸の `except:` 禁止）
- **テストカバレッジ**: 境界値・異常系のテストが充足しているか
"""


def _format_review_comments(comments: list[dict[str, Any]]) -> str:
    """レビューコメントリストをプロンプト用テキストにフォーマットする.

    Args:
        comments: レビューコメントの辞書リスト.

    Returns:
        フォーマットされたプロンプト文字列.
    """
    if not comments:
        return ""
    lines: list[str] = []
    for i, comment in enumerate(comments, 1):
        user = (comment.get("user") or {}).get("login", "reviewer")
        path = comment.get("path", "")
        line = comment.get("line", "")
        body = comment.get("body", "")
        lines.append(f"### 指摘 {i} ({user})\n**ファイル**: `{path}` 行 {line}\n{body}")
    return "\n\n".join(lines)


class EventRouter:
    """イベントをフェーズ遷移アクションに変換する.

    PollEvent を受け取り、StateMachineManager で遷移を実行し、
    TaskQueue にタスクをエンキューする。
    イベント種別ごとに統一パイプラインのフェーズ遷移・エンキューを行う。
    """

    def __init__(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        account_manager: object | None = None,
        notifier: Notifier | None = None,
        execution_guard: ExecutionGuard | None = None,
    ) -> None:
        """EventRouter を初期化する.

        Args:
            state_machine: ステートマシンマネージャ.
            task_queue: タスクキュー.
            account_manager: AccountManager (GitHub ラベル更新用、省略可).
            notifier: 通知送信 (Slack 等、省略可).
            execution_guard: フェーズ実行中の状態遷移を防止するガード (省略可).
        """
        self._sm = state_machine
        self._tq = task_queue
        self._account_manager = account_manager
        self._notifier = notifier
        self._guard = execution_guard
        # impl-revise に渡し済みのレビューコメント ID（延期イベント再生時の
        # 二重実行防止。インメモリのため再起動後の初回は再実行され得るが許容）
        self._handled_review_comment_ids: dict[IssueKey, set[int]] = {}

    @staticmethod
    def _issue_key_from_event(event: PollEvent) -> IssueKey:
        """PollEvent から IssueKey を生成する."""
        repo_key = f"{event.repo.owner}/{event.repo.repo}"
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        return make_issue_key(repo_key, event.issue.number)

    async def _get_client(self, repo: object) -> GitHubClient | None:
        """リポジトリに対応する GitHubClient を取得する (省略可能).

        account_manager が設定されていない場合は None を返す。

        Args:
            repo: リポジトリ設定オブジェクト.

        Returns:
            GitHubClient または None.
        """
        if self._account_manager is None:
            return None
        if hasattr(self._account_manager, "get_client_for_repo"):
            owner = getattr(repo, "owner", "")
            repo_name = getattr(repo, "repo", "")
            result: Any = await self._account_manager.get_client_for_repo(owner, repo_name)
            return result  # type: ignore[no-any-return]
        return None

    async def route(self, event: PollEvent) -> None:
        """イベントを処理し、適切な遷移とエンキューを行う.

        Args:
            event: 処理するポーリングイベント.

        イベントとアクションの対応:
            NEW_ISSUE           -> register_issue + INTAKE エンキュー
            ISSUE_COMMENT       -> hearing_continue エンキュー (遷移なし)
            HEARING_TIMEOUT     -> SUSPENDED 遷移
            PLAN_REACTION_ADDED -> APPROVE->IMPLEMENT (👍で方針承認)
            PLAN_COMMENT_ADDED  -> APPROVE->PLAN (方針指摘で再計画)
            DESIGN_PR_APPROVED  -> IMPLEMENT 遷移 + エンキュー
            DESIGN_PR_COMMENTED -> DESIGN (PLAN) 遷移 + feedback 付きエンキュー (U4 #82)
            IMPL_PR_APPROVED    -> DONE 遷移 + エンキュー
            IMPL_PR_COMMENTED   -> REVISE 遷移 + エンキュー
            CI_RESULT (failed)  -> REVISE(trigger=ci) (3回以内) or SUSPENDED
            CI_RESULT (passed)  -> REVIEW 遷移
            SPLIT_APPROVED      -> SPLIT 内で実行ステップをエンキュー
            SPLIT_MODIFIED      -> CLARIFY 遷移 + エンキュー
        """
        logger.info(
            "Routing event: type=%s issue=#%s",
            event.type,
            event.issue.number if event.issue else "N/A",
        )
        repo_key = f"{event.repo.owner}/{event.repo.repo}"
        logger.debug(
            "route: dispatching type=%s issue_key=(%s, #%s) comment=%s",
            event.type,
            repo_key,
            event.issue.number if event.issue else "N/A",
            event.comment.id if event.comment else "none",
        )

        # ガードチェック: Issue が実行中の場合はイベントを保留
        if self._guard is not None and event.issue is not None:
            issue_key = self._issue_key_from_event(event)
            if await self._guard.is_executing(issue_key):
                logger.info(
                    "Issue #%d: currently executing, deferring event %s",
                    event.issue.number,
                    event.type,
                )
                await self._guard.defer_event(issue_key, event)
                return

        # 検知したイベントに👀リアクションを付ける
        await self._add_eyes_reaction(event)

        match event.type:
            case EventType.NEW_ISSUE:
                await self._handle_new_issue(event)
            case EventType.ISSUE_COMMENT:
                await self._handle_hearing_reply(event)
            case EventType.HEARING_TIMEOUT:
                await self._handle_hearing_timeout(event)
            case EventType.PLAN_REACTION_ADDED:
                await self._handle_plan_reaction(event)
            case EventType.PLAN_COMMENT_ADDED:
                await self._handle_plan_comment(event)
            case EventType.DESIGN_PR_APPROVED:
                await self._handle_design_pr_approved(event)
            case EventType.DESIGN_PR_COMMENTED:
                await self._handle_design_pr_commented(event)
            case EventType.IMPL_PR_MERGED:
                await self._handle_impl_pr_merged(event)
            case EventType.IMPL_PR_APPROVED:
                await self._handle_impl_pr_approved(event)
            case EventType.IMPL_PR_COMMENTED:
                await self._handle_impl_pr_commented(event)
            case EventType.CI_RESULT:
                await self._handle_ci_result(event)
            case EventType.SPLIT_APPROVED:
                await self._handle_split_approved(event)
            case EventType.SPLIT_MODIFIED:
                await self._handle_split_modified(event)
            case _:
                logger.warning("Unknown event type: %s", event.type)

    # ------------------------------------------------------------------
    # Reaction helper
    # ------------------------------------------------------------------

    async def _add_eyes_reaction(self, event: PollEvent) -> None:
        """検知したイベントに👀リアクションを付ける."""
        try:
            client = await self._get_client(event.repo)
            if client is None:
                return
            if event.comment is not None:
                await client.add_comment_reaction(
                    event.repo,
                    event.comment.id,
                    "eyes",
                )
            elif event.issue is not None:
                await client.add_issue_reaction(
                    event.repo,
                    event.issue.number,
                    "eyes",
                )
        except Exception:
            logger.debug(
                "Failed to add reaction for event %s",
                event.type,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Recovery helper
    # ------------------------------------------------------------------

    async def _ensure_registered(self, event: PollEvent) -> None:
        """Issue が未登録の場合、ラベルからタイプ・フェーズを推定して自動登録する.

        オーケストレーター再起動後に state.json が消失した場合のリカバリ。
        """
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        try:
            self._sm.get_phase(issue_key)
            return  # 登録済み
        except KeyError:
            pass

        repo_key = f"{event.repo.owner}/{event.repo.repo}"
        labels = [str(lbl.name) if hasattr(lbl, "name") else str(lbl) for lbl in (event.issue.labels or [])]

        # タイプをラベルから推定。不正な type:* ラベル (collaborator が誤付与/
        # 細工した値) で set_issue_type が ValueError を出し error 通知スパムに
        # なるのを防ぐため、許可値以外はデフォルトへフォールバックする
        issue_type = "bug"  # デフォルト
        valid_types = {"bug", "feature-m", "feature-l"}
        for lbl in labels:
            if lbl.startswith("type:"):
                candidate = lbl.replace("type:", "")
                if candidate in valid_types:
                    issue_type = candidate
                else:
                    logger.warning(
                        "Issue #%d: invalid type label '%s', defaulting to 'bug'",
                        event.issue.number,
                        lbl,
                    )
                break

        # フェーズをラベルから推定。旧ラベル (phase:impl-review 等) は
        # PHASE_MIGRATION で新フェーズへ読み替える (U5 移行期のリカバリ堅牢化)
        current_phase = Phase.APPROVE  # デフォルト(plan_reaction の呼び出し元)
        for lbl in labels:
            if lbl.startswith("phase:"):
                phase_str = lbl.replace("phase:", "")
                try:
                    current_phase = Phase(phase_str)
                except ValueError:
                    migrated = PHASE_MIGRATION.get(phase_str)
                    if migrated is not None:
                        current_phase = migrated
                break

        logger.info(
            "Auto-registering Issue #%d (recovered): type=%s, phase=%s",
            event.issue.number,
            issue_type,
            current_phase.value,
        )
        self._sm.register_issue(
            issue_number=event.issue.number,
            repo=repo_key,
            initial_phase=current_phase,
            title=_opt_str(event.issue.title),
            body=_opt_str(event.issue.body),
        )
        self._sm.set_issue_type(issue_key, issue_type)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    async def _handle_new_issue(self, event: PollEvent) -> None:
        """新規 Issue: ステートマシンに登録し、INTAKE をエンキュー."""
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        repo_key = f"{event.repo.owner}/{event.repo.repo}"
        # 既に登録済みの場合はスキップ (再ポーリングで重複検知される)。
        # ただし title/body が未保存の旧データなら、この機会に補完する (#142)。
        try:
            self._sm.get_phase(issue_key)
            self._sm.backfill_issue_meta(
                issue_key,
                title=_opt_str(event.issue.title),
                body=_opt_str(event.issue.body),
            )
            return  # 登録済み
        except KeyError:
            pass  # 未登録 -> 登録に進む
        self._sm.register_issue(
            issue_number=event.issue.number,
            repo=repo_key,
            initial_phase=Phase.INTAKE,
            title=_opt_str(event.issue.title),
            body=_opt_str(event.issue.body),
        )
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.INTAKE.value,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_hearing_reply(self, event: PollEvent) -> None:
        """ヒアリング回答: HEARING_WAIT → HEARING 遷移して再実行."""
        if event.comment is None:
            raise ValueError(f"event.comment must not be None for event type {event.type}")
        issue_number = int(str(event.comment.issue_url).split("/")[-1])
        repo_key = f"{event.repo.owner}/{event.repo.repo}"
        issue_key = make_issue_key(repo_key, issue_number)

        # 現在のフェーズを確認
        try:
            current_phase = self._sm.get_phase(issue_key)
        except KeyError:
            logger.warning("Issue #%d is not registered, skipping hearing reply", issue_number)
            return

        if current_phase == Phase.CLARIFY_WAIT:
            # 回答待ち → hearing に遷移して再実行
            await self._sm.transition(issue_key, Phase.CLARIFY)
            # ラベル更新
            try:
                client = await self._get_client(event.repo)
                if client:
                    await client.replace_phase_label(event.repo, issue_number, "phase:clarify")
            except Exception:
                logger.warning("Failed to update phase label to hearing for issue #%d", issue_number)
        elif current_phase == Phase.CLARIFY:
            # AI 実行中にユーザーが回答 → 遷移せずキューイングのみ
            pass
        elif current_phase == Phase.SUSPENDED:
            # SUSPENDED → HEARING に復帰
            await self._sm.transition(issue_key, Phase.CLARIFY)
            logger.info("Issue #%d resumed from SUSPENDED to CLARIFY", issue_number)
        else:
            # HEARING/HEARING_WAIT/SUSPENDED 以外のフェーズなら無視
            # (SPLIT_PROPOSAL等のフェーズでコメントを誤検知しないようにする)
            logger.info("Issue #%d is in phase %s, ignoring hearing reply", issue_number, current_phase)
            return

        await self._tq.enqueue(
            TaskRequest(
                issue_number=issue_number,
                repo=event.repo,
                phase=Phase.CLARIFY.value,
                priority=Priority.HIGH,
                extra={"comment": event.comment.body},
            )
        )

    async def _handle_hearing_timeout(self, event: PollEvent) -> None:
        """ヒアリングタイムアウト: SUSPENDED に遷移."""
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        await self._sm.transition(issue_key, Phase.SUSPENDED)
        try:
            client = await self._get_client(event.repo)
            if client:
                await client.replace_phase_label(event.repo, event.issue.number, "phase:suspended")
        except Exception:
            logger.warning("Failed to update phase label to suspended for issue #%d", event.issue.number)

    async def _handle_plan_reaction(self, event: PollEvent) -> None:
        """方針承認 (thumbsup リアクション): reaction-style プランのみ IMPLEMENT へ遷移.

        approval_style が reaction でないプラン (旧 feature) は警告ログを出力して
        早期リターンする (U5c #95)。
        """
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        # 未登録の場合は自動登録(再起動後のリカバリ)
        await self._ensure_registered(event)
        # U5c (#95): リアクション (👍) 承認は reaction-style プラン (旧 bug) 専用。
        # pr-style プラン (旧 feature) は PR approve 経由で承認する。
        params = self._sm.get_workflow_params(issue_key)
        if params.approval_style != "reaction":
            logger.warning(
                "Issue #%d uses %s approval, plan reaction only applies to reaction-style plans",
                event.issue.number,
                params.approval_style,
            )
            return
        next_phase = Phase.IMPLEMENT

        # 既に遷移先フェーズにいる場合はスキップ (再起動後の重複検出対策)
        current_phase = self._sm.get_phase(issue_key)
        if current_phase == next_phase:
            logger.info(
                "Issue #%d is already in %s, skipping duplicate plan reaction",
                event.issue.number,
                next_phase.value,
            )
            return
        # APPROVE ゲート以外での 👍 は無視する (U5 #83)。再起動リカバリで
        # ラベルと SM 状態が乖離した場合に PLAN→IMPLEMENT 等の不正遷移で
        # InvalidTransitionError になるのを防ぐ
        if current_phase != Phase.APPROVE:
            logger.info(
                "Issue #%d is in %s (not APPROVE), ignoring plan reaction",
                event.issue.number,
                current_phase.value,
            )
            return

        # 承認検出を通知: Issue に🚀リアクション + コメント
        await self._notify_plan_approved(event, next_phase)

        # Slack 通知
        await self._notify_approval_accepted(
            event.issue.number,
            f"{event.repo.owner}/{event.repo.repo}",
            "方針",
        )

        await self._sm.transition(issue_key, next_phase)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=next_phase.value,
                priority=Priority.NORMAL,
            )
        )

    async def _notify_plan_approved(self, event: PollEvent, next_phase: Phase) -> None:
        """方針承認を検出したことを Issue 上で通知する."""
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        try:
            client = await self._get_client(event.repo)
            if client is None:
                return
            await client.add_issue_reaction(event.repo, event.issue.number, "rocket")
            phase_label = "修正"
            await client.create_comment(
                event.repo,
                event.issue.number,
                f"👍 方針承認を確認しました。{phase_label}を開始します。",
            )
        except Exception:
            logger.debug(
                "Failed to notify plan approval for issue #%d",
                event.issue.number,
                exc_info=True,
            )

    async def _notify_approval_accepted(
        self,
        issue_number: int,
        repo_full_name: str,
        phase_label: str,
    ) -> None:
        """承認後の再開通知を Slack に送信する."""
        if self._notifier is None:
            return
        try:
            await self._notifier.notify(
                f"Issue #{issue_number} の{phase_label}が承認されました。次のフェーズに進みます",
                metadata={
                    "notification_type": "approval_accepted",
                    "issue": issue_number,
                    "repo": repo_full_name,
                },
            )
        except Exception:
            logger.debug(
                "Failed to send approval notification for issue #%d",
                issue_number,
                exc_info=True,
            )

    async def _handle_plan_comment(self, event: PollEvent) -> None:
        """方針指摘コメント: reaction-style プランのみ PLAN (再計画) へ遷移.

        approval_style が reaction でないプラン (旧 feature) は警告ログを出力して
        早期リターンする (U5c #95)。
        既に PLAN にいる場合は遷移をスキップする (重複防止)。
        """
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        # 現在のフェーズを確認し、既に修正フェーズにいる場合はスキップ
        try:
            current_phase = self._sm.get_phase(issue_key)
        except KeyError:
            logger.warning("Issue #%d is not registered, skipping plan comment", event.issue.number)
            return

        # U5c (#95): プランコメント承認は reaction-style プラン (旧 bug) 専用。
        params = self._sm.get_workflow_params(issue_key)
        if params.approval_style != "reaction":
            logger.warning(
                "Issue #%d uses %s approval, plan comment only applies to reaction-style plans",
                event.issue.number,
                params.approval_style,
            )
            return
        next_phase = Phase.PLAN

        if current_phase == next_phase:
            logger.info(
                "Issue #%d already in %s, skipping duplicate plan comment",
                event.issue.number,
                next_phase.value,
            )
            return
        if current_phase != Phase.APPROVE:
            logger.info(
                "Issue #%d is in %s (not approve), ignoring plan comment",
                event.issue.number,
                current_phase.value,
            )
            return

        await self._sm.transition(issue_key, next_phase)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=next_phase.value,
                priority=Priority.NORMAL,
                extra={
                    "feedback": event.comment.body if event.comment else "",
                },
            )
        )

    async def _handle_design_pr_approved(self, event: PollEvent) -> None:
        """設計 PR approve: IMPLEMENT へ遷移してエンキュー.

        設計・実装は同一ブランチ (feature/issue-XX) の同一PRで管理するため、
        設計PRのマージは不要。承認後すぐに実装フェーズへ遷移する。
        """
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        current_phase = self._sm.get_phase(issue_key)
        if current_phase != Phase.APPROVE:
            logger.info(
                "Issue #%d is in %s, not APPROVE, skipping design_pr_approved",
                event.issue.number,
                current_phase,
            )
            return
        await self._notify_approval_accepted(
            event.issue.number,
            f"{event.repo.owner}/{event.repo.repo}",
            "設計PR",
        )
        await self._sm.transition(issue_key, Phase.IMPLEMENT)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.IMPLEMENT.value,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_design_pr_commented(self, event: PollEvent) -> None:
        """設計 PR の差し戻し (指摘): APPROVE ゲートとして design (PLAN) へ戻す (U4 #82).

        統一パイプラインでは design-review は実装前の APPROVE ゲートであり、
        その差し戻しは PLAN (design) へ戻して指摘全文を feedback として再設計させる
        (plan-review→analysis と対称)。指摘全文は extra["feedback"] で渡す。
        """
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        current_phase = self._sm.get_phase(issue_key)
        if current_phase != Phase.APPROVE:
            logger.info(
                "Issue #%d is in %s, not APPROVE, skipping design_pr_commented",
                event.issue.number,
                current_phase,
            )
            return
        feedback = (event.extra or {}).get("comments", "")
        await self._sm.transition(issue_key, Phase.PLAN)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.PLAN.value,
                priority=Priority.CRITICAL,
                extra={"feedback": feedback},
            )
        )

    async def _handle_impl_pr_merged(self, event: PollEvent) -> None:
        """実装 PR マージ: DONE へ遷移し、DoneExecutor をエンキュー.

        ユーザーが手動で PR をマージした段階で Issue を完了させる。
        fix フェーズがまだ impl-review に遷移完了していないタイミングで
        マージが検知される場合があるため、先に impl-review へ遷移させる。
        """
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        current_phase = self._sm.get_phase(issue_key)
        if current_phase not in (Phase.REVIEW, Phase.DONE):
            logger.info(
                "Issue #%d: PR merged while in %s, transitioning to impl-review first",
                event.issue.number,
                current_phase,
            )
            await self._sm.transition(issue_key, Phase.REVIEW)
        await self._sm.transition(issue_key, Phase.DONE)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.DONE.value,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_impl_pr_approved(self, event: PollEvent) -> None:
        """実装 PR approve: ログのみ。DONE 遷移はしない.

        実装PRの完了はマージ (IMPL_PR_MERGED) で判定する。
        approve/LGTM は参考情報としてログに記録する。
        """
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        logger.info(
            "Issue #%d: impl PR approved (waiting for merge to complete)",
            event.issue.number,
        )

    async def _handle_impl_pr_commented(self, event: PollEvent) -> None:
        """実装 PR コメント (指摘): 全未対応コメントを収集して IMPL_REVISE へ遷移."""
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)

        current_phase = self._sm.get_phase(issue_key)
        if current_phase == Phase.IMPLEMENT:
            logger.info(
                "Issue #%d is still in implement phase, skipping PR comment",
                event.issue.number,
            )
            return

        if current_phase == Phase.REVISE:
            # 既に IMPL_REVISE 中: スキップするが、全コメント収集により
            # 先発タスクが全コメントを包含済みのため問題なし
            logger.info(
                "Issue #%d is already in impl-revise, skipping (all comments already included in pending task)",
                event.issue.number,
            )
            return

        # PR の全未対応レビューコメントを収集（1回のreviseで全件対応するため）
        state = self._sm.get_state(issue_key)
        all_review_comments: list[dict[str, Any]] = []
        client = await self._get_client(event.repo)  # 1回だけ取得して再利用
        if client and state and state.pr_number:
            try:
                all_review_comments = await client.get_pr_review_comments(event.repo, state.pr_number)
            except Exception:
                logger.warning(
                    "Issue #%d: failed to fetch review comments, using event comments",
                    event.issue.number,
                    exc_info=True,
                )

        # 回答済みコメントを対象から除外 (#103: 永続化された ID。再起動を跨いで有効)
        answered_ids_ref = getattr(state, "answered_review_comment_ids", None) if state else None
        answered = set(answered_ids_ref) if isinstance(answered_ids_ref, list) else set()
        had_inline_comments = bool(all_review_comments)
        if answered:
            all_review_comments = [c for c in all_review_comments if c.get("id") not in answered]
        # トップレベルコメント（PR 本文コメント）はインライン収集に含まれないため、
        # それが存在する場合は「全件回答済み」でもスキップしない（サイレント消失防止）。
        # ただし応答済みの review id は永続 dedup の対象（再起動を跨いだ本文応答の重複防止）
        event_review_id = (event.extra or {}).get("review_id")
        answered_rids_ref = getattr(state, "answered_review_ids", None) if state else None
        top_level_answered = (
            isinstance(answered_rids_ref, list)
            and isinstance(event_review_id, int)
            and event_review_id in answered_rids_ref
        )
        has_top_level_comment = bool((event.extra or {}).get("comments", "")) and not top_level_answered
        if not all_review_comments and not has_top_level_comment and (had_inline_comments or top_level_answered):
            logger.info(
                "Issue #%d: all review comments already answered (inline=%d, top_level=%s), skipping re-enqueue",
                event.issue.number,
                len(answered),
                top_level_answered,
            )
            return

        # コメント一覧をフォーマット（プロンプト用）
        comments_text = _format_review_comments(all_review_comments)
        if not comments_text:
            # フォールバック: イベントの extra から取得
            comments_text = (event.extra or {}).get("comments", "")

        comment_ids = [c["id"] for c in all_review_comments]

        # 延期イベント再生の二重実行防止: 収集したコメントが全て処理済みなら
        # 再エンキューしない（先行タスクが全コメント包含で対応済みのため）
        handled = self._handled_review_comment_ids.get(issue_key, set())
        if comment_ids and set(comment_ids) <= handled:
            logger.info(
                "Issue #%d: no new review comments (%d already handled), skipping re-enqueue",
                event.issue.number,
                len(comment_ids),
            )
            return

        # フェーズ遷移・エンキュー（先に確定させる）
        await self._sm.transition(issue_key, Phase.REVISE)
        accepted = await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.REVISE.value,
                priority=Priority.CRITICAL,
                extra={
                    "comments": comments_text,
                    "review_comment_ids": comment_ids,
                    # 構造化リスト（U2: 修正要求/質問の分類と ID 対応付けに使用）
                    "review_comments": all_review_comments,
                    # トップレベル本文応答の永続 dedup 用 (#103)
                    "review_id": event_review_id,
                },
            )
        )
        if accepted is False:
            # キュー側で重複スキップされた場合は処理済みとして記録しない。
            # 記録すると次回の延期再生時に「処理済み」と誤判定され、
            # このコメントへの対応が永久に行われなくなる。
            logger.info(
                "Issue #%d: enqueue was skipped as duplicate, leaving comments unhandled for retry",
                event.issue.number,
            )
            return
        self._handled_review_comment_ids[issue_key] = handled | set(comment_ids)

        # 着手通知: 遷移・エンキュー成功後、未通知のコメントにのみ返信する (#103)
        # （遷移失敗時は例外が上位に伝播するため、ここに到達した場合は必ず修正が開始される）
        if client and state and state.pr_number and all_review_comments:
            acked_ids_ref = getattr(state, "acknowledged_review_comment_ids", None)
            acked = set(acked_ids_ref) if isinstance(acked_ids_ref, list) else set()
            to_ack = [c for c in all_review_comments if c.get("id") not in acked]
            if to_ack:
                acked_now = await self._reply_to_review_comments(
                    client,
                    event.repo,
                    state.pr_number,
                    to_ack,
                    "レビュー指摘を確認しました。修正を開始します。",
                )
                # 送信に成功した ID のみ記録（失敗分は次回再送される）
                if acked_now and isinstance(acked_ids_ref, list):
                    acked_ids_ref.extend(acked_now)
                    acked_ids_ref[:] = sorted(set(acked_ids_ref))  # 防御的な重複排除
                    self._sm.persist()
        else:
            # フォールバック: PRスレッドへの返信ができない場合は Issue コメントで通知
            await self._notify_review_received(event, comments_text)

    async def _reply_to_review_comments(
        self,
        client: GitHubClientProtocol,
        repo: RepositoryConfig,
        pr_number: int,
        review_comments: list[dict[str, Any]],
        body: str,
    ) -> list[int]:
        """PRレビューコメントの各スレッドに返信する.

        Args:
            client: GitHub クライアントインスタンス（呼び出し元で取得済みのものを渡す）.
            repo: リポジトリ設定.
            pr_number: PR 番号.
            review_comments: レビューコメントのリスト.
            body: 返信本文.

        Returns:
            返信に成功したコメント ID のリスト（失敗分は次回再送できるよう含めない）.
        """
        succeeded: list[int] = []
        for comment in review_comments:
            comment_id = comment.get("id")
            if not comment_id:
                continue
            try:
                await client.reply_to_review_comment(
                    repo,
                    pr_number,
                    comment_id,
                    body,
                )
                succeeded.append(comment_id)
            except Exception:
                logger.debug(
                    "Failed to reply to review comment %d",
                    comment_id,
                    exc_info=True,
                )
        return succeeded

    async def _notify_review_received(self, event: PollEvent, comments: str) -> None:
        """PR レビュー指摘を検出したことを Issue 上で通知する."""
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        try:
            client = await self._get_client(event.repo)
            if client is None:
                return
            await client.add_issue_reaction(event.repo, event.issue.number, "eyes")
            await client.create_comment(
                event.repo,
                event.issue.number,
                f"PR のレビュー指摘を確認しました。修正を開始します。\n\n> {comments[:500]}"
                if comments
                else "PR のレビュー指摘を確認しました。修正を開始します。",
            )
        except Exception:
            logger.debug(
                "Failed to notify review received for issue #%d",
                event.issue.number,
                exc_info=True,
            )

    async def _handle_ci_result(self, event: PollEvent) -> None:
        """CI 結果: extra の ci_status に応じて分岐.

        ci_status == "failure":
            3 回以内 -> CI_FIX へ遷移してエンキュー
            3 回超過 -> SUSPENDED へ遷移 (手動対応が必要)
        ci_status == "success":
            -> IMPL_REVIEW 遷移 (エンキュー不要、PR approve/comment をポーリングで待つ)
        """
        if event.issue is None:
            logger.warning("CI result event has no issue, skipping")
            return
        issue_key = self._issue_key_from_event(event)
        ci_status = (event.extra or {}).get("ci_status", "")

        if ci_status == "failure":
            current_phase = self._sm.get_phase(issue_key)
            if current_phase not in (Phase.IMPLEMENT, Phase.REVIEW, Phase.REVISE):
                logger.info(
                    "Issue #%d is in %s, not IMPLEMENT/REVIEW/REVISE, skipping ci_result failure",
                    event.issue.number,
                    current_phase,
                )
                return
            retry_count = await self._sm.get_ci_retry_count(issue_key)
            if retry_count < 3:
                await self._sm.transition(issue_key, Phase.REVISE)
                await self._tq.enqueue(
                    TaskRequest(
                        issue_number=event.issue.number,
                        repo=event.repo,
                        phase=Phase.REVISE.value,
                        priority=Priority.HIGH,
                        extra={
                            # U5 (#83): REVISE 内で CI 修正フローへ振り分けるトリガー
                            "trigger": "ci",
                            "ci_logs": (event.extra or {}).get("ci_logs", ""),
                            "retry_count": retry_count + 1,
                        },
                    )
                )
            else:
                await self._sm.transition(issue_key, Phase.SUSPENDED)
                try:
                    client = await self._get_client(event.repo)
                    if client:
                        await client.replace_phase_label(event.repo, event.issue.number, "phase:suspended")
                except Exception:
                    logger.warning("Failed to update phase label to suspended for issue #%d", event.issue.number)
        elif ci_status == "success":
            current = self._sm.get_phase(issue_key)
            if current != Phase.REVIEW:
                await self._sm.transition(issue_key, Phase.REVIEW)
                # フェーズ遷移が実際に発生した場合のみ @claude /review を投稿（冪等性保証）
                await self._post_impl_review_comment(event)
            # ラベルを impl-review に更新 (ci-fix → impl-review)
            try:
                client = await self._get_client(event.repo)
                if client:
                    await client.replace_phase_label(event.repo, event.issue.number, "phase:review")
            except Exception:
                logger.warning("Failed to update phase label to impl-review for issue #%d", event.issue.number)
            # IMPL_REVIEW はポーリングで PR approve/comment を待つため、エンキュー不要

    async def _post_impl_review_comment(self, event: PollEvent) -> None:
        """CI パス後に実装PRへ @claude /review コメントを投稿する.

        Args:
            event: CI 結果イベント。
        """
        if event.issue is None:
            return
        try:
            client = await self._get_client(event.repo)
            if client is None:
                return

            issue_key = self._issue_key_from_event(event)
            state = self._sm.get_state(issue_key)
            if state is None or state.pr_number is None:
                logger.warning(
                    "Issue #%d: pr_number not found in state, skipping @claude /review",
                    event.issue.number,
                )
                return

            await client.create_comment(event.repo, state.pr_number, _IMPL_REVIEW_PROMPT)
            logger.info(
                "Issue #%d: posted @claude /review comment to impl PR #%d",
                event.issue.number,
                state.pr_number,
            )
        except Exception:
            logger.warning(
                "Issue #%d: failed to post @claude /review to impl PR",
                event.issue.number,
                exc_info=True,
            )

    async def _handle_split_approved(self, event: PollEvent) -> None:
        """分割承認 (Feature-L): SPLIT フェーズ内で実行ステップをエンキュー.

        U5 (#83): 提案→承認→実行は SPLIT フェーズ内で完結するため遷移はなく、
        extra["step"]="execute" で実行ステップへ進める。
        """
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        current_phase = self._sm.get_phase(issue_key)
        if current_phase != Phase.SPLIT:
            logger.info(
                "Issue #%d is in %s, not SPLIT, skipping split_approved",
                event.issue.number,
                current_phase,
            )
            return
        # Web 承認待ちフラグを解除する (#150)。
        self._sm.set_awaiting_split_approval(issue_key, False)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.SPLIT.value,
                priority=Priority.NORMAL,
                extra={"step": "execute"},
            )
        )

    async def _handle_split_modified(self, event: PollEvent) -> None:
        """分割修正指示 (Feature-L): CLARIFY へ遷移して再ヒアリング."""
        if event.issue is None:
            raise ValueError(f"event.issue must not be None for event type {event.type}")
        issue_key = self._issue_key_from_event(event)
        # Web 承認待ちフラグを解除する (#150)。
        self._sm.set_awaiting_split_approval(issue_key, False)
        await self._sm.transition(issue_key, Phase.CLARIFY)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.CLARIFY.value,
                priority=Priority.NORMAL,
                extra={
                    "modification_request": (event.comment.body if event.comment else ""),
                },
            )
        )
