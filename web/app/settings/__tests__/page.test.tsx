import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { RepoConfig } from "@/lib/api";

// PhaseModelConfig は独自に fetch するため stub 化
vi.mock("@/components/PhaseModelConfig", () => ({
  PhaseModelConfig: () => <div data-testid="phase-model-config" />,
}));

vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

import { usePolling } from "@/lib/hooks";
import SettingsPage from "@/app/settings/page";
import { ApiError } from "@/lib/api";

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
