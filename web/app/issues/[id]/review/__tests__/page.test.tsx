import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { DesignView } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useParams: vi.fn().mockReturnValue({ id: "129" }),
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
    api: { ...actual.api, getDesign: vi.fn() },
  };
});

import { api, ApiError } from "@/lib/api";
import DesignReviewPage from "@/app/issues/[id]/review/page";

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
  });

  it("present=true で DesignReviewClient を描画する", async () => {
    (api.getDesign as ReturnType<typeof vi.fn>).mockResolvedValue(presentView());
    render(<DesignReviewPage />);

    expect(await screen.findByTestId("design-client-129")).toBeInTheDocument();
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
