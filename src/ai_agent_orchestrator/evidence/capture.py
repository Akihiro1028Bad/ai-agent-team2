"""Playwright を使った UI スクショ・録画キャプチャ (#91).

Playwright は optional 依存 (``evidence`` extra) のため、関数内 import で扱い、
未インストール時は CaptureUnavailableError に変換して呼び出し側が握り潰せるようにする。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ai_agent_orchestrator.evidence.models import EvidenceItem

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# ビューポート定義 (id, width, height)
_DESKTOP = ("desktop", 1280, 720)
_MOBILE = ("mobile", 390, 844)

_GOTO_TIMEOUT_MS = 30_000


class CaptureError(Exception):
    """キャプチャ処理に失敗した場合に発生する例外."""


class CaptureUnavailableError(CaptureError):
    """Playwright が利用できない (未インストール等) 場合に発生する例外."""


class ScreenCapture(Protocol):
    """UI キャプチャの抽象インターフェース."""

    async def capture(self, url: str, out_dir: Path) -> list[EvidenceItem]:
        """指定 URL のスクショ・録画を out_dir に保存し EvidenceItem を返す."""
        ...


def _now_iso() -> str:
    """現在時刻を ISO8601 UTC 文字列で返す."""
    return datetime.now(UTC).isoformat()


class PlaywrightCapture:
    """Playwright (chromium headless) による UI キャプチャ実装.

    desktop / mobile のスクショと、簡単なスクロール操作付きの録画 (webm) を取得する。
    Playwright 未インストール時は CaptureUnavailableError を送出する。
    """

    async def capture(self, url: str, out_dir: Path) -> list[EvidenceItem]:
        """url のスクショ・録画を取得して out_dir に保存する.

        Args:
            url: キャプチャ対象の URL。
            out_dir: 保存先ディレクトリ (事前に存在している前提)。

        Returns:
            生成した EvidenceItem のリスト。

        Raises:
            CaptureUnavailableError: Playwright が未インストールの場合。
            CaptureError: キャプチャ処理に失敗した場合。
        """
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found,unused-ignore]
        except ImportError as exc:  # pragma: no cover - 依存有無に依存
            msg = "playwright が未インストールです (evidence extra を導入してください)"
            raise CaptureUnavailableError(msg) from exc

        items: list[EvidenceItem] = []
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    items.extend(await self._capture_screenshots(browser, url, out_dir))
                    video_item = await self._capture_video(browser, url, out_dir)
                    if video_item is not None:
                        items.append(video_item)
                finally:
                    await browser.close()
        except CaptureError:
            raise
        except Exception as exc:  # Playwright 例外を一括包む
            msg = f"UI キャプチャに失敗しました: {exc}"
            raise CaptureError(msg) from exc

        return items

    async def _capture_screenshots(self, browser: object, url: str, out_dir: Path) -> list[EvidenceItem]:
        """desktop / mobile のスクショを取得する."""
        items: list[EvidenceItem] = []
        for viewport_id, width, height in (_DESKTOP, _MOBILE):
            context = await browser.new_context(viewport={"width": width, "height": height})  # type: ignore[attr-defined]
            try:
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=_GOTO_TIMEOUT_MS)
                filename = f"screenshot-{viewport_id}.png"
                await page.screenshot(path=str(out_dir / filename), full_page=True)
                items.append(
                    EvidenceItem(
                        id=f"screenshot-{viewport_id}",
                        kind="screenshot",
                        title=f"{viewport_id} スクリーンショット",
                        file=filename,
                        viewport=viewport_id,
                        created_at=_now_iso(),
                    )
                )
            finally:
                await context.close()
        return items

    async def _capture_video(self, browser: object, url: str, out_dir: Path) -> EvidenceItem | None:
        """録画付きでページを開き、軽くスクロールして webm を保存する."""
        context = await browser.new_context(  # type: ignore[attr-defined]
            viewport={"width": _DESKTOP[1], "height": _DESKTOP[2]},
            record_video_dir=str(out_dir),
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=_GOTO_TIMEOUT_MS)
        for _ in range(3):
            await page.mouse.wheel(0, 600)
            await page.wait_for_timeout(1000)
        await context.close()

        # Playwright は close 後に動画を flush する。ファイル名は自動採番のため探してリネーム。
        target = out_dir / "recording.webm"
        webms: Sequence[Path] = sorted(p for p in out_dir.glob("*.webm") if p.name != target.name)
        if not webms:
            logger.warning("録画ファイルが生成されませんでした: %s", url)
            return None
        webms[0].replace(target)
        # 余分な録画ファイルを掃除
        for extra in webms[1:]:
            extra.unlink(missing_ok=True)
        return EvidenceItem(
            id="video",
            kind="video",
            title="操作録画",
            file=target.name,
            created_at=_now_iso(),
        )
