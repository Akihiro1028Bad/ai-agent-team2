import { renderHook, act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePolling, useLogStream } from "@/lib/hooks";
import { ApiError } from "@/lib/api";
import { FakeEventSource, installFakeEventSource } from "./_fakes";

// api をモック（useLogStream live=false 経路で api.getLogs を使う）
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      getLogs: vi.fn(),
    },
  };
});

import { api } from "@/lib/api";

// ── usePolling ────────────────────────────────────────────────────

describe("usePolling", () => {
  it("(a) 初回: loading=true → データ取得後 loading=false かつ data がセットされる", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 42 });
    const { result } = renderHook(() => usePolling(fetcher, 60_000));

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeUndefined();

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ value: 42 });
    expect(result.current.error).toBeUndefined();
  });

  it("(b) fetcher が reject したとき error がセットされ、直前に成功した data は保持される", async () => {
    const fetcher = vi.fn();
    // 1回目: 成功
    fetcher.mockResolvedValueOnce({ value: 99 });
    // 2回目: 失敗 (setTimeout が expire したあと呼ばれる)
    fetcher.mockRejectedValue(new ApiError(500, "サーバーエラー"));

    const { result } = renderHook(() => usePolling(fetcher, 1));

    // 初回成功を待つ
    await waitFor(() => expect(result.current.data).toEqual({ value: 99 }));

    // 2回目エラーを待つ (interval=1ms なのですぐ来る)
    await waitFor(() => expect(result.current.error).toBeDefined(), { timeout: 3000 });

    // data は保持される
    expect(result.current.data).toEqual({ value: 99 });
    expect(result.current.error).toBeInstanceOf(ApiError);
  });

  it("(c) アンマウントで AbortController が abort される", async () => {
    let capturedSignal: AbortSignal | null = null;
    const fetcher = vi.fn().mockImplementation((signal: AbortSignal) => {
      capturedSignal = signal;
      return Promise.resolve({ ok: true });
    });

    const { result, unmount } = renderHook(() => usePolling(fetcher, 60_000));
    await waitFor(() => expect(result.current.loading).toBe(false));

    unmount();
    expect(capturedSignal!.aborted).toBe(true);
  });

  it("interval 後に 2 回目のフェッチが実行される", async () => {
    const fetcher = vi.fn().mockResolvedValue({ n: 1 });
    renderHook(() => usePolling(fetcher, 1));

    // 初回フェッチ
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

    // 短い interval なので自然に 2 回目が来るまで待つ
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2), { timeout: 3000 });
  });
});

// ── useLogStream ──────────────────────────────────────────────────

describe("useLogStream", () => {
  let restore: () => void;

  beforeEach(() => {
    restore = installFakeEventSource();
    // live=false 経路のデフォルト
    vi.mocked(api.getLogs).mockResolvedValue([]);
  });
  afterEach(() => {
    restore();
    vi.restoreAllMocks();
  });

  /** ApiAgentLogRecord 形の JSON 文字列を生成する */
  function makeAgentData(text: string): string {
    return JSON.stringify({
      ts: "2026-06-12T01:02:03+00:00",
      phase: "implement",
      type: "text",
      text,
    });
  }

  it('(a) "agent" イベント受信で lines に行が増える', async () => {
    const { result } = renderHook(() => useLogStream(42));

    const src = FakeEventSource.instances[0];
    expect(src).toBeDefined();

    await act(async () => {
      src.emit("agent", makeAgentData("hello"));
    });

    expect(result.current.lines).toHaveLength(1);
    expect(result.current.lines[0].text).toBe("hello");
  });

  it("(b) onopen → connected=true, onerror → connected=false", async () => {
    const { result } = renderHook(() => useLogStream(42));
    const src = FakeEventSource.instances[0];

    await act(async () => {
      src.open();
    });
    expect(result.current.connected).toBe(true);

    await act(async () => {
      src.fail();
    });
    expect(result.current.connected).toBe(false);
  });

  it("(c) issue prop を変えると lines がリセットされる", async () => {
    const { result, rerender } = renderHook(({ issue }: { issue: number }) => useLogStream(issue), {
      initialProps: { issue: 1 },
    });

    // issue=1 で行を追加
    const src1 = FakeEventSource.instances[0];
    await act(async () => {
      src1.emit("agent", makeAgentData("issue 1 log"));
    });
    expect(result.current.lines).toHaveLength(1);

    // issue を変更 → lines リセット
    rerender({ issue: 2 });
    expect(result.current.lines).toHaveLength(0);
  });

  it("(d) アンマウントで close() が呼ばれる", async () => {
    const { unmount } = renderHook(() => useLogStream(42));
    const src = FakeEventSource.instances[0];
    expect(src.closed).toBe(false);

    unmount();
    expect(src.closed).toBe(true);
  });

  it("(e) live=false のとき EventSource を張らず api.getLogs を呼ぶ", async () => {
    const logLine = { t: "01:00:00", level: "agent" as const, source: "implement", text: "hist" };
    vi.mocked(api.getLogs).mockResolvedValue([logLine]);

    const { result } = renderHook(() => useLogStream(42, false));

    // EventSource インスタンスは生成されない
    expect(FakeEventSource.instances).toHaveLength(0);
    // connected は false 固定
    expect(result.current.connected).toBe(false);

    // getLogs の結果が lines にセットされる
    await waitFor(() => expect(result.current.lines).toHaveLength(1));
    expect(result.current.lines[0].text).toBe("hist");
  });

  it("(f) live=false のとき api.getLogs 失敗でも lines は空のまま (クラッシュしない)", async () => {
    vi.mocked(api.getLogs).mockRejectedValue(new Error("fetch failed"));

    const { result } = renderHook(() => useLogStream(42, false));

    // エラー後も lines は空、クラッシュしない
    await waitFor(() => expect(result.current.lines).toHaveLength(0));
    expect(result.current.connected).toBe(false);
  });

  it("(g) live が変わると lines がリセットされる", async () => {
    const { result, rerender } = renderHook(
      ({ issue, live }: { issue: number; live: boolean }) => useLogStream(issue, live),
      { initialProps: { issue: 1, live: true } },
    );

    // live=true で行を追加
    const src1 = FakeEventSource.instances[0];
    await act(async () => {
      src1.emit("agent", JSON.stringify({ ts: "2026-06-12T01:02:03+00:00", phase: "implement", type: "text", text: "live log" }));
    });
    expect(result.current.lines).toHaveLength(1);

    // live=false に変更 → lines リセット
    rerender({ issue: 1, live: false });
    expect(result.current.lines).toHaveLength(0);
  });
});
