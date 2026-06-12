// NotificationBell の未カバーブランチを補完する追加テスト
// - gate/error 通知のリンクをクリック → markOne + setOpen(false)
// - done 通知 (href なし) は div でラップされる
// - 既読状態で localStorage が壊れている場合

import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationBell } from "@/components/NotificationBell";
import type { IssueEvent } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    onClick,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    onClick?: () => void;
    className?: string;
  }) => (
    <a href={href} onClick={onClick} className={className}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

import { usePolling } from "@/lib/hooks";

function makeEvent(overrides: Partial<IssueEvent> & { id: string; kind: IssueEvent["kind"]; title: string }): IssueEvent {
  return {
    at: "1分前",
    detail: undefined,
    cost: undefined,
    ...overrides,
  };
}

const gateEvent = makeEvent({ id: "ev-gate", kind: "gate", title: "承認待ち" });
const errorEvent = makeEvent({ id: "ev-error", kind: "error", title: "エラー", detail: "詳細あり" });
// done パターンにマッチするイベント (kind=phase, title は done パターンにマッチ)
const doneEvent = makeEvent({ id: "ev-done", kind: "phase", title: "処理完了 done" });
// info 相当 (kind が gate/error でなく done パターンにもマッチしない)
const infoEvent = makeEvent({ id: "ev-info", kind: "comment", title: "コメントあり" });

beforeEach(() => {
  localStorage.clear();
  vi.mocked(usePolling).mockReturnValue({ data: [], error: undefined, loading: false });
});
afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("NotificationBell: 追加カバレッジ", () => {
  it("gate 通知のリンクをクリックすると markOne + close", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [gateEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);

    // ベルを開く
    await userEvent.click(screen.getByRole("button", { name: /通知/ }));

    // gate → /approvals リンクをクリック
    const link = screen.getByRole("link");
    await act(async () => {
      await userEvent.click(link);
    });

    // ドロップダウンが閉じる
    expect(screen.queryByText("すべて既読にする")).toBeNull();
  });

  it("done 種別の通知はリンクでなく div でラップされる", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [doneEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /通知/ }));

    // done 通知は href が undefined → Link ではなく div
    // screen.queryByRole("link") が null であることを確認
    expect(screen.queryByRole("link")).toBeNull();
    // タイトルは表示されている
    expect(screen.getByText("処理完了 done")).toBeDefined();
  });

  it("通知の body (detail) が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [errorEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);
    await userEvent.click(screen.getByRole("button", { name: /通知/ }));
    expect(screen.getByText("詳細あり")).toBeDefined();
  });

  it("外部クリックでドロップダウンが閉じる", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [gateEvent],
      error: undefined,
      loading: false,
    });
    render(
      <div>
        <NotificationBell />
        <button data-testid="outside">outside</button>
      </div>,
    );

    await userEvent.click(screen.getByRole("button", { name: /通知/ }));
    expect(screen.getByText("すべて既読にする")).toBeDefined();

    // 外部要素をクリック
    await userEvent.click(screen.getByTestId("outside"));
    expect(screen.queryByText("すべて既読にする")).toBeNull();
  });

  it("localStorage が壊れていても loadReadIds は空 Set を返す", () => {
    // 壊れた JSON を設定
    localStorage.setItem("notif-read", "INVALID JSON");
    vi.mocked(usePolling).mockReturnValue({
      data: [gateEvent],
      error: undefined,
      loading: false,
    });
    // エラーなく描画される
    render(<NotificationBell />);
    // 全件が未読扱い
    expect(screen.getByText("1")).toBeDefined();
  });

  it("localStorage の notif-read が配列でない JSON のとき空 Set を返す", () => {
    localStorage.setItem("notif-read", JSON.stringify({ not: "array" }));
    vi.mocked(usePolling).mockReturnValue({
      data: [gateEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);
    // 全件が未読扱い
    expect(screen.getByText("1")).toBeDefined();
  });

  it("kind が info (gate/error/done どれでもない) は通知に含まれない", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [infoEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);
    // 0 件なのでバッジなし
    expect(screen.queryByText("1")).toBeNull();
  });

  it("error が発生して data が空のとき「通知を取得できませんでした」を表示する", async () => {
    const { ApiError } = await import("@/lib/api");
    vi.mocked(usePolling).mockReturnValue({
      data: undefined,
      error: new ApiError(0, "offline"),
      loading: false,
    });
    render(<NotificationBell />);
    await userEvent.click(screen.getByRole("button", { name: /通知/ }));
    expect(screen.getByText("通知を取得できませんでした")).toBeDefined();
  });

  it("既読 id を markOne で個別追加できる", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [gateEvent, errorEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);

    // ベルを開く
    await userEvent.click(screen.getByRole("button", { name: /通知/ }));

    // gate リンクをクリック → markOne(ev-gate) → close
    const links = screen.getAllByRole("link");
    await act(async () => {
      await userEvent.click(links[0]);
    });

    // ドロップダウンが閉じているので再度開く
    await userEvent.click(screen.getByRole("button", { name: /通知/ }));

    // gateEvent が既読 → 未読は errorEvent の 1 件
    expect(screen.getByText("1")).toBeDefined();
  });
});
