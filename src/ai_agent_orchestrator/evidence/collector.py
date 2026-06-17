"""エビデンス収集のオーケストレーション (#91).

IMPLEMENT 完了時に呼ばれ、テストログ・UI スクショ・録画を収集して
manifest.json と各ファイルを evidence ディレクトリに書き出す。dev server の
起動/停止・readiness 待機・各種フォールバックを内部で処理し、collect は
**例外を外に出さない** (失敗は manifest の notes に記録する)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from ai_agent_orchestrator.evidence.capture import (
    CaptureError,
    PlaywrightCapture,
    ScreenCapture,
)
from ai_agent_orchestrator.evidence.models import EvidenceItem
from ai_agent_orchestrator.evidence.paths import evidence_dir

logger = logging.getLogger(__name__)

# テストコマンドのタイムアウト (秒)
_TEST_COMMAND_TIMEOUT_SEC = 600
# 保存するテストログの末尾行数
_TEST_LOG_TAIL_LINES = 400
# dev server 停止時の SIGTERM → SIGKILL 猶予 (秒)
_DEV_STOP_GRACE_SEC = 5.0
# readiness ポーリング間隔 (秒)
_READY_POLL_INTERVAL_SEC = 1.0


class RepoLike(Protocol):
    """エビデンス収集に必要な RepositoryConfig 互換の最小インターフェース.

    すべて任意属性で、未設定 (None) のケースは collect 側でスキップ扱いにする。
    """

    dev_command: str | None
    dev_url: str | None
    dev_ready_timeout_sec: int
    dev_ready_log: str | None
    test_command: str | None


class ReadyProbe(Protocol):
    """dev server の readiness 判定の抽象インターフェース."""

    async def wait_ready(self, url: str, timeout_sec: int) -> bool:
        """url が応答するまで待機し、ready なら True を返す."""
        ...


class HttpReadyProbe:
    """httpx で URL を 1 秒間隔ポーリングする readiness プローブ.

    2xx-4xx を ready とみなす (4xx でもサーバーは応答している)。接続エラーは
    起動待ちとしてリトライする。
    """

    async def wait_ready(self, url: str, timeout_sec: int) -> bool:
        """url が応答するまで最大 timeout_sec 待機する.

        Args:
            url: 監視対象の URL。
            timeout_sec: 待機上限 (秒)。

        Returns:
            ready になれば True、タイムアウトなら False。
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_sec
        async with httpx.AsyncClient(timeout=5.0) as client:
            while loop.time() < deadline:
                try:
                    resp = await client.get(url)
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
                    await asyncio.sleep(_READY_POLL_INTERVAL_SEC)
                    continue
                except httpx.HTTPError:
                    await asyncio.sleep(_READY_POLL_INTERVAL_SEC)
                    continue
                if 200 <= resp.status_code < 500:
                    return True
                await asyncio.sleep(_READY_POLL_INTERVAL_SEC)
        return False


