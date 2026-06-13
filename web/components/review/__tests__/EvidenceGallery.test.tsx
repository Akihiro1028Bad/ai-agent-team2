import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Evidence } from "@/lib/evidence";
import { EvidenceGallery } from "@/components/review/EvidenceGallery";

const SHOT: Evidence = {
  id: "screenshot-desktop",
  kind: "screenshot",
  title: "デスクトップ スクリーンショット",
  url: "/api/issues/42/evidence/screenshot-desktop.png",
  viewport: "desktop",
  createdAt: "2026-06-13T00:00:00+00:00",
};

const VIDEO: Evidence = {
  id: "video",
  kind: "video",
  title: "操作録画",
  url: "/api/issues/42/evidence/recording.webm",
};

const TERMINAL: Evidence = {
  id: "terminal",
  kind: "terminal",
  title: "テスト実行ログ",
  url: "/api/issues/42/evidence/test-log.txt",
};

describe("EvidenceGallery", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("items が空のとき notes（スキップ理由）を表示する", () => {
    render(<EvidenceGallery items={[]} notes={["dev_command 未設定のためスクショをスキップしました"]} />);
    expect(screen.getByText("エビデンスは生成されていません。")).toBeInTheDocument();
    expect(screen.getByText(/dev_command 未設定/)).toBeInTheDocument();
  });

  it("空 + notes 無しでもフォールバック文を表示する", () => {
    render(<EvidenceGallery items={[]} />);
    expect(screen.getByText("この Issue にはエビデンスがありません。")).toBeInTheDocument();
  });

  it("screenshot は配信 URL を src にした img を描画する", () => {
    render(<EvidenceGallery items={[SHOT]} />);
    const img = screen.getByAltText("デスクトップ スクリーンショット") as HTMLImageElement;
    expect(img).toBeInTheDocument();
    expect(img.getAttribute("src")).toBe(SHOT.url);
    // viewport / 生成時刻のメタが「・」区切りで出る
    expect(screen.getByText(/デスクトップ ・ /)).toBeInTheDocument();
  });

  it("video は配信 URL を src にした video 要素を描画する", () => {
    const { container } = render(<EvidenceGallery items={[VIDEO]} />);
    const video = container.querySelector("video");
    expect(video).not.toBeNull();
    expect(video?.getAttribute("src")).toBe(VIDEO.url);
  });

  it("terminal は url のテキストを fetch して表示する", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("$ uv run pytest\n\n1091 passed\nexit code: 0\n"),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<EvidenceGallery items={[TERMINAL]} />);

    await waitFor(() => expect(screen.getByText(/1091 passed/)).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(TERMINAL.url, expect.objectContaining({ signal: expect.anything() }));
  });

  it("terminal の fetch 失敗時はエラーメッセージを出す", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    render(<EvidenceGallery items={[TERMINAL]} />);
    await waitFor(() => expect(screen.getByText("ログの取得に失敗しました。")).toBeInTheDocument());
  });

  it("カードをクリックすると Lightbox（dialog）が開く", async () => {
    const user = userEvent.setup();
    render(<EvidenceGallery items={[SHOT]} />);
    // グリッドのカードボタン（タイトルを含む）をクリック
    await user.click(screen.getAllByText("デスクトップ スクリーンショット")[0]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    // Lightbox 内にも img が出る
    expect(within(dialog).getByAltText("デスクトップ スクリーンショット")).toBeInTheDocument();
  });
});
