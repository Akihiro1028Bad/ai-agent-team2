import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { ApprovalRow } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/ConnectionBanner", async () => {
  const actual = await vi.importActual<typeof import("@/components/ConnectionBanner")>("@/components/ConnectionBanner");
  return actual;
});

vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

import { usePolling } from "@/lib/hooks";
import ApprovalsPage from "@/app/approvals/page";
import { ApiError } from "@/lib/api";

function makeRow(overrides: Partial<ApprovalRow> = {}): ApprovalRow {
  return {
    repo: "owner/repo",
    issue: 10,
    phase: "approve",
    prNumber: null,
    updatedAt: "3分前",
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(usePolling).mockReturnValue({ data: undefined, error: undefined, loading: true });
});

describe("ApprovalsPage", () => {
  it("loading 中は '読み込み中…' が表示される", () => {
    render(<ApprovalsPage />);
    expect(screen.getByText("読み込み中…")).toBeDefined();
  });

  it("rows が空のとき '承認待ちの Issue はありません' が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByText("承認待ちの Issue はありません。")).toBeDefined());
  });

  it("rows がある場合、repo#issue が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeRow({ issue: 42, repo: "owner/repo" })],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByText("owner/repo#42")).toBeDefined());
  });

  it("phase=approve のとき '計画承認待ち' バッジが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeRow({ phase: "approve" })],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByText("計画承認待ち")).toBeDefined());
  });

  it("phase=review のとき 'PRレビュー待ち' バッジが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeRow({ phase: "review" })],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByText("PRレビュー待ち")).toBeDefined());
  });

  it("prNumber がある場合 PR # が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeRow({ prNumber: 55 })],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByText("PR #55")).toBeDefined());
  });

  it("prNumber が null の場合 PR # は表示されない", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeRow({ prNumber: null })],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.queryByText(/PR #/)).toBeNull());
  });

  it("data がある場合、件数テキストが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeRow(), makeRow({ issue: 11 })],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByText("2 件が承認待ちです")).toBeDefined());
  });

  it("API エラー時に ConnectionBanner が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: undefined,
      error: new ApiError(0, "接続不可"),
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
  });

  it("updatedAt が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeRow({ updatedAt: "5分前" })],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByText("5分前")).toBeDefined());
  });

  it("phase=approve の行に承認ボタンが出る (#146)", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeRow({ phase: "approve" })],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "承認" })).toBeDefined());
  });

  it("phase=review の行には承認ボタンを出さない (#146)", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [makeRow({ phase: "review" })],
      error: undefined,
      loading: false,
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByText("PRレビュー待ち")).toBeDefined());
    expect(screen.queryByRole("button", { name: "承認" })).toBeNull();
  });
});
