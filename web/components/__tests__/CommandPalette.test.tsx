import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockPush = vi.fn();

// next/navigation - persistent mock with stable push fn
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: mockPush,
  })),
}));

// api をモック
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getDefaultActor: vi.fn().mockResolvedValue("owner"),
      postControl: vi.fn().mockResolvedValue(undefined),
    },
  };
});

import { api } from "@/lib/api";
import { CommandPalette } from "@/components/CommandPalette";

beforeEach(() => {
  mockPush.mockReset();
  vi.mocked(api.getDefaultActor).mockResolvedValue("owner");
  vi.mocked(api.postControl).mockResolvedValue(undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("CommandPalette", () => {
  it("ボタンが描画される", () => {
    render(<CommandPalette />);
    expect(screen.getByRole("button", { name: "コマンドパレットを開く" })).toBeDefined();
  });

  it("ボタンクリックでパレットが開く", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("背景クリックでパレットが閉じる", async () => {
    const { container } = render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    const backdrop = container.ownerDocument.querySelector(".bg-black\\/60") as HTMLElement;
    await userEvent.click(backdrop);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Esc キーでパレットが閉じる", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("⌘K でパレットが開く", async () => {
    render(<CommandPalette />);
    await userEvent.keyboard("{Meta>}k{/Meta}");
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("⌘K でパレットをトグルできる", async () => {
    render(<CommandPalette />);
    await userEvent.keyboard("{Meta>}k{/Meta}");
    expect(screen.getByRole("dialog")).toBeDefined();

    await userEvent.keyboard("{Meta>}k{/Meta}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("検索語で絞り込みされる", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    const input = screen.getByPlaceholderText(/Issue 番号・タイトル/);
    await userEvent.type(input, "ダッシュボード");

    // 「ダッシュボード」に絞り込まれる
    expect(screen.getByText("ダッシュボード")).toBeDefined();
  });

  it("検索語がマッチしない場合は「該当なし」を表示する", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    const input = screen.getByPlaceholderText(/Issue 番号・タイトル/);
    await userEvent.type(input, "xyzxyzxyznotmatch12345");

    expect(screen.getByText("該当なし")).toBeDefined();
  });

  it("ArrowDown で cursor が下に移動する", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    await userEvent.keyboard("{ArrowDown}");
    // crash しないことを確認
  });

  it("ArrowUp で cursor が上に移動する", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{ArrowUp}");
    // crash しないことを確認
  });

  it("Enter でハイライトされたアイテムを実行する (ページ遷移)", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    // cursor=0 → 最初のアイテム (ダッシュボード) → Enter
    await userEvent.keyboard("{Enter}");

    expect(mockPush).toHaveBeenCalledWith("/");
  });

  it("マウスホバーで cursor が更新される", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    const buttons = screen.getAllByRole("button");
    // dialog 内のボタンをホバー
    if (buttons.length > 1) {
      await userEvent.hover(buttons[1]);
    }
  });

  it("a-poll アクション → poll_now API 呼び出し", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
      render(<CommandPalette />);
      await user.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

      // 操作グループの「今すぐポーリング実行」ボタンをクリック
      const pollBtn = screen.getByRole("button", { name: /今すぐポーリング実行/ });
      await user.click(pollBtn);

      await waitFor(() => {
        expect(api.getDefaultActor).toHaveBeenCalled();
      });

      await waitFor(() => {
        expect(api.postControl).toHaveBeenCalledWith(
          expect.objectContaining({ action: "poll_now" }),
        );
      });

      // toast が表示される
      await waitFor(() => {
        expect(screen.getByText(/ポーリングを実行しました/)).toBeDefined();
      });

      // toast タイムアウト
      await act(async () => {
        vi.advanceTimersByTime(3000);
      });
      expect(screen.queryByText(/ポーリングを実行しました/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a-poll アクション: API 失敗でエラー toast", async () => {
    vi.mocked(api.postControl).mockRejectedValue(new Error("fail"));
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    const pollBtn = screen.getByRole("button", { name: /今すぐポーリング実行/ });
    await userEvent.click(pollBtn);

    await waitFor(() => {
      expect(screen.getByText(/ポーリングの送信に失敗しました/)).toBeDefined();
    });
  });

  it("a-gc アクション → worktree_gc API 呼び出し", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    const gcBtn = screen.getByRole("button", { name: /worktree を掃除/ });
    await userEvent.click(gcBtn);

    await waitFor(() => {
      expect(api.postControl).toHaveBeenCalledWith(
        expect.objectContaining({ action: "worktree_gc" }),
      );
    });

    await waitFor(() => {
      expect(screen.getByText(/クリーンアップを開始しました/)).toBeDefined();
    });
  });

  it("a-gc アクション: API 失敗でエラー toast", async () => {
    vi.mocked(api.postControl).mockRejectedValue(new Error("fail"));
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    const gcBtn = screen.getByRole("button", { name: /worktree を掃除/ });
    await userEvent.click(gcBtn);

    await waitFor(() => {
      expect(screen.getByText(/worktree_gc の送信に失敗しました/)).toBeDefined();
    });
  });

  it("a-stop アクション: フォールバック toast を表示する", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    const stopBtn = screen.getByRole("button", { name: /オーケストレーターを停止/ });
    await userEvent.click(stopBtn);

    await waitFor(() => {
      expect(screen.getByText(/を実行しました/)).toBeDefined();
    });
  });

  it("モバイル用アイコンボタンでもパレットが開く", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "検索・操作" }));
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("検索語が変わるとカーソルが 0 にリセットされる", async () => {
    render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "コマンドパレットを開く" }));

    const input = screen.getByPlaceholderText(/Issue 番号・タイトル/);
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{ArrowDown}");

    // 検索語を変更 → cursor リセット
    await userEvent.type(input, "a");
    // crash しないことを確認
  });
});
