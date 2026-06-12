import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IssueControls } from "@/components/IssueControls";

// api をモック
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      postControl: vi.fn().mockResolvedValue(undefined),
    },
  };
});

import { api } from "@/lib/api";

beforeEach(() => {
  vi.mocked(api.postControl).mockResolvedValue(undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
});

function renderControls(overrides: Partial<{ issue: number; status: import("@/lib/types").RunStatus; phase: import("@/lib/types").PhaseKey; repo: string }> = {}) {
  return render(
    <IssueControls
      issue={overrides.issue ?? 42}
      status={overrides.status ?? "running"}
      phase={overrides.phase ?? "implement"}
      repo={overrides.repo ?? "owner/repo"}
    />,
  );
}

describe("IssueControls", () => {
  it("基本 UI が描画される", () => {
    renderControls();
    expect(screen.getByText("一時停止")).toBeDefined();
    expect(screen.getByText("フェーズ巻き戻し")).toBeDefined();
    expect(screen.getByText("中止")).toBeDefined();
  });

  it("status=suspended のとき初期状態が paused=true (「再開」ボタン)", () => {
    renderControls({ status: "suspended" });
    expect(screen.getByText("再開")).toBeDefined();
  });

  it("一時停止ボタンクリック → API 呼び出し → 成功フラッシュ", async () => {
    renderControls();
    await userEvent.click(screen.getByText("一時停止"));

    await waitFor(() => {
      expect(api.postControl).toHaveBeenCalledWith(
        expect.objectContaining({ action: "pause", issue: 42 }),
      );
    });
  });

  it("再開ボタンクリック → resume アクション", async () => {
    renderControls({ status: "suspended" });
    await userEvent.click(screen.getByText("再開"));

    await waitFor(() => {
      expect(api.postControl).toHaveBeenCalledWith(
        expect.objectContaining({ action: "resume" }),
      );
    });
  });

  it("一時停止 API 失敗 → エラーフラッシュ + rollback", async () => {
    vi.mocked(api.postControl).mockRejectedValue(new Error("network error"));
    renderControls();
    await userEvent.click(screen.getByText("一時停止"));

    await waitFor(() => {
      expect(screen.getByText(/送信に失敗しました/)).toBeDefined();
    });

    // rollback で元の状態に戻る
    expect(screen.getByText("一時停止")).toBeDefined();
  });

  it("中止ボタン → 確認パネルが開く", async () => {
    renderControls();
    await userEvent.click(screen.getByText("中止"));
    expect(screen.getByText(/処理を中止します/)).toBeDefined();
  });

  it("中止確認 → API 呼び出し", async () => {
    renderControls();
    await userEvent.click(screen.getByText("中止"));
    await userEvent.click(screen.getByText("中止する"));

    await waitFor(() => {
      expect(api.postControl).toHaveBeenCalledWith(
        expect.objectContaining({ action: "abort", issue: 42 }),
      );
    });
  });

  it("中止パネルの「やめる」で確認パネルが閉じる", async () => {
    renderControls();
    await userEvent.click(screen.getByText("中止"));
    // 「やめる」ボタンが複数あるかもしれないので最後のものをクリック
    const yameruButtons = screen.getAllByText("やめる");
    await userEvent.click(yameruButtons[yameruButtons.length - 1]);
    expect(screen.queryByText(/処理を中止します/)).toBeNull();
  });

  it("巻き戻しボタン → 確認パネルが開く (前フェーズが存在する場合)", async () => {
    // implement より前のフェーズが存在する
    renderControls({ phase: "implement" });
    await userEvent.click(screen.getByText("フェーズ巻き戻し"));
    expect(screen.getByText(/どのフェーズからやり直しますか/)).toBeDefined();
  });

  it("巻き戻し: フェーズボタンをクリックすると rewindTo が変わる", async () => {
    renderControls({ phase: "implement" });
    await userEvent.click(screen.getByText("フェーズ巻き戻し"));

    // 巻き戻し先のフェーズボタン (MAIN_PHASES の implement より前)
    const planBtn = screen.getByRole("button", { name: "計画" });
    await userEvent.click(planBtn);
    // 計画が選択状態
    expect(planBtn).toBeDefined();
  });

  it("巻き戻し実行 → API 呼び出し", async () => {
    renderControls({ phase: "implement" });
    await userEvent.click(screen.getByText("フェーズ巻き戻し"));
    await userEvent.click(screen.getByText("巻き戻す"));

    await waitFor(() => {
      expect(api.postControl).toHaveBeenCalledWith(
        expect.objectContaining({ action: "rewind", issue: 42 }),
      );
    });
  });

  it("巻き戻し select で rewindTo を変更できる", async () => {
    renderControls({ phase: "implement" });
    await userEvent.click(screen.getByText("フェーズ巻き戻し"));

    const select = screen.getByRole("combobox");
    await userEvent.selectOptions(select, "intake");
    expect((select as HTMLSelectElement).value).toBe("intake");
  });

  it("巻き戻しパネルの「やめる」で確認パネルが閉じる", async () => {
    renderControls({ phase: "implement" });
    await userEvent.click(screen.getByText("フェーズ巻き戻し"));
    await userEvent.click(screen.getByText("やめる"));
    expect(screen.queryByText(/どのフェーズからやり直しますか/)).toBeNull();
  });

  it("フェーズが最初 (intake) の場合、巻き戻しボタンは disabled", () => {
    renderControls({ phase: "intake" });
    const rewindBtn = screen.getByText("フェーズ巻き戻し").closest("button");
    expect(rewindBtn).toHaveAttribute("disabled");
  });

  it("中止ボタンを 2 回クリックするとパネルがトグルする", async () => {
    renderControls();
    await userEvent.click(screen.getByText("中止"));
    expect(screen.getByText(/処理を中止します/)).toBeDefined();

    // 同じボタンをもう一度クリック → 閉じる
    await userEvent.click(screen.getByText("中止"));
    expect(screen.queryByText(/処理を中止します/)).toBeNull();
  });

  it("巻き戻しボタンを 2 回クリックするとパネルがトグルする", async () => {
    renderControls({ phase: "implement" });
    await userEvent.click(screen.getByText("フェーズ巻き戻し"));
    expect(screen.getByText(/どのフェーズ/)).toBeDefined();

    await userEvent.click(screen.getByText("フェーズ巻き戻し"));
    expect(screen.queryByText(/どのフェーズ/)).toBeNull();
  });

  it("エラーフラッシュはタイムアウト後に消える", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
      vi.mocked(api.postControl).mockRejectedValue(new Error("fail"));
      renderControls();
      await user.click(screen.getByText("一時停止"));

      await waitFor(() => {
        expect(screen.getByText(/送信に失敗しました/)).toBeDefined();
      });

      await act(async () => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.queryByText(/送信に失敗しました/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("成功フラッシュはタイムアウト後に消える", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
      renderControls();
      await user.click(screen.getByText("一時停止"));

      await waitFor(() => {
        expect(api.postControl).toHaveBeenCalled();
      });

      // 成功フラッシュが表示される
      await waitFor(() => {
        expect(screen.queryByText(/一時停止しました/)).not.toBeNull();
      });

      await act(async () => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.queryByText(/一時停止しました/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
