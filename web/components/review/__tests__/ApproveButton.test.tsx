import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

// api モック: 承認系のみ差し替え。
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getDefaultActor: vi.fn().mockResolvedValue("owner"),
      postReview: vi.fn().mockResolvedValue("approved"),
    },
  };
});

import { api } from "@/lib/api";
import { ApproveButton } from "@/components/review/ApproveButton";

describe("ApproveButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("承認クリックで空コメントの postReview を repo 付きで呼ぶ (#146)", async () => {
    const user = userEvent.setup();
    render(<ApproveButton issue={44} repo="owner/site" />);

    await user.click(screen.getByRole("button", { name: "承認" }));

    expect(api.postReview).toHaveBeenCalledWith(44, [], "owner", "owner/site");
  });

  it("承認後に受理フィードバックを表示する (#146)", async () => {
    const user = userEvent.setup();
    render(<ApproveButton issue={44} />);

    await user.click(screen.getByRole("button", { name: "承認" }));

    expect(await screen.findByText(/承認を受理しました/)).toBeInTheDocument();
  });

  it("onApproved コールバックを承認成功後に呼ぶ", async () => {
    const onApproved = vi.fn();
    const user = userEvent.setup();
    render(<ApproveButton issue={1} onApproved={onApproved} />);

    await user.click(screen.getByRole("button", { name: "承認" }));
    await screen.findByText(/承認を受理しました/);

    expect(onApproved).toHaveBeenCalledTimes(1);
  });

  it("承認失敗時はエラーメッセージを表示しボタンは残る", async () => {
    (api.postReview as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<ApproveButton issue={1} />);

    await user.click(screen.getByRole("button", { name: "承認" }));

    expect(await screen.findByText(/承認の送信に失敗しました/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "承認" })).toBeInTheDocument();
  });
});
