// lib/activity-context.tsx の 100% カバレッジテスト
// - ActivityProvider が usePolling を呼び子孫に data/error を提供する
// - useActivity が Provider 外で throw する
// - useActivity が Provider 内で正常に値を返す

import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ActivityProvider, useActivity } from "@/lib/activity-context";

// usePolling をモック（api.getActivity の実呼び出しを回避）
vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

// api もモック
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      getActivity: vi.fn(),
    },
  };
});

import { usePolling } from "@/lib/hooks";
import type { IssueEvent } from "@/lib/types";

function makeEvent(id: string): IssueEvent {
  return { id, at: "1分前", kind: "phase", title: `イベント ${id}` };
}

describe("ActivityProvider / useActivity", () => {
  it("Provider 内で useActivity が data を返す", async () => {
    const events = [makeEvent("ev1")];
    vi.mocked(usePolling).mockReturnValue({ data: events, error: undefined, loading: false });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <ActivityProvider>{children}</ActivityProvider>
    );
    const { result } = renderHook(() => useActivity(), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual(events));
    expect(result.current.error).toBeUndefined();
  });

  it("Provider 内で error を返す", async () => {
    const { ApiError } = await import("@/lib/api");
    const err = new ApiError(0, "接続不可");
    vi.mocked(usePolling).mockReturnValue({ data: undefined, error: err, loading: false });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <ActivityProvider>{children}</ActivityProvider>
    );
    const { result } = renderHook(() => useActivity(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe(err));
    expect(result.current.data).toBeUndefined();
  });

  it("Provider 外で useActivity を呼ぶと throw する", () => {
    expect(() => {
      renderHook(() => useActivity());
    }).toThrow("useActivity は ActivityProvider の子孫で使用してください。");
  });
});
