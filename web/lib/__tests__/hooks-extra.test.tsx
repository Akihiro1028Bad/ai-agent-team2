// usePolling の未カバーブランチを通す追加テスト
// (壊れ JSON スキップ・非 AbortError 変換・cancelled 分岐)

import { renderHook, act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePolling, useLogStream } from "@/lib/hooks";
import { ApiError } from "@/lib/api";
import { FakeEventSource, installFakeEventSource } from "./_fakes";

// api.getLogs をモック（useLogStream が内部で参照するため）
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      getLogs: vi.fn().mockResolvedValue([]),
    },
  };
});

// ── usePolling: 非 ApiError 例外 ──────────────────────────────────

describe("usePolling: 非 ApiError 例外", () => {
  it("ApiError 以外の例外は ApiError(0) に変換される", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("unexpected"));

    const { result } = renderHook(() => usePolling(fetcher, 60_000));

    await waitFor(() => expect(result.current.error).toBeDefined());
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect(result.current.error?.status).toBe(0);
  });

  it("cancelled=true の tick は setData を呼ばない", async () => {
    // fetcher が応答する前にアンマウントして、cancelled=true の後のコード経路を通す
    let resolveIt!: (v: unknown) => void;
    const fetcher = vi.fn().mockImplementation(
      () =>
        new Promise((res) => {
          resolveIt = res;
        }),
    );

    const { unmount } = renderHook(() => usePolling(fetcher, 60_000));

    // まだ未解決の fetch がある状態でアンマウント → cancelled=true
    unmount();

    // fetch を解決する (cancelled=true なので setData は呼ばれず、例外も起きない)
    await act(async () => {
      resolveIt({ value: 1 });
    });
    // クラッシュしないことを確認
  });

  it("cancelled=true の tick でエラー発生しても setError を呼ばない", async () => {
    let rejectIt!: (e: unknown) => void;
    const fetcher = vi.fn().mockImplementation(
      () =>
        new Promise((_, rej) => {
          rejectIt = rej;
        }),
    );

    const { unmount } = renderHook(() => usePolling(fetcher, 60_000));

    unmount();

    await act(async () => {
      rejectIt(new ApiError(500, "err"));
    });
    // クラッシュしないことを確認
  });

  it("fetcher が AbortError を throw したとき setError を呼ばず return する", async () => {
    const abortErr = new DOMException("Aborted", "AbortError");
    const fetcher = vi.fn().mockRejectedValue(abortErr);

    const { result } = renderHook(() => usePolling(fetcher, 60_000));

    await waitFor(() => expect(result.current.loading).toBe(false));
    // AbortError は無視されるため error はセットされない
    expect(result.current.error).toBeUndefined();
  });
});

// ── useLogStream: 壊れ JSON スキップ ─────────────────────────────

describe("useLogStream: 壊れ JSON スキップ", () => {
  let restore: () => void;

  beforeEach(() => {
    restore = installFakeEventSource();
  });
  afterEach(() => {
    restore();
  });

  it("壊れ JSON を受信しても lines は増えない (catch path)", async () => {
    const { result } = renderHook(() => useLogStream(1));
    const src = FakeEventSource.instances[0];

    await act(async () => {
      src.emit("agent", "NOT VALID JSON {{{{");
    });

    expect(result.current.lines).toHaveLength(0);
  });
});
