import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AddIssueButton } from "@/components/AddIssueButton";

// Portal は body に createPortal するので jsdom でそのまま動く
// api.postControl をモック
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      postControl: vi.fn().mockResolvedValue(undefined),
      getRepositories: vi.fn().mockResolvedValue([]),
      createIssue: vi.fn().mockResolvedValue({ number: 7, repo: "o/r", url: "https://github.com/o/r/issues/7" }),
    },
    actorForRepo: actual.actorForRepo,
  };
});

import { api } from "@/lib/api";

const REPO = (owner: string, repo: string) => ({ owner, repo, label: "ai-agent", baseBranch: "main" });

beforeEach(() => {
  vi.clearAllMocks(); // factory の vi.fn は restoreAllMocks で履歴クリアされないため明示的に
  vi.mocked(api.postControl).mockResolvedValue(undefined);
  vi.mocked(api.getRepositories).mockResolvedValue([REPO("o", "r")]);
  vi.mocked(api.createIssue).mockResolvedValue({ number: 7, repo: "o/r", url: "https://github.com/o/r/issues/7" });
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("AddIssueButton", () => {
  it("ボタンが描画される", () => {
    render(<AddIssueButton />);
    expect(screen.getByRole("button", { name: /Issue を投入/ })).toBeDefined();
  });

  it("ボタンをクリックするとダイアログが開く", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("X ボタンでダイアログが閉じる", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));
    await userEvent.click(screen.getByRole("button", { name: "閉じる" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("キャンセルボタンでダイアログが閉じる", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));
    await userEvent.click(screen.getByRole("button", { name: "キャンセル" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("背景クリックでダイアログが閉じる", async () => {
    const { container } = render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));

    const backdrop = container.ownerDocument.querySelector(".bg-black\\/60") as HTMLElement;
    expect(backdrop).not.toBeNull();
    await userEvent.click(backdrop);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("URL モード: 有効な URL で送信ボタンが有効化される", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));

    const input = screen.getByPlaceholderText(/github\.com\/owner/);
    await userEvent.type(input, "https://github.com/owner/repo/issues/42");

    const submitBtn = screen.getByRole("button", { name: "受付キューに追加" });
    expect(submitBtn).not.toHaveAttribute("disabled");
  });

  it("URL モード: URL を送信すると API が呼ばれ成功メッセージが出る", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));

    const input = screen.getByPlaceholderText(/github\.com\/owner/);
    await userEvent.type(input, "https://github.com/owner/repo/issues/42");
    await userEvent.click(screen.getByRole("button", { name: "受付キューに追加" }));

    await waitFor(() => {
      expect(api.postControl).toHaveBeenCalledWith(
        expect.objectContaining({ action: "enqueue_issue", issue: 42 }),
      );
    });

    expect(screen.getByText(/ai-agent ラベルを付与し/)).toBeDefined();
  });

  it("URL モード: API 失敗でエラーメッセージが出る", async () => {
    vi.mocked(api.postControl).mockRejectedValue(new Error("fail"));
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));

    const input = screen.getByPlaceholderText(/github\.com\/owner/);
    await userEvent.type(input, "https://github.com/owner/repo/issues/10");
    await userEvent.click(screen.getByRole("button", { name: "受付キューに追加" }));

    await waitFor(() => {
      expect(screen.getByText(/送信に失敗しました/)).toBeDefined();
    });
  });

  it("URL モード: issue 番号が取れない URL でエラーメッセージが出る", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));

    // valid パターンはマッチするが issues/\d+ の数字が取れない URL
    // valid = /github\.com\/.+\/issues\/\d+/.test(url) で true になるように
    // でも URL.match(/issues\/(\d+)/) が null になる URL は作れないので
    // valid チェックをパスする "github.com/owner/repo/issues/abc" は valid=false
    // 代わりに: URL モードのバリデーションは /github\.com\/.+\/issues\/\d+/ なので
    // "github.com/owner/repo/issues/0" → issueNum = 0 → if (!issueNum) のブランチ
    const input = screen.getByPlaceholderText(/github\.com\/owner/);
    await userEvent.type(input, "https://github.com/owner/repo/issues/0");
    await userEvent.click(screen.getByRole("button", { name: "受付キューに追加" }));

    await waitFor(() => {
      expect(screen.getByText(/Issue 番号を取得できません/)).toBeDefined();
    });
  });

  it("新規モードに切り替えられる", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));
    await userEvent.click(screen.getByRole("button", { name: "新規に起票" }));
    expect(screen.getByPlaceholderText(/検索結果にページネーション/)).toBeDefined();
  });

  it("新規モード: タイトル入力で送信ボタンが有効化される", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));
    await userEvent.click(screen.getByRole("button", { name: "新規に起票" }));

    const titleInput = screen.getByPlaceholderText(/検索結果にページネーション/);
    await userEvent.type(titleInput, "テストタイトル");

    const submitBtn = screen.getByRole("button", { name: "受付キューに追加" });
    expect(submitBtn).not.toHaveAttribute("disabled");
  });

  it("新規モード: 送信すると createIssue を呼び成功メッセージが出る (#137)", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));
    await userEvent.click(screen.getByRole("button", { name: "新規に起票" }));

    const titleInput = screen.getByPlaceholderText(/検索結果にページネーション/);
    await userEvent.type(titleInput, "テストタイトル");
    await userEvent.click(screen.getByRole("button", { name: "受付キューに追加" }));

    await waitFor(() => expect(api.createIssue).toHaveBeenCalled());
    expect(api.createIssue).toHaveBeenCalledWith(
      expect.objectContaining({ title: "テストタイトル" }),
    );
    expect(await screen.findByText(/o\/r#7 を起票しました/)).toBeDefined();
  });

  it("新規モード: 単一リポ構成では repo セレクタを出さない (#137)", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));
    await userEvent.click(screen.getByRole("button", { name: "新規に起票" }));
    // 単一リポなのでリポジトリ選択ボタンは出ない
    expect(screen.queryByText("リポジトリ")).toBeNull();
    const titleInput = screen.getByPlaceholderText(/検索結果にページネーション/);
    await userEvent.type(titleInput, "t");
    await userEvent.click(screen.getByRole("button", { name: "受付キューに追加" }));
    await waitFor(() => expect(api.createIssue).toHaveBeenCalled());
    expect(vi.mocked(api.createIssue).mock.calls[0][0].title).toBe("t");
  });

  it("新規モード: 複数リポ構成では owner/repo を選んで送る (#137)", async () => {
    vi.mocked(api.getRepositories).mockResolvedValue([REPO("o", "r1"), REPO("o", "r2")]);
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));
    await userEvent.click(screen.getByRole("button", { name: "新規に起票" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "o/r2" })).toBeDefined());
    await userEvent.click(screen.getByRole("button", { name: "o/r2" }));
    await userEvent.type(screen.getByPlaceholderText(/検索結果にページネーション/), "t");
    await userEvent.click(screen.getByRole("button", { name: "受付キューに追加" }));
    await waitFor(() => expect(api.createIssue).toHaveBeenCalled());
    expect(vi.mocked(api.createIssue).mock.calls[0][0].repo).toBe("o/r2");
  });

  it("新規モード: 本文 textarea に入力できる", async () => {
    render(<AddIssueButton />);
    await userEvent.click(screen.getByRole("button", { name: /Issue を投入/ }));
    await userEvent.click(screen.getByRole("button", { name: "新規に起票" }));

    const bodyInput = screen.getByPlaceholderText(/背景・やりたいこと/);
    await userEvent.type(bodyInput, "本文テスト");
    // クラッシュしないことを確認
  });
});
