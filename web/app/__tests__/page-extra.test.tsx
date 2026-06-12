// app/page.tsx の未カバーブランチを補完する追加テスト
// Line 115: issue.needsHuman (waiting 状態の Issue)
// Line 156: ev.detail (detail あり activity イベント)

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { IssueSummary, IssueEvent } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/AddIssueButton", () => ({
  AddIssueButton: () => <button>+ Issue を投入</button>,
}));

vi.mock("@/components/ConnectionBanner", async () => {
  const actual = await vi.importActual<typeof import("@/components/ConnectionBanner")>("@/components/ConnectionBanner");
  return actual;
});

vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

import { usePolling } from "@/lib/hooks";
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

beforeEach(() => {
  vi.mocked(usePolling).mockReturnValue({ data: undefined, error: undefined, loading: true });
});

describe("Dashboard: 追加カバレッジ", () => {
  it("needsHuman のある issue では '承認・回答待ち' が表示される", async () => {
    const issues = [
      makeIssue({
        number: 1,
        status: "waiting",
        needsHuman: "承認・回答待ち",
      }),
    ];
    vi.mocked(usePolling)
      .mockReturnValueOnce({ data: issues, error: undefined, loading: false })
      .mockReturnValueOnce({ data: [], error: undefined, loading: false });
    render(<Dashboard />);
    await waitFor(() => expect(screen.getByText("承認・回答待ち")).toBeDefined());
  });

  it("needsHuman がない issue では '更新 N分前' が表示される", async () => {
    const issues = [makeIssue({ number: 2, status: "running", updated: "3分前" })];
    vi.mocked(usePolling)
      .mockReturnValueOnce({ data: issues, error: undefined, loading: false })
      .mockReturnValueOnce({ data: [], error: undefined, loading: false });
    render(<Dashboard />);
    await waitFor(() => expect(screen.getByText(/更新 3分前/)).toBeDefined());
  });

  it("detail のある activity イベントが表示される", async () => {
    const events: IssueEvent[] = [
      { id: "ev1", at: "1分前", kind: "ci", title: "CI 実行中", detail: "build-and-test 実行" },
    ];
    vi.mocked(usePolling)
      .mockReturnValueOnce({ data: [], error: undefined, loading: false })
      .mockReturnValueOnce({ data: events, error: undefined, loading: false });
    render(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText("CI 実行中")).toBeDefined();
      expect(screen.getByText("build-and-test 実行")).toBeDefined();
    });
  });

  it("activity が空のとき 'イベントはまだありません' が表示される", async () => {
    vi.mocked(usePolling)
      .mockReturnValueOnce({ data: [], error: undefined, loading: false })
      .mockReturnValueOnce({ data: [], error: undefined, loading: false });
    render(<Dashboard />);
    await waitFor(() => expect(screen.getByText("イベントはまだありません。")).toBeDefined());
  });

  it("loading が false かつ issue あり: initialLoading=false", async () => {
    const issues = [makeIssue({ number: 10, title: "マイ Issue" })];
    vi.mocked(usePolling)
      .mockReturnValueOnce({ data: issues, error: undefined, loading: false })
      .mockReturnValueOnce({ data: [], error: undefined, loading: false });
    render(<Dashboard />);
    await waitFor(() => expect(screen.queryByText("読み込み中…")).toBeNull());
  });
});
