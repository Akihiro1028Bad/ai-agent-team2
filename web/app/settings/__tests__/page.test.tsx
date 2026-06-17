import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { RepoConfig } from "@/lib/api";

// PhaseModelConfig は独自に fetch するため stub 化
vi.mock("@/components/PhaseModelConfig", () => ({
  PhaseModelConfig: () => <div data-testid="phase-model-config" />,
}));

vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

// api: 書き込み系のみ差し替え (#138)
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      createRepository: vi.fn().mockResolvedValue(undefined),
      deleteRepository: vi.fn().mockResolvedValue(undefined),
    },
  };
});

import { usePolling } from "@/lib/hooks";
import SettingsPage from "@/app/settings/page";
import { ApiError, api } from "@/lib/api";

function repo(overrides: Partial<RepoConfig> = {}): RepoConfig {
  return { owner: "o", repo: "r", label: "ai-agent", baseBranch: "main", ...overrides };
}

beforeEach(() => {
  vi.mocked(usePolling).mockReturnValue({ data: undefined, error: undefined, loading: true });
});

describe("SettingsPage 監視リポジトリ (#144)", () => {
  it("実 config の repos を表示する", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [repo({ owner: "myorg", repo: "frontend", baseBranch: "develop", account: "acc" })],
      error: undefined,
      loading: false,
    });
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByText("frontend")).toBeDefined());
    expect(screen.getByText(/base:develop/)).toBeDefined();
    expect(screen.getByText(/account:acc/)).toBeDefined();
  });

  it("repos が空のとき未設定メッセージを出す", async () => {
    vi.mocked(usePolling).mockReturnValue({ data: [], error: undefined, loading: false });
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByText(/監視リポジトリは未設定です/)).toBeDefined());
  });

  it("取得失敗時はエラー表示", async () => {
    vi.mocked(usePolling).mockReturnValue({ data: undefined, error: new ApiError(0, "x"), loading: false });
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByText(/設定の取得に失敗しました/)).toBeDefined());
  });

  it("モックの bigban / ai-agent-team2 を表示しない（実config接続の確認）", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [repo({ owner: "myorg", repo: "only-real" })],
      error: undefined,
      loading: false,
    });
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByText("only-real")).toBeDefined());
    expect(screen.queryByText("bigban")).toBeNull();
  });
});

describe("SettingsPage リポジトリ追加/削除 (#138)", () => {
  beforeEach(() => {
    vi.mocked(usePolling).mockReturnValue({ data: [], error: undefined, loading: false });
    vi.mocked(api.createRepository).mockResolvedValue(undefined);
    vi.mocked(api.deleteRepository).mockResolvedValue(undefined);
  });

  it("フォームから追加すると createRepository を呼び再起動案内を出す", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);
    await user.type(screen.getByPlaceholderText("owner"), "myorg");
    await user.type(screen.getByPlaceholderText("repo"), "newapp");
    await user.click(screen.getByRole("button", { name: "+ 追加" }));

    await waitFor(() => expect(api.createRepository).toHaveBeenCalled());
    expect(api.createRepository).toHaveBeenCalledWith(
      expect.objectContaining({ owner: "myorg", repo: "newapp" }),
    );
    expect(await screen.findByText(/myorg\/newapp を追加しました/)).toBeDefined();
  });

  it("owner/repo 未入力では追加ボタンが disabled", async () => {
    render(<SettingsPage />);
    expect(screen.getByRole("button", { name: "+ 追加" })).toHaveProperty("disabled", true);
  });

  it("削除ボタンで deleteRepository を呼ぶ", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [repo({ owner: "myorg", repo: "old" })],
      error: undefined,
      loading: false,
    });
    const user = userEvent.setup();
    render(<SettingsPage />);
    await user.click(screen.getByRole("button", { name: "myorg/old を削除" }));
    await waitFor(() => expect(api.deleteRepository).toHaveBeenCalledWith("myorg", "old"));
  });

  it("追加失敗時はエラーメッセージを表示", async () => {
    vi.mocked(api.createRepository).mockRejectedValueOnce(new ApiError(409, "dup"));
    const user = userEvent.setup();
    render(<SettingsPage />);
    await user.type(screen.getByPlaceholderText("owner"), "o");
    await user.type(screen.getByPlaceholderText("repo"), "r");
    await user.click(screen.getByRole("button", { name: "+ 追加" }));
    expect(await screen.findByText(/追加に失敗しました/)).toBeDefined();
  });
});