class EvidenceCollector:
    """エビデンス収集を統括するコレクタ.

    test_command 実行ログ・UI キャプチャを収集し manifest を生成する。
    capture / ready_probe は注入可能 (テストで Fake に差し替え)。
    """

    def __init__(
        self,
        workspace_root: Path,
        capture: ScreenCapture | None = None,
        ready_probe: ReadyProbe | None = None,
    ) -> None:
        """EvidenceCollector を初期化する.

        Args:
            workspace_root: ワークスペースのベースディレクトリ。
            capture: UI キャプチャ実装。None なら PlaywrightCapture。
            ready_probe: readiness プローブ。None なら HttpReadyProbe。
        """
        self._workspace_root = workspace_root
        self._capture = capture or PlaywrightCapture()
        self._ready_probe = ready_probe or HttpReadyProbe()
        # 直近に起動した dev server プロセス (テストからの検査用)
        self._dev_proc: asyncio.subprocess.Process | None = None

    async def collect(
        self,
        repo: RepoLike,
        issue_number: int,
        worktree_path: str,
        ui_impact: bool | None,
    ) -> dict[str, Any]:
        """エビデンスを収集し manifest を返す.

        evidence_dir をクリアして再生成し、test_command ログ・UI キャプチャを
        収集する。内部エラーは握り潰し notes に記録する (例外を外に出さない)。

        Args:
            repo: RepositoryConfig 互換 (dev_command/dev_url/test_command 等を持つ)。
            issue_number: Issue 番号。
            worktree_path: コマンド実行先 worktree のパス。
            ui_impact: UI 影響があるか (True のみキャプチャ対象)。

        Returns:
            manifest dict ({"generated_at", "items", "notes"})。
        """
        ev_dir = evidence_dir(self._workspace_root, issue_number)
        self._reset_dir(ev_dir)

        items: list[EvidenceItem] = []
        notes: list[str] = []

        await self._run_test_command(repo, worktree_path, ev_dir, items, notes)
        await self._maybe_capture_ui(repo, worktree_path, ev_dir, ui_impact, items, notes)

        manifest: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(),
            "items": [item.to_dict() for item in items],
            "notes": notes,
        }
        self._write_manifest_atomic(ev_dir, manifest)
        return manifest

    # ------------------------------------------------------------------
    # ディレクトリ / manifest I/O
    # ------------------------------------------------------------------

    @staticmethod
    def _reset_dir(ev_dir: Path) -> None:
        """evidence ディレクトリをクリアして作り直す."""
        if ev_dir.exists():
            shutil.rmtree(ev_dir, ignore_errors=True)
        ev_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_manifest_atomic(ev_dir: Path, manifest: dict[str, Any]) -> None:
        """manifest.json を atomic write (tmp → os.replace) する."""
        target = ev_dir / "manifest.json"
        tmp = ev_dir / "manifest.json.tmp"
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)

    # ------------------------------------------------------------------
    # テストコマンド
    # ------------------------------------------------------------------

    async def _run_test_command(
        self,
        repo: RepoLike,
        worktree_path: str,
        ev_dir: Path,
        items: list[EvidenceItem],
        notes: list[str],
    ) -> None:
        """test_command を worktree 内で実行しログを terminal item として保存する."""
        test_command = getattr(repo, "test_command", None)
        if not test_command:
            return
        try:
            output, exit_code, timed_out = await self._exec_capture(test_command, worktree_path)
        except Exception:
            logger.exception("test_command の実行に失敗しました")
            notes.append("test_command の実行に失敗しました")
            return

        tail = "\n".join(output.splitlines()[-_TEST_LOG_TAIL_LINES:])
        log_text = f"$ {test_command}\n\n{tail}\n\nexit code: {exit_code}\n"
        if timed_out:
            log_text += "(タイムアウトのため打ち切りました)\n"
            notes.append("test_command がタイムアウトしました")
        (ev_dir / "test-log.txt").write_text(log_text, encoding="utf-8")
        items.append(
            EvidenceItem(
                id="terminal",
                kind="terminal",
                title="テスト実行ログ",
                file="test-log.txt",
                created_at=datetime.now(UTC).isoformat(),
            )
        )

    @staticmethod
    async def _exec_capture(command: str, cwd: str) -> tuple[str, int | None, bool]:
        """シェルコマンドを実行し (出力, exit code, タイムアウト有無) を返す."""
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        timed_out = False
        try:
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=_TEST_COMMAND_TIMEOUT_SEC)
        except TimeoutError:
            timed_out = True
            proc.kill()
            stdout_bytes, _ = await proc.communicate()
        return stdout_bytes.decode(errors="replace"), proc.returncode, timed_out

    # ------------------------------------------------------------------
    # UI キャプチャ
    # ------------------------------------------------------------------

    async def _maybe_capture_ui(
        self,
        repo: RepoLike,
        worktree_path: str,
        ev_dir: Path,
        ui_impact: bool | None,
        items: list[EvidenceItem],
        notes: list[str],
    ) -> None:
        """条件を満たす場合のみ dev server を起動して UI キャプチャを実施する."""
        dev_command = getattr(repo, "dev_command", None)
        dev_url = getattr(repo, "dev_url", None)

        if ui_impact is not True:
            notes.append("ui_impact なしのためスクショをスキップしました")
            return
        if not dev_command:
            notes.append("dev_command 未設定のためスクショをスキップしました")
            return
        if not dev_url:
            notes.append("dev_url 未設定のためスクショをスキップしました")
            return

        ready_timeout = int(getattr(repo, "dev_ready_timeout_sec", 60))
        ready_log = getattr(repo, "dev_ready_log", None)
        proc: asyncio.subprocess.Process | None = None
        drain_task: asyncio.Task[None] | None = None
        try:
            # ログパターン待機を使う場合のみ stdout を PIPE で取得する。
            use_log = bool(ready_log)
            proc = await asyncio.create_subprocess_shell(
                dev_command,
                cwd=worktree_path,
                stdout=asyncio.subprocess.PIPE if use_log else asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.STDOUT if use_log else asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            self._dev_proc = proc
            if use_log:
                ready = await self._wait_ready_by_log(proc, str(ready_log), ready_timeout)
                # 準備完了後は stdout を読み続けないとパイプ満杯でプロセスが停止し得る。
                if ready and proc.stdout is not None:
                    drain_task = asyncio.create_task(self._drain_stream(proc.stdout))
            else:
                ready = await self._ready_probe.wait_ready(dev_url, ready_timeout)
            if not ready:
                notes.append(f"dev server が {ready_timeout}s 以内に準備完了しなかったためキャプチャを中止しました")
                return
            captured = await self._capture.capture(dev_url, ev_dir)
            items.extend(captured)
        except CaptureError as exc:
            logger.warning("UI キャプチャをスキップ: %s", exc)
            notes.append(f"UI キャプチャに失敗しました: {exc}")
        except Exception:
            logger.exception("UI キャプチャ中に予期しないエラーが発生しました")
            notes.append("UI キャプチャ中に予期しないエラーが発生しました")
        finally:
            if drain_task is not None:
                drain_task.cancel()
            if proc is not None:
                await self._stop_dev_server(proc)

    @staticmethod
    async def _wait_ready_by_log(
        proc: asyncio.subprocess.Process,
        pattern: str,
        timeout_sec: int,
    ) -> bool:
        """dev server の標準出力に pattern が現れるまで待つ (#91).

        プロセスが先に終了 (EOF) した場合やタイムアウト時は False を返す。

        Args:
            proc: 監視対象の dev server プロセス (stdout=PIPE 必須)。
            pattern: 起動完了を示す部分文字列。
            timeout_sec: 待機上限 (秒)。

        Returns:
            pattern を検出できたら True、そうでなければ False。
        """
        if proc.stdout is None:
            return False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_sec
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except TimeoutError:
                return False
            if not line:  # EOF: プロセスが起動に失敗して終了した
                return False
            if pattern in line.decode(errors="replace"):
                return True

    @staticmethod
    async def _drain_stream(stream: asyncio.StreamReader) -> None:
        """stdout を EOF まで読み捨て、パイプ満杯によるブロックを防ぐ (#91).

        cancel() で停止されるため CancelledError は握らず素通しする。
        """
        try:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    return
        except Exception:
            return

    @staticmethod
    async def _stop_dev_server(proc: asyncio.subprocess.Process) -> None:
        """dev server プロセスグループを SIGTERM → 猶予 → SIGKILL で確実に停止する."""
        if proc.returncode is not None:
            return
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=_DEV_STOP_GRACE_SEC)
        except TimeoutError:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                return
            try:
                await proc.wait()
            except Exception:
                logger.exception("dev server プロセスの停止待機に失敗しました")
