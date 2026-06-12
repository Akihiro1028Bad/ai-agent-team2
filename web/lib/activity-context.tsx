"use client";

// Activity ポーリングの共有コンテキスト (#118-3)。
// ActivityProvider が単一の usePolling(getActivity(50), 5000) を実行し提供する。
// ダッシュボードと NotificationBell が同一 Context を参照し、二重フェッチを排除する。

import { createContext, useCallback, useContext } from "react";
import { api } from "@/lib/api";
import { usePolling, type PollingState } from "@/lib/hooks";
import type { IssueEvent } from "@/lib/types";

type ActivityState = Pick<PollingState<IssueEvent[]>, "data" | "error">;

const ActivityContext = createContext<ActivityState | null>(null);

/** Activity ポーリングを単一インスタンスで実行し子孫へ提供する。 */
export function ActivityProvider({ children }: { children: React.ReactNode }) {
  /* v8 ignore next -- usePolling callback mocked in tests; api.getActivity is tested separately */
  const fetcher = useCallback((signal: AbortSignal) => api.getActivity(50, signal), []);
  const { data, error } = usePolling(fetcher, 5000);
  return <ActivityContext.Provider value={{ data, error }}>{children}</ActivityContext.Provider>;
}

/**
 * Activity ポーリング結果を返す。
 * Provider 外で呼ばれた場合は throw する（既存の useReview 等の流儀に合わせる）。
 */
export function useActivity(): ActivityState {
  const ctx = useContext(ActivityContext);
  if (ctx === null) {
    throw new Error("useActivity は ActivityProvider の子孫で使用してください。");
  }
  return ctx;
}
