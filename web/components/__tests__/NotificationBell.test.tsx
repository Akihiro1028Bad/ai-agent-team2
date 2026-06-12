import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationBell } from "@/components/NotificationBell";
import type { IssueEvent } from "@/lib/types";

// next/link をシンプルな <a> にスタブ化する
vi.mock("next/link", () => ({
  default: ({ href, children, onClick }: { href: string; children: React.ReactNode; onClick?: () => void }) => (
    <a href={href} onClick={onClick}>{children}</a>
  ),
}));

// usePolling を差し替えてテストデータを注入する
vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

import { usePolling } from "@/lib/hooks";
import { ApiError } from "@/lib/api";

/** gate/error/done イベントのサンプル */
function makeEvent(overrides: Partial<IssueEvent> & { id: string; kind: IssueEvent["kind"]; title: string }): IssueEvent {
  return {
    at: "1分前",
    detail: undefined,
    cost: undefined,
    ...overrides,
  };
}

const gateEvent = makeEvent({ id: "ev-gate", kind: "gate", title: "承認待ち" });
const errorEvent = makeEvent({ id: "ev-error", kind: "error", title: "エラー発生" });
const doneEvent = makeEvent({ id: "ev-done", kind: "phase", title: "done 完了" }); // DONE_PATTERN にマッチ

beforeEach(() => {
  localStorage.clear();
  vi.mocked(usePolling).mockReturnValue({ data: [], error: undefined, loading: false });
});
afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("NotificationBell", () => {
  it("通知がないとき未読バッジは表示されない", () => {
    render(<NotificationBell />);
    // aria-label が「未読 0 件」
    expect(screen.getByRole("button", { name: /通知（未読 0 件）/ })).toBeDefined();
    // バッジ数字なし
    expect(screen.queryByText("0")).toBeNull();
  });

  it("gate/error イベントがあると未読バッジが表示される", () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [gateEvent, errorEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);
    // 未読バッジに数字が出る
    expect(screen.getByText("2")).toBeDefined();
  });

  it("ベルをクリックすると通知リストが開く", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [gateEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /通知/ }));
    expect(screen.getByText("承認待ち")).toBeDefined();
  });

  it("「すべて既読にする」で未読バッジが消える", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [gateEvent, errorEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);

    // ベルを開く
    await userEvent.click(screen.getByRole("button", { name: /通知/ }));
    // すべて既読
    await act(async () => {
      await userEvent.click(screen.getByText("すべて既読にする"));
    });

    // バッジが消える (localStorage に保存され、バッジ数 0)
    expect(screen.queryByText("2")).toBeNull();
  });

  it("done パターンのイベントも通知に含まれる", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: [doneEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);
    await userEvent.click(screen.getByRole("button", { name: /通知/ }));
    expect(screen.getByText("done 完了")).toBeDefined();
  });

  it("エラー時かつ通知ゼロのとき取得失敗メッセージを出す", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: undefined,
      error: new ApiError(0, "失敗"),
      loading: false,
    });
    render(<NotificationBell />);
    await userEvent.click(screen.getByRole("button", { name: /通知/ }));
    expect(screen.getByText("通知を取得できませんでした")).toBeDefined();
  });

  it("localStorage 既読済み id は未読に含まれない", () => {
    localStorage.setItem("notif-read", JSON.stringify([gateEvent.id]));
    vi.mocked(usePolling).mockReturnValue({
      data: [gateEvent, errorEvent],
      error: undefined,
      loading: false,
    });
    render(<NotificationBell />);
    // gateEvent は既読済み → 未読は errorEvent の 1 件
    expect(screen.getByText("1")).toBeDefined();
  });
});
