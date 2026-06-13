import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { DesignView } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useParams: vi.fn().mockReturnValue({ id: "129" }),
  useSearchParams: vi.fn().mockReturnValue(new URLSearchParams()),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

// DesignReviewClient は別テストで検証済みのためスタブ化し、ページの分岐に集中する。
vi.mock("@/components/review/DesignReviewClient", () => ({
  DesignReviewClient: ({ issue }: { issue: number }) => <div data-testid={`design-client-${issue}`} />,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, getDesign: vi.fn(), getEvidence: vi.fn() },
  };
});

import { api, ApiError } from "@/lib/api";
import type { EvidenceView } from "@/lib/evidence";
import DesignReviewPage from "@/app/issues/[id]/review/page";

const EMPTY_EVIDENCE: EvidenceView = { generatedAt: null, items: [], notes: [] };

function presentView(): DesignView {
  return {
    present: true,
    planDepth: "full",
    uiImpact: false,
    summary: { anchor: "sum-1", text: "x" },
    architecture: [],
    testCases: [],
    subtasks: [],
    reason: null,
  };
}

describe("DesignReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // エビデンスは既定で空（個別テストで上書き）。
    (api.getEvidence as ReturnType<typeof vi.fn>).mockResolvedValue(EMPTY_EVIDENCE);
  });

  it("present=true で DesignReviewClient を描画する", async () => {
    (api.getDesign as ReturnType<typeof vi.fn>).mockResolvedValue(presentView());
    render(<DesignReviewPage />);

    expect(await screen.findByTestId("design-client-129")).toBeInTheDocument();
  });

  it("エビデンスがあれば EvidenceGallery セクションを描画する", async () => {
    (api.getDesign as ReturnType<typeof vi.fn>).mockResolvedValue(presentView());
    (api.getEvidence as ReturnType<typeof vi.fn>).mockResolvedValue({
      generatedAt: "2026-06-13T00:00:00+00:00",
      items: [
        { id: "screenshot-desktop", kind: "screenshot", title: "デスクトップ スクリーンショット", url: "/api/issues/129/evidence/screenshot-desktop.png", viewport: "desktop", createdAt: undefined },
      ],
      notes: [],
    } satisfies EvidenceView);
    render(<DesignReviewPage />);

    expect(await screen.findByRole("heading", { name: "エビデンス" })).toBeInTheDocument();
    expect(screen.getByAltText("デスクトップ スクリーンショット")).toBeInTheDocument();
  });

  it("エビデンス取得失敗時もレビュー本体は描画される", async () => {
    (api.getDesign as ReturnType<typeof vi.fn>).mockResolvedValue(presentView());
    (api.getEvidence as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("evidence down"));
    render(<DesignReviewPage />);

    expect(await screen.findByTestId("design-client-129")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "エビデンス" })).not.toBeInTheDocument();
  });

  it("present=false は設計未生成メッセージを表示する", async () => {
    (api.getDesign as ReturnType<typeof vi.fn>).mockResolvedValue({
      present: false,
      planDepth: null,
      uiImpact: null,
      summary: null,
      architecture: [],
      testCases: [],
      subtasks: [],
      reason: "設計はまだ生成されていません (PLAN フェーズ未完了)。",
    } satisfies DesignView);
    render(<DesignReviewPage />);

    expect(await screen.findByText(/設計はまだ生成されていません/)).toBeInTheDocument();
    expect(screen.queryByTestId("design-client-129")).not.toBeInTheDocument();
  });

  it("取得失敗時は接続バナーを表示する", async () => {
    (api.getDesign as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(0, "down"));
    render(<DesignReviewPage />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    // エラー時に「設計未生成」等の無関係なメッセージを出さない (誤認防止)。
    expect(screen.queryByText(/設計が生成されていません/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("design-client-129")).not.toBeInTheDocument();
  });

  it("初回は読み込み中を表示する", async () => {
    let resolve!: (v: DesignView) => void;
    (api.getDesign as ReturnType<typeof vi.fn>).mockReturnValue(new Promise<DesignView>((r) => { resolve = r; }));
    render(<DesignReviewPage />);

    expect(screen.getByText("読み込み中…")).toBeInTheDocument();
    resolve(presentView());
    await waitFor(() => expect(screen.getByTestId("design-client-129")).toBeInTheDocument());
  });
});
