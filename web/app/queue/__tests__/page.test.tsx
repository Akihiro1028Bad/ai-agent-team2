import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import type { QueueView, QueueRow } from "@/lib/api";

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

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      postControl: vi.fn().mockResolvedValue(undefined),
    },
    actorForRepo: actual.actorForRepo,
  };
});

import { usePolling } from "@/lib/hooks";
import { api } from "@/lib/api";
import QueuePage from "@/app/queue/page";

function makeRow(overrides: Partial<QueueRow> = {}): QueueRow {
  return {
    repo: "owner/repo",
    issue: 10,
    phase: "implement",
    priority: 5,
    priorityLabel: "normal",
    enqueued: "2分前",
    reason: "待機中",
    ...overrides,
  };
}

function makeQueueView(overrides: Partial<QueueView> = {}): QueueView {
  return {
    running: true,
    reason: null,
    queued: [],
    activeCount: 0,
    pausedCount: 0,
    maxTotal: 4,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(usePolling).mockReturnValue({ data: undefined, error: undefined, loading: true });
  vi.mocked(api.postControl).mockResolvedValue(undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("QueuePage", () => {
  it("loading 中は '読み込み中…' が表示される", () => {
    render(<QueuePage />);
    expect(screen.getByText("読み込み中…")).toBeDefined();
  });

  it("queued が空のとき '待機中のタスクはありません' が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeQueueView({ queued: [] }),
      error: undefined,
      loading: false,
    });
    render(<QueuePage />);
    await waitFor(() => expect(screen.getByText("待機中のタスクはありません。")).toBeDefined());
  });

  it("queued があると row が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeQueueView({
        queued: [makeRow({ issue: 42, phase: "plan" })],
      }),
      error: undefined,
      loading: false,
    });
    render(<QueuePage />);
    await waitFor(() => expect(screen.getByText(/owner\/repo#42/)).toBeDefined());
    expect(screen.getByText("plan")).toBeDefined();
  });

  it("data がある場合、統計テキストが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeQueueView({
        queued: [],
        activeCount: 2,
        pausedCount: 1,
        maxTotal: 4,
      }),
      error: undefined,
      loading: false,
    });
    render(<QueuePage />);
    await waitFor(() => expect(screen.getByText(/実行中 2\/4/)).toBeDefined());
    // pausedCount > 0 → 一時停止 表示
    expect(screen.getByText(/一時停止 1/)).toBeDefined();
  });

  it("pausedCount=0 のとき一時停止の表示がない", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeQueueView({ activeCount: 1, pausedCount: 0, maxTotal: 3 }),
      error: undefined,
      loading: false,
    });
    render(<QueuePage />);
    await waitFor(() => expect(screen.queryByText(/一時停止/)).toBeNull());
  });

  it("優先度ボタンをクリックすると set_priority API が呼ばれる", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
      vi.mocked(usePolling).mockReturnValue({
        data: makeQueueView({
          queued: [makeRow({ issue: 5, priority: 5, phase: "implement" })],
        }),
        error: undefined,
        loading: false,
      });
      render(<QueuePage />);

      // priority=5 (normal) なので critical ボタンをクリック
      const criticalBtn = screen.getByTitle("優先度: critical");
      await user.click(criticalBtn);

      await waitFor(() => {
        expect(api.postControl).toHaveBeenCalledWith(
          expect.objectContaining({ action: "set_priority", priority: 1, issue: 5 }),
        );
      });

      // sentMsg が表示される
      await waitFor(() => {
        expect(screen.getByText(/優先度を変更しました/)).toBeDefined();
      });

      // タイムアウト
      await act(async () => {
        vi.advanceTimersByTime(4000);
      });
      expect(screen.queryByText(/優先度を変更しました/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("優先度変更 API 失敗でエラーメッセージが出る", async () => {
    vi.mocked(api.postControl).mockRejectedValue(new Error("fail"));
    vi.mocked(usePolling).mockReturnValue({
      data: makeQueueView({
        queued: [makeRow({ issue: 3, priority: 10, phase: "plan" })],
      }),
      error: undefined,
      loading: false,
    });
    render(<QueuePage />);

    const criticalBtn = screen.getByTitle("優先度: critical");
    await userEvent.click(criticalBtn);

    await waitFor(() => {
      expect(screen.getByText("優先度の変更に失敗しました（次回ポーリングで反映されます）")).toBeDefined();
    });
  });
});
