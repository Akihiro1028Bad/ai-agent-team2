import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { ApiHealth } from "@/lib/api";

// next/navigation をスタブ化
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

// next/link をスタブ化
vi.mock("next/link", () => ({
  default: ({ href, children, onClick }: { href: string; children: React.ReactNode; onClick?: () => void }) => (
    <a href={href} onClick={onClick}>{children}</a>
  ),
}));

// CommandPalette / NotificationBell は副作用が大きいのでスタブ化
vi.mock("@/components/CommandPalette", () => ({
  CommandPalette: () => <div data-testid="cmd-palette" />,
}));
vi.mock("@/components/NotificationBell", () => ({
  NotificationBell: () => <div data-testid="notif-bell" />,
}));

// usePolling をモック
vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

import { usePolling } from "@/lib/hooks";
import { Shell } from "@/components/Shell";

function makeHealth(overrides: Partial<ApiHealth> = {}): ApiHealth {
  return {
    running: true,
    stale: false,
    reason: null,
    ts: null,
    queue: null,
    repositories: ["owner/repo"],
    rate_limit: null,
    worktrees: null,
    last_poll: {},
    accounts: {},
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(usePolling).mockReturnValue({ data: undefined, error: undefined, loading: true });
});

describe("Shell", () => {
  it("children が描画される", () => {
    render(
      <Shell>
        <div>メインコンテンツ</div>
      </Shell>,
    );
    expect(screen.getByText("メインコンテンツ")).toBeDefined();
  });

  it("health が running=true のとき RUNNING と表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeHealth({ running: true, stale: false }),
      error: undefined,
      loading: false,
    });
    render(<Shell><div /></Shell>);
    await waitFor(() => expect(screen.getByText("RUNNING")).toBeDefined());
  });

  it("health が running=false のとき STOPPED と表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeHealth({ running: false, stale: false }),
      error: undefined,
      loading: false,
    });
    render(<Shell><div /></Shell>);
    await waitFor(() => expect(screen.getByText("STOPPED")).toBeDefined());
  });

  it("error かつ data=undefined のとき OFFLINE と表示される", async () => {
    const { ApiError } = await import("@/lib/api");
    vi.mocked(usePolling).mockReturnValue({
      data: undefined,
      error: new ApiError(0, "接続不可"),
      loading: false,
    });
    render(<Shell><div /></Shell>);
    // OFFLINE は topbar と sidebar health の 2 箇所に出る
    await waitFor(() => expect(screen.getAllByText("OFFLINE").length).toBeGreaterThan(0));
  });

  it("repos 数が header に表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeHealth({ repositories: ["r1", "r2"] }),
      error: undefined,
      loading: false,
    });
    render(<Shell><div /></Shell>);
    await waitFor(() => expect(screen.getByText(/2 repos/)).toBeDefined());
  });
});
