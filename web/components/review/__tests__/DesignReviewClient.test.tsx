import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { DesignView } from "@/lib/api";

// api モック: 提出系のみ差し替え (anchor の流れを検証する)。
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getDefaultActor: vi.fn().mockResolvedValue("owner"),
      postReview: vi.fn().mockResolvedValue("changes_requested"),
    },
  };
});

import { api } from "@/lib/api";
import { DesignReviewClient } from "@/components/review/DesignReviewClient";

function makeView(overrides: Partial<DesignView> = {}): DesignView {
  return {
    present: true,
    planDepth: "full",
    uiImpact: true,
    summary: { anchor: "sum-1", text: "プロフィール画面を追加する。" },
    architecture: [
      { anchor: "arch-1", text: "page.tsx は Server で userId を解決する。" },
      { anchor: "arch-2", text: "ProfileClient が編集状態を管理する。" },
    ],
    testCases: [
      { anchor: "tc-01", text: "正常: 既存ユーザーのプロフィールを返す" },
      { anchor: "tc-02", text: "異常: 存在しない ID で 404" },
    ],
    subtasks: [
      { anchor: "st-1", id: 1, title: "Route Handler の実装" },
      { anchor: "st-2", id: null, title: "ProfilePage の分割" },
    ],
    reason: null,
    ...overrides,
  };
}

describe("DesignReviewClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("実 design.json の各セクションを描画する", () => {
    render(<DesignReviewClient issue={129} view={makeView()} />);

    expect(screen.getByText("プロフィール画面を追加する。")).toBeInTheDocument();
    expect(screen.getByText("page.tsx は Server で userId を解決する。")).toBeInTheDocument();
    expect(screen.getByText("正常: 既存ユーザーのプロフィールを返す")).toBeInTheDocument();
    expect(screen.getByText("Route Handler の実装")).toBeInTheDocument();
    // サーバ anchor がそのまま表示されている (UI 自動採番ではない)。
    expect(screen.getByText("tc-01")).toBeInTheDocument();
    expect(screen.getByText("st-1")).toBeInTheDocument();
    // plan_depth / ui_impact バッジ。
    expect(screen.getByText("plan: full")).toBeInTheDocument();
    expect(screen.getByText("UI 影響あり")).toBeInTheDocument();
  });

  it("差し戻し提出時、サーバ anchor (arch-1) が postReview に載る", async () => {
    const user = userEvent.setup();
    render(<DesignReviewClient issue={129} view={makeView()} />);

    // arch-1 の段落を含む Commentable のコメント追加ボタンを開く。
    const archPara = screen.getByText("page.tsx は Server で userId を解決する。");
    const commentable = archPara.closest(".group\\/c") as HTMLElement;
    await user.click(within(commentable).getByLabelText("コメントを追加"));

    // 指摘を入力 → 下書きに追加。
    await user.type(within(commentable).getByRole("textbox"), "userId 解決の根拠を明記してください");
    await user.click(within(commentable).getByRole("button", { name: "下書きに追加" }));

    // 差し戻して提出。
    await user.click(screen.getByRole("button", { name: /差し戻して提出/ }));

    expect(api.postReview).toHaveBeenCalledTimes(1);
    const [issueArg, commentsArg, actorArg] = (api.postReview as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(issueArg).toBe(129);
    expect(actorArg).toBe("owner");
    expect(commentsArg).toEqual([
      expect.objectContaining({ anchor: "arch-1", tag: "指摘", body: "userId 解決の根拠を明記してください" }),
    ]);
    // 成功メッセージ。
    expect(await screen.findByText(/差し戻しました/)).toBeInTheDocument();
  });

  it("コメント無しの承認は空配列で postReview を呼ぶ", async () => {
    (api.postReview as ReturnType<typeof vi.fn>).mockResolvedValueOnce("approved");
    const user = userEvent.setup();
    render(<DesignReviewClient issue={7} view={makeView()} />);

    await user.click(screen.getByRole("button", { name: "承認" }));

    expect(api.postReview).toHaveBeenCalledWith(7, [], "owner");
    expect(await screen.findByText(/設計を承認しました/)).toBeInTheDocument();
  });

  it("提出失敗時はエラーメッセージを表示する", async () => {
    (api.postReview as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<DesignReviewClient issue={7} view={makeView()} />);

    await user.click(screen.getByRole("button", { name: "承認" }));

    expect(await screen.findByText(/提出に失敗しました/)).toBeInTheDocument();
  });
});
