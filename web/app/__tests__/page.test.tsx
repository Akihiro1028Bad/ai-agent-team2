import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { IssueSummary, IssueEvent } from "@/lib/types";

// next/link stub
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

// AddIssueButton stub (副作用を避ける)
vi.mock("@/components/AddIssueButton", () => ({
  AddIssueButton: () => <button>+ Issue を投入</button>,
}));

// ConnectionBanner stub (実実装を使ってもよいが副作用を最小化)
vi.mock("@/components/ConnectionBanner", async () => {
  const actual = await vi.importActual<typeof import("@/components/ConnectionBanner")>("@/components/ConnectionBanner");
  return actual;
});

// usePolling をモック
vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

// useActivity をモック（NotificationBell は別モジュールで使うが、page.tsx も直接使う）
vi.mock("@/lib/activity-context", () => ({
  useActivity: vi.fn(),
}));

import { usePolling } from "@/lib/hooks";
import { useActivity } from "@/lib/activity-context";
import { ApiError } from "@/lib/api";
import Dashboard from "@/app/page";

function makeIssue(overrides: Partial<IssueSummary> & { number: number }): IssueSummary {
  return {
    repo: "owner/repo",
    title: `Issue ${overrides.number}`,
    type: "feature-m",
    phase: "implement",
    status: "running",
    costUsd: 0,
    updated: "1分前",
    ...overrides,
  };
}

function makeEvent(id: string): IssueEvent {
  return { id, at: "1分前", kind: "phase", title: `イベント ${id}` };
}

beforeEach(() => {
  // デフォルト: issues loading 中
  vi.mocked(usePolling).mockReturnValue({ data: undefined, error: undefined, loading: true });
  // activity: デフォルト空
  vi.mocked(useActivity).mockReturnValue({ data: [], error: undefined });
});

describe("Dashboard (app/page.tsx)", () => {
  it("loading 中は '読み込み中…' が表示される", () => {
    vi.mocked(usePolling).mockReturnValue({ data: undefined, error: undefined, loading: true });
    render(<Dashboard />);
    expect(screen.getByText("読み込み中…")).toBeDefined();
  });

  it("issues が空の場合 '処理中の Issue はありません。' が表示される", () => {
    vi.mocked(usePolling).mockReturnValue({ data: [], error: undefined, loading: false });
    render(<Dashboard />);
    expect(screen.getByText("処理中の Issue はありません。")).toBeDefined();
  });

  it("issues が存在すると Issue タイトルが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeIssue({ number: 42, title: "テスト Issue タイトル" })],
      error: undefined,
      loading: false,
    });
    render(<Dashboard />);
    await waitFor(() => expect(screen.getByText("テスト Issue タイトル")).toBeDefined());
  });

  it("API エラー時に ConnectionBanner のアラートが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({ data: undefined, error: new ApiError(0, "接続不可"), loading: false });
    render(<Dashboard />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
  });

  it("stats に running 件数・waiting 件数が正しく表示される", async () => {
    const issues = [
      makeIssue({ number: 1, status: "running" }),
      makeIssue({ number: 2, status: "running" }),
      makeIssue({ number: 3, status: "waiting" }),
    ];
    vi.mocked(usePolling).mockReturnValue({ data: issues, error: undefined, loading: false });
    render(<Dashboard />);
    // 稼働中: 2, 人間待ち: 1
    await waitFor(() => {
      expect(screen.getByText("2")).toBeDefined();
      expect(screen.getByText("1")).toBeDefined();
    });
  });

  it("アクティビティがあると最初のイベントタイトルが描画される", async () => {
    const events: IssueEvent[] = [makeEvent("ev1")];
    vi.mocked(usePolling).mockReturnValue({ data: [], error: undefined, loading: false });
    vi.mocked(useActivity).mockReturnValue({ data: events, error: undefined });
    render(<Dashboard />);
    await waitFor(() => expect(screen.getByText("イベント ev1")).toBeDefined());
  });
});
