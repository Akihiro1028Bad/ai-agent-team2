"""FastAPI アプリケーションファクトリと読み取りエンドポイント定義.

orchestrator 本体には触れず、ワークスペース配下のファイル (state.json /
events.jsonl) のみを読み取って Web UI に JSON を返す (#84)。diff のみ GitHub API を
参照し、認証は orchestrator と同一の AccountManager (CredentialResolver) を共有する。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ai_agent_orchestrator.agents.claude_runner import PHASE_CONFIG
from ai_agent_orchestrator.api.design import build_design_response
from ai_agent_orchestrator.api.hearing import build_hearing
from ai_agent_orchestrator.api.middleware import AuthMiddleware
from ai_agent_orchestrator.api.readers import (
    aggregate_costs,
    detail_from_state,
    load_states,
    merge_activity,
    read_agent_logs,
    read_approvals,
    read_evidence,
    read_health,
    read_issue_events,
    read_issue_summaries,
    read_prototypes,
    read_queue,
)
from ai_agent_orchestrator.api.review import build_review_control_record, classify_review
from ai_agent_orchestrator.api.schemas import (
    AgentLogPage,
    ApprovalEntry,
    ConfigMutationResponse,
    ControlAcceptedResponse,
    ControlRequest,
    CostsResponse,
    DesignResponse,
    DiffFile,
    DiffResponse,
    EventRecord,
    EvidenceResponse,
    HealthResponse,
    HearingResponse,
    IssueDetailResponse,
    IssueSummaryResponse,
    PhaseModelRow,
    PhaseModelsRequest,
    PhaseModelsResponse,
    PrototypeResponse,
    QueueResponse,
    ReplyRequest,
    ReplyResponse,
    RepositoriesResponse,
    RepositoryConfigRow,
    RepositoryRegisterRequest,
    ReviewRequest,
    ReviewResponse,
)
from ai_agent_orchestrator.api.stream import (
    KEEPALIVE_INTERVAL_SEC,
    MAX_SSE_CONNECTIONS_PER_ISSUE,
    MAX_SSE_CONNECTIONS_TOTAL,
    SseConnectionLimiter,
    format_sse,
    parse_last_event_id,
    tail_issue_streams,
)
from ai_agent_orchestrator.config.ui_settings import (
    ALLOWED_MODELS,
    effective_phase_models,
    load_ui_settings,
    save_ui_settings,
    ui_settings_from_rows,
    validate_phase_models,
)
from ai_agent_orchestrator.config.ui_settings import (
    ValidationError as UiValidationError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from ai_agent_orchestrator.config.settings import AppSettings
    from ai_agent_orchestrator.models import IssueState

logger = logging.getLogger(__name__)

# エビデンスファイルの拡張子 → media_type マッピング (#91)。未知は octet-stream。
_EVIDENCE_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".webm": "video/webm",
    ".txt": "text/plain; charset=utf-8",
}

# プロトタイプ配信の拡張子 → media_type (#145)。HTML のみ想定。
_PROTOTYPE_MEDIA_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
}


class _DiffClient(Protocol):
    """diff 取得に必要な最小インターフェース (GitHubClient 互換)."""

    async def get_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, object]]: ...


class _CommentClient(Protocol):
    """Issue コメント投稿に必要な最小インターフェース (GitHubClient 互換)."""

    async def create_comment(self, repo: object, issue_number: int, body: str, mark_as_bot: bool = True) -> object: ...


class _CommentListClient(Protocol):
    """Issue コメント取得に必要な最小インターフェース (GitHubClient 互換, #139)."""

    async def list_comments(self, repo: object, issue_number: int) -> list[object]: ...


class ControlSystemd(Protocol):
    """systemd ユニット制御の最小インターフェース (テスト差し替え可能)."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class SystemctlControl:
    """``systemctl --user`` を使って ai-agent-orchestrator ユニットを制御する.

    実環境に systemd が無い場合でも HTTPException を上位に伝播させ、クラッシュしない。
    """

    _UNIT = "ai-agent-orchestrator"

    async def start(self) -> None:
        """``systemctl --user start`` を実行する."""
        await self._run("start")

    async def stop(self) -> None:
        """``systemctl --user stop`` を実行する."""
        await self._run("stop")

    async def _run(self, verb: Literal["start", "stop"]) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl",
                "--user",
                verb,
                self._UNIT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"systemctl exited with code {proc.returncode}")
        except Exception as exc:
            logger.warning("systemctl %s %s に失敗", verb, self._UNIT, exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Failed to control orchestrator service",
            ) from exc


def _append_control_line(path: Path, record: dict[str, object]) -> None:
    """control.jsonl に 1 行 JSON を追記する (同期 I/O。to_thread 経由で呼ぶ)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _build_default_factory(
    settings: AppSettings,
) -> Callable[[str, str], Awaitable[_DiffClient]]:
    """AccountManager ベースのデフォルト github_client_factory を構築する.

    orchestrator と同一の CredentialResolver / AccountManager を使い、
    新しい秘密の受け渡し経路を作らない (仕様 §設計判断2)。

    Args:
        settings: アプリケーション設定。

    Returns:
        (owner, repo) を受け取り認証済みクライアントを返す async callable。
    """
    from ai_agent_orchestrator.credential import CredentialResolver
    from ai_agent_orchestrator.github.client import AccountManager

    manager = AccountManager(
        accounts=settings.accounts,
        resolver=CredentialResolver(),
        repo_configs=settings.repositories,
    )

    async def factory(owner: str, repo: str) -> _DiffClient:
        return await manager.get_client_for_repo(owner, repo)

    return factory


def _resolve_issue(
    states: dict[tuple[str, int], IssueState],
    issue_number: int,
    repo: str | None,
) -> tuple[str, IssueState]:
    """Issue 番号 (+ 任意の repo) から一意の (repo, IssueState) を解決する.

    Args:
        states: load_states() の結果。
        issue_number: Issue 番号。
        repo: "owner/repo" 形式の絞り込み (任意)。

    Returns:
        (repo, IssueState) のタプル。

    Raises:
        HTTPException: 不在なら 404、複数一致かつ repo 未指定なら 400。
    """
    matches = [
        (state_repo, state)
        for (state_repo, number), state in states.items()
        if number == issue_number and (repo is None or state_repo == repo)
    ]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Issue #{issue_number} not found")
    if len(matches) > 1:
        repos = ", ".join(sorted(m[0] for m in matches))
        raise HTTPException(
            status_code=400,
            detail=f"Issue #{issue_number} is ambiguous across repos: {repos}. Specify ?repo=owner/repo",
        )
    return matches[0]


def create_app(settings: AppSettings) -> FastAPI:
    """AppSettings から読み取り API の FastAPI アプリを生成する.

    Args:
        settings: アプリケーション設定。workspace_dir からファイルを読み取る。

    Returns:
        構成済みの FastAPI アプリ。app.state.workspace / github_client_factory を持つ。
    """
    workspace = Path(settings.workspace_dir).expanduser()

    app = FastAPI(title="AI Agent Orchestrator API", version="0.1.0")
    app.add_middleware(AuthMiddleware)

    app.state.workspace = workspace
    # config.yaml のパス (#138 の書き込み系で使用)。api_command が上書きする。
    app.state.config_path = Path(getattr(settings, "config_path", "") or "config.yaml").expanduser()
    # UI 可変設定 (フェーズ別モデル等) のオーバーレイファイル (#90)。config.yaml とは分離。
    app.state.ui_settings_path = Path(settings.ui_settings_file).expanduser()
    app.state.github_client_factory = _build_default_factory(settings)
    app.state.systemd = SystemctlControl()
    # SSE 同時接続のリミッタ (#113 DoS 対策)。テストは app.state 経由で参照できる。
    app.state.sse_limiter = SseConnectionLimiter(
        max_total=MAX_SSE_CONNECTIONS_TOTAL,
        max_per_issue=MAX_SSE_CONNECTIONS_PER_ISSUE,
    )
    # tail のアイドル打ち切り秒数。本番は None (無限) で、テストのみ app.state 経由で
    # 短い値を設定して TestClient のストリームを終端させる。公開 Query には出さない (#113 L3)。
    app.state.sse_max_idle_sec = None

    @app.get("/api/issues", response_model=list[IssueSummaryResponse])
    async def list_issues() -> list[IssueSummaryResponse]:
        """全 Issue の概要を updated_at 降順で返す."""
        return read_issue_summaries(workspace)

    @app.get("/api/issues/{issue_number}", response_model=IssueDetailResponse)
    async def get_issue(
        issue_number: int,
        repo: str | None = Query(default=None),
    ) -> IssueDetailResponse:
        """Issue の詳細を返す. 複数一致かつ repo 未指定は 400、不在は 404."""
        states = load_states(workspace)
        state_repo, state = _resolve_issue(states, issue_number, repo)
        return detail_from_state(workspace, state, state_repo)

    @app.get("/api/issues/{issue_number}/events", response_model=list[EventRecord])
    async def get_issue_events(
        issue_number: int,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> list[EventRecord]:
        """Issue の events.jsonl を新しい順で返す (既定 200 件)."""
        return read_issue_events(workspace, issue_number, limit=limit)

    @app.get("/api/issues/{issue_number}/logs", response_model=AgentLogPage)
    async def get_issue_logs(
        issue_number: int,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> AgentLogPage:
        """Issue の agent.jsonl を物理行オフセット基準でページング取得する (#85)."""
        return read_agent_logs(workspace, issue_number, offset=offset, limit=limit)

    @app.get("/api/stream")
    async def get_stream(
        request: Request,
        issue: int = Query(..., description="対象 Issue 番号"),
        last_event_id: str | None = Query(default=None),
        # 下限 0.1s: 過小値での毎ループ全ファイル読みによる CPU 占有を防ぐ
        poll_interval: float = Query(default=0.5, ge=0.1, le=5.0),
    ) -> Response:
        """events.jsonl + agent.jsonl の tail を SSE で配信する (#85, #113).

        Last-Event-ID は (EventSource polyfill 対応で) ヘッダとクエリの両方を
        受ける。15 秒ごとに keep-alive コメント行を送出する。同時接続数は
        ``app.state.sse_limiter`` で全体 / Issue 単位に制限し、上限超過は 429。
        ストリームはクライアント切断で終端する (テスト用 max_idle_sec は
        tail_issue_streams 側にのみ残し、公開 Query からは外した)。
        """
        limiter: SseConnectionLimiter = app.state.sse_limiter
        if not limiter.try_acquire(issue):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many concurrent stream connections"},
            )

        header_id = request.headers.get("Last-Event-ID")
        start_events, start_agent = parse_last_event_id(header_id or last_event_id)

        async def _gen() -> AsyncIterator[str]:
            # keepalive は tail_issue_streams がアイドル中も source="keepalive" として
            # yield する (format_sse がコメント行へ整形)。イベント待ちで沈黙しない。
            try:
                async for event in tail_issue_streams(
                    workspace,
                    issue,
                    start_events=start_events,
                    start_agent=start_agent,
                    poll_interval=poll_interval,
                    max_idle_sec=app.state.sse_max_idle_sec,
                    keepalive_interval=KEEPALIVE_INTERVAL_SEC,
                ):
                    if await request.is_disconnected():
                        break
                    yield format_sse(event)
            finally:
                # 正常終了・切断・キャンセルのいずれでも接続枠を解放する。
                limiter.release(issue)

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/activity", response_model=list[EventRecord])
    async def get_activity(
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[EventRecord]:
        """全 Issue のイベントをマージし ts 降順で返す (既定 100 件)."""
        return merge_activity(workspace, limit=limit)

    @app.get("/api/health", response_model=HealthResponse)
    async def get_health() -> HealthResponse:
        """orchestrator の稼働状態を返す (#97).

        health.json を読んで返す。不在/古い/running=false でも 200 で
        「停止中である」事実を返す (#84 の停止中でも応答する方針)。
        """
        return read_health(workspace)

    @app.get("/api/queue", response_model=QueueResponse)
    async def get_queue() -> QueueResponse:
        """実行キューの状態を返す (#96).

        queue.json を読んで返す。不在/壊れでも 200 で空キュー + reason を返す
        (#84 の「停止中でも応答」方針)。
        """
        return read_queue(workspace)

    @app.get("/api/issues/{issue_number}/design", response_model=DesignResponse)
    async def get_issue_design(
        issue_number: int,
        repo: str | None = Query(default=None),
    ) -> DesignResponse:
        """Issue の構造化設計 (plan_json 由来・anchor 付き) を返す (#89).

        PLAN 未完了は present=false で 200。複数一致は 400、不在は 404。
        """
        states = load_states(workspace)
        _state_repo, state = _resolve_issue(states, issue_number, repo)
        return build_design_response(state.plan_json)

    @app.get("/api/issues/{issue_number}/evidence", response_model=EvidenceResponse)
    async def get_issue_evidence(issue_number: int) -> EvidenceResponse:
        """Issue のエビデンス manifest を返す (#91).

        manifest が不在/壊れでも 200 で空の EvidenceResponse を返す。各 item の
        url はファイル配信エンドポイントへの相対 URL。
        """
        return read_evidence(workspace, issue_number)

    @app.get("/api/issues/{issue_number}/evidence/{filename}")
    async def get_issue_evidence_file(issue_number: int, filename: str) -> Response:
        """エビデンスファイル (スクショ/録画/ログ) を配信する (#91).

        パストラバーサルを多層で防ぐ: ベース名以外/``..`` 含みは 404、resolve 後に
        evidence ディレクトリ配下にあることを確認する。不在も 404。
        """
        from fastapi.responses import FileResponse

        from ai_agent_orchestrator.evidence.paths import evidence_dir

        # ベース名のみ許可 (サブディレクトリ・トラバーサルを拒否)
        if filename != Path(filename).name or ".." in filename:
            raise HTTPException(status_code=404, detail="Evidence file not found")
        ev_dir = evidence_dir(workspace, issue_number).resolve()
        target = (ev_dir / filename).resolve()
        if ev_dir not in target.parents:
            raise HTTPException(status_code=404, detail="Evidence file not found")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Evidence file not found")

        media_type = _EVIDENCE_MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
        return FileResponse(path=str(target), media_type=media_type)

    @app.get("/api/issues/{issue_number}/prototypes", response_model=PrototypeResponse)
    async def get_issue_prototypes(issue_number: int) -> PrototypeResponse:
        """Issue の UI プロトタイプ manifest を返す (#145).

        manifest が不在/壊れでも 200 で空の PrototypeResponse を返す。各 item の
        url は HTML 配信エンドポイントへの相対 URL (sandbox iframe の src)。
        """
        return read_prototypes(workspace, issue_number)

    @app.get("/api/issues/{issue_number}/prototypes/{filename}")
    async def get_issue_prototype_file(issue_number: int, filename: str) -> Response:
        """UI プロトタイプ HTML を配信する (#145).

        エージェント生成 HTML を返すため、サンドボックス化のセキュリティヘッダを
        必ず付与する: ``Content-Security-Policy: sandbox`` でスクリプトを不透明
        オリジン化し (同一オリジン資源・Cookie へ到達不可)、frame-ancestors を
        'self' に限定。パストラバーサルはエビデンスと同様に多層で防ぐ。
        """
        from fastapi.responses import FileResponse

        from ai_agent_orchestrator.prototype.paths import prototype_dir

        if filename != Path(filename).name or ".." in filename:
            raise HTTPException(status_code=404, detail="Prototype file not found")
        proto_dir = prototype_dir(workspace, issue_number).resolve()
        target = (proto_dir / filename).resolve()
        if proto_dir not in target.parents:
            raise HTTPException(status_code=404, detail="Prototype file not found")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Prototype file not found")

        media_type = _PROTOTYPE_MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
        # エージェント生成 HTML を隔離: sandbox で不透明オリジン化し、埋め込みは自オリジンのみ。
        headers = {
            "Content-Security-Policy": "sandbox allow-scripts; frame-ancestors 'self'",
            "X-Content-Type-Options": "nosniff",
        }
        return FileResponse(path=str(target), media_type=media_type, headers=headers)

    @app.post("/api/issues/{issue_number}/review", response_model=ReviewResponse)
    async def post_issue_review(
        issue_number: int,
        body: ReviewRequest,
        repo: str | None = Query(default=None),
    ) -> ReviewResponse:
        """設計レビュー提出を分類し、承認/差し戻しを control.jsonl へ書く (#89).

        指摘=差し戻し(PLAN) / 質問=差し戻し(回答促し) / 0件=承認。actor の権限検証は
        orchestrator 側 (control_file の approver 検証) で行う。不在 404・複数一致 400。
        """
        states = load_states(workspace)
        _state_repo, _state = _resolve_issue(states, issue_number, repo)
        outcome = classify_review(body.comments)
        record = build_review_control_record(issue_number, body.actor, body.comments)
        control_path: Path = app.state.workspace / "control.jsonl"
        await asyncio.to_thread(_append_control_line, control_path, record)
        return ReviewResponse(outcome=outcome, accepted=True)

    def _phase_models_payload() -> PhaseModelsResponse:
        ui = load_ui_settings(app.state.ui_settings_path)
        rows = effective_phase_models(PHASE_CONFIG, ui)
        return PhaseModelsResponse(
            phases=[PhaseModelRow(**row) for row in rows],
            allowed_models=sorted(ALLOWED_MODELS),
        )

    @app.get("/api/issues/{issue_number}/hearing", response_model=HearingResponse)
    async def get_issue_hearing(
        issue_number: int,
        repo: str | None = Query(default=None),
    ) -> HearingResponse:
        """Issue のヒアリング (clarify) Q&A を構造化して返す (#139).

        Q&A は GitHub Issue コメントが出所のため、diff と同様に github_client_factory で
        コメントを取得して分類する。config 未登録は 404、GitHub 障害は 502 に整形。
        """
        states = load_states(workspace)
        state_repo, state = _resolve_issue(states, issue_number, repo)
        owner, _, name = state_repo.partition("/")
        repo_config = next(
            (r for r in settings.repositories if r.owner == owner and r.repo == name),
            None,
        )
        if repo_config is None:
            raise HTTPException(
                status_code=404,
                detail=f"Repository {state_repo} is not configured in config.yaml",
            )

        from ai_agent_orchestrator.github.client import ConfigError

        factory: Callable[[str, str], Awaitable[_CommentListClient]] = app.state.github_client_factory
        try:
            client = await factory(owner, name)
            comments = await client.list_comments(repo_config, issue_number)
        except ConfigError as e:
            raise HTTPException(
                status_code=404,
                detail=f"Repository {state_repo} is not configured in config.yaml",
            ) from e
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("ヒアリングコメントの取得に失敗: repo=%s issue=%s", state_repo, issue_number, exc_info=True)
            raise HTTPException(
                status_code=502,
                detail="Failed to fetch hearing comments from GitHub",
            ) from e
        return build_hearing(list(comments), state.phase.value)

    def _repositories_payload() -> RepositoriesResponse:
        """config.yaml から監視リポジトリ (非機密のみ) を読み出す (#138/#144).

        書き込み (#138) を即座に UI へ反映するため、in-memory ではなくファイルを
        都度読む。ファイル不在/不正は in-memory settings へフォールバック。
        """
        from ai_agent_orchestrator.config.repo_registry import list_repositories

        config_path: Path = app.state.config_path
        rows_raw = list_repositories(config_path)
        if not rows_raw and not config_path.exists():
            rows_raw = [
                {
                    "owner": r.owner,
                    "repo": r.repo,
                    "account": r.account,
                    "label": r.label,
                    "base_branch": r.base_branch,
                    "slack_channel": r.slack_channel,
                }
                for r in settings.repositories
            ]
        return RepositoriesResponse(repositories=[RepositoryConfigRow(**row) for row in rows_raw])

    @app.get("/api/config/repositories", response_model=RepositoriesResponse)
    async def get_config_repositories() -> RepositoriesResponse:
        """監視対象リポジトリ (config.yaml) を返す (#144/#138).

        **非機密のみ** (owner/repo/account/label/base_branch/slack_channel) を返し、
        token 等は一切含めない。
        """
        return _repositories_payload()

    @app.post(
        "/api/config/repositories",
        response_model=ConfigMutationResponse,
        status_code=201,
    )
    async def add_config_repository(body: RepositoryRegisterRequest) -> ConfigMutationResponse:
        """監視リポジトリを config.yaml に追加する (#138).

        書き込み系。loopback 限定 (AuthMiddleware) 配下。**非機密のみ**を受け取り、
        accounts/機密は温存する。入力不正/未登録 account は 400、重複は 409。
        反映にはオーケストレーター再起動が必要 (restart_required=True)。
        """
        from ai_agent_orchestrator.config.repo_registry import RepoRegistryError, add_repository

        try:
            await asyncio.to_thread(
                add_repository,
                app.state.config_path,
                owner=body.owner,
                repo=body.repo,
                account=body.account,
                label=body.label,
                base_branch=body.base_branch,
            )
        except RepoRegistryError as exc:
            status = 409 if "既に登録" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return ConfigMutationResponse()

    @app.delete("/api/config/repositories/{owner}/{repo}", response_model=ConfigMutationResponse)
    async def delete_config_repository(owner: str, repo: str) -> ConfigMutationResponse:
        """監視リポジトリを config.yaml から削除する (#138). 不在は 404。"""
        from ai_agent_orchestrator.config.repo_registry import remove_repository

        removed = await asyncio.to_thread(remove_repository, app.state.config_path, owner, repo)
        if not removed:
            raise HTTPException(status_code=404, detail=f"{owner}/{repo} は登録されていません")
        return ConfigMutationResponse()

    @app.get("/api/config/phase-models", response_model=PhaseModelsResponse)
    async def get_phase_models() -> PhaseModelsResponse:
        """フェーズ別モデル設定 (既定 + settings.ui.yaml 上書き) を返す (#90).

        機密 (config.yaml) は一切含まない。effective な model/thinking/max_turns のみ。
        """
        return _phase_models_payload()

    @app.put("/api/config/phase-models", response_model=PhaseModelsResponse)
    async def put_phase_models(body: PhaseModelsRequest) -> PhaseModelsResponse:
        """フェーズ別モデル設定を settings.ui.yaml へ保存する (#90).

        全置換セマンティクス: 送られたフェーズのみが overlay に残り、未送フェーズは
        既定値へ戻る (UI は GET の全フェーズを編集して送る前提)。非機密のみ。未知
        フェーズ/モデル・範囲外 max_turns・重複フェーズは 400。max_turns=null は
        「上書きなし (SDK デフォルト)」。保存後は次のフェーズ実行から反映される
        (orchestrator は run() ごとに overlay を再読込)。
        """
        rows = [row.model_dump() for row in body.phases]
        try:
            validate_phase_models(rows)
        except UiValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ui = ui_settings_from_rows(rows)
        await asyncio.to_thread(save_ui_settings, app.state.ui_settings_path, ui)
        return _phase_models_payload()

    @app.get("/api/approvals", response_model=list[ApprovalEntry])
    async def get_approvals() -> list[ApprovalEntry]:
        """人間の承認/レビュー待ち Issue (approve / review 相) を返す (#88)."""
        return read_approvals(workspace)

    @app.post("/api/issues/{issue_number}/reply", response_model=ReplyResponse, status_code=201)
    async def post_issue_reply(
        issue_number: int,
        body: ReplyRequest,
        repo: str | None = Query(default=None),
    ) -> ReplyResponse:
        """ヒアリング回答を GitHub Issue コメントとして投稿する (#88).

        bot マーカーを付けずに投稿し、poller の人間コメント検知フローに乗せる
        (control.jsonl は経由しない)。不在 404、GitHub 障害 502。

        ヒアリング相 (clarify / clarify-wait) 以外は 409 で拒否する: bot アカウント
        名義の非マーカーコメントは承認者コメントとして検知され得るため、review 相へ
        の投稿を許すと LGTM 偽装で承認ゲートを迂回できてしまう (#102 の承認者検証
        と整合させる)。
        """
        from ai_agent_orchestrator.models import Phase

        states = load_states(workspace)
        state_repo, state = _resolve_issue(states, issue_number, repo)
        if state.phase not in (Phase.CLARIFY, Phase.CLARIFY_WAIT):
            raise HTTPException(
                status_code=409,
                detail="Reply is only allowed while the issue is awaiting hearing answers",
            )
        owner, _, name = state_repo.partition("/")
        factory: Callable[[str, str], Awaitable[_CommentClient]] = app.state.github_client_factory
        from ai_agent_orchestrator.config.settings import RepositoryConfig
        from ai_agent_orchestrator.github.client import ConfigError

        try:
            client = await factory(owner, name)
            await client.create_comment(
                RepositoryConfig(owner=owner, repo=name),
                issue_number,
                body.text,
                mark_as_bot=False,
            )
        except ConfigError as e:
            raise HTTPException(
                status_code=404,
                detail=f"Repository {state_repo} is not configured in config.yaml",
            ) from e
        except HTTPException:
            raise
        except Exception as e:
            # detail に内部例外の文字列を含めない (情報漏えい防止)。詳細はログのみ。
            logger.warning("ヒアリング回答の投稿に失敗: repo=%s issue=%d", state_repo, issue_number, exc_info=True)
            raise HTTPException(
                status_code=502,
                detail="Failed to post reply comment to GitHub",
            ) from e
        return ReplyResponse(posted=True)

    @app.get("/api/costs", response_model=CostsResponse)
    async def get_costs() -> CostsResponse:
        """phase_completed の cost_usd を総額・Issue 別・フェーズ別に集計する."""
        return aggregate_costs(workspace)

    @app.get("/api/issues/{issue_number}/diff", response_model=DiffResponse)
    async def get_issue_diff(
        issue_number: int,
        repo: str | None = Query(default=None),
    ) -> DiffResponse:
        """Issue に紐づく PR の差分 (files + patch) を返す. pr_number 無しは 404."""
        states = load_states(workspace)
        state_repo, state = _resolve_issue(states, issue_number, repo)
        if state.pr_number is None:
            raise HTTPException(
                status_code=404,
                detail=f"Issue #{issue_number} has no associated pull request",
            )
        owner, _, name = state_repo.partition("/")
        factory: Callable[[str, str], Awaitable[_DiffClient]] = app.state.github_client_factory
        # GitHub 呼び出し失敗を素の 500 で返さない: config 未登録は 404、
        # API 障害 (認証・レート制限・ネットワーク等) は 502 に整形する。
        from ai_agent_orchestrator.github.client import ConfigError

        try:
            client = await factory(owner, name)
            raw_files = await client.get_pull_request_files(owner, name, state.pr_number)
        except ConfigError as e:
            raise HTTPException(
                status_code=404,
                detail=f"Repository {state_repo} is not configured in config.yaml",
            ) from e
        except HTTPException:
            raise
        except Exception as e:
            # detail に内部例外の文字列を含めない (内部 URL 等の情報漏えい防止)。
            # 詳細はサーバーログ側にのみ出す。
            logger.warning("PR 差分の取得に失敗: repo=%s pr=%s", state_repo, state.pr_number, exc_info=True)
            raise HTTPException(
                status_code=502,
                detail="Failed to fetch pull request diff from GitHub",
            ) from e
        files = [DiffFile.model_validate(f) for f in raw_files]
        return DiffResponse(pr_number=state.pr_number, files=files)

    @app.post("/api/control", response_model=ControlAcceptedResponse, status_code=202)
    async def post_control(body: ControlRequest) -> ControlAcceptedResponse:
        """運用コマンドを control.jsonl に追記する.

        orchestrator 側の ControlBus が非同期に消費する。API は形式検証と追記のみ担当
        し、actor の権限検証は orchestrator 側で行う。
        """
        control_path: Path = app.state.workspace / "control.jsonl"
        await asyncio.to_thread(_append_control_line, control_path, body.to_control_record())
        return ControlAcceptedResponse(accepted=True)

    @app.post("/api/orchestrator/{action}", status_code=200)
    async def post_orchestrator_action(action: str) -> ControlAcceptedResponse:
        """orchestrator systemd ユニットを start / stop する.

        stop は control.jsonl に shutdown コマンドを先に追記してから
        ``systemctl --user stop`` を呼ぶ2段階構成。
        systemd が無い / 失敗した場合は 503 を返す。未知の action は 404。
        """
        if action not in ("start", "stop"):
            # 入力値はエコーバックしない (固定メッセージ)。
            raise HTTPException(status_code=404, detail="Unknown orchestrator action")
        systemd: ControlSystemd = app.state.systemd
        if action == "stop":
            # shutdown コマンドを先に追記してから systemd に stop を伝える。
            control_path: Path = app.state.workspace / "control.jsonl"
            await asyncio.to_thread(
                _append_control_line,
                control_path,
                {"action": "shutdown", "actor": "api"},
            )
            await systemd.stop()
        else:
            await systemd.start()
        return ControlAcceptedResponse(accepted=True)

    return app
