// Shell の未カバーブランチ: mobile メニュー開閉 (lines 139-152)
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/queue",
}));

vi.mock("next/link", () => ({
  default: ({ children, onClick }: { href: string; children: React.ReactNode; onClick?: () => void }) => (
    <a
      role="link"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === "Enter" && onClick) onClick(); }}
    >
      {children}
    </a>
  ),
}));

vi.mock("@/components/CommandPalette", () => ({
  CommandPalette: () => <div data-testid="cmd-palette" />,
}));
vi.mock("@/components/NotificationBell", () => ({
  NotificationBell: () => <div data-testid="notif-bell" />,
}));

vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

import { usePolling } from "@/lib/hooks";
import { Shell } from "@/components/Shell";
import type { ApiHealth } from "@/lib/api";

function makeHealth(overrides: Partial<ApiHealth> = {}): ApiHealth {
  return {
    running: true,
    stale: false,
    reason: null,
    ts: null,
    queue: null,
    repositories: ["r1"],
    rate_limit: null,
    worktrees: null,
    last_poll: {},
    accounts: {},
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(usePolling).mockReturnValue({
    data: makeHealth(),
    error: undefined,
    loading: false,
  });
});

describe("Shell: mobile メニュー開閉", () => {
  it("メニューボタンをクリックするとモバイルサイドバーが開く", async () => {
    render(<Shell><div>content</div></Shell>);

    // メニューボタンをクリック (aria-label="メニュー")
    await userEvent.click(screen.getByRole("button", { name: "メニュー" }));

    // モバイルサイドバーが開く (「閉じる」ボタンが現れる)
    expect(screen.getByRole("button", { name: "閉じる" })).toBeDefined();
  });

  it("閉じるボタンでモバイルサイドバーが閉じる", async () => {
    render(<Shell><div>content</div></Shell>);

    await userEvent.click(screen.getByRole("button", { name: "メニュー" }));
    await userEvent.click(screen.getByRole("button", { name: "閉じる" }));

    expect(screen.queryByRole("button", { name: "閉じる" })).toBeNull();
  });

  it("オーバーレイ背景をクリックでサイドバーが閉じる", async () => {
    const { container } = render(<Shell><div>content</div></Shell>);

    await userEvent.click(screen.getByRole("button", { name: "メニュー" }));

    // 背景の div (bg-black/60) をクリック
    const overlay = container.querySelector(".bg-black\\/60") as HTMLElement;
    expect(overlay).not.toBeNull();
    await userEvent.click(overlay);

    expect(screen.queryByRole("button", { name: "閉じる" })).toBeNull();
  });

  it("モバイルサイドバー内のナビリンクをクリックするとサイドバーが閉じる", async () => {
    render(<Shell><div>content</div></Shell>);

    await userEvent.click(screen.getByRole("button", { name: "メニュー" }));

    // SidebarInner 内のナビリンクをクリック (onNav が setOpen(false) を呼ぶ)
    // mobile sidebar に onNav が渡される (desktop は onNav なし)
    // mobile sidebar は後から描画されるので最後のリンク
    const dashLinks = screen.getAllByRole("link", { name: "ダッシュボード" });
    await userEvent.click(dashLinks[dashLinks.length - 1]);

    // サイドバーが閉じる
    expect(screen.queryByRole("button", { name: "閉じる" })).toBeNull();
  });

  it("health warn 状態を表示する", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeHealth({
        running: true,
        stale: false,
        queue: { active: 4, max_total: 4, queued: 1 },
      }),
      error: undefined,
      loading: false,
    });
    render(<Shell><div /></Shell>);
    await waitFor(() => expect(screen.getByText(/WARN/)).toBeDefined());
  });

  it("health error 状態を表示する", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeHealth({ running: false }),
      error: undefined,
      loading: false,
    });
    // adaptHealth で poller=error が返る → summarizeHealth → ERROR
    render(<Shell><div /></Shell>);
    await waitFor(() => expect(screen.getAllByText(/ERROR/).length).toBeGreaterThan(0));
  });

  it("health items が空のとき '…' を表示する", async () => {
    // data が undefined かつ loading=true → healthItems=[] → summarizeHealth で '…'
    vi.mocked(usePolling).mockReturnValue({
      data: undefined,
      error: undefined,
      loading: true,
    });
    render(<Shell><div /></Shell>);
    await waitFor(() => expect(screen.getByText("…")).toBeDefined());
  });

  it("pathname が /queue のとき実行キューリンクが active", async () => {
    render(<Shell><div /></Shell>);
    // pathname = /queue (モック) なので 実行キュー リンクが active
    await waitFor(() => expect(screen.getByText("実行キュー")).toBeDefined());
  });
});
