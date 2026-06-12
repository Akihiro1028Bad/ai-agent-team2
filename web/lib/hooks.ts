"use client";

// 読み取り API 用のクライアントフック (#86)。
// usePolling: 一定間隔でフェッチして {data, error, loading} を返す (ライブ更新)。
// useLogStream: SSE (EventSource) で agent.jsonl の行を購読する。

import { useEffect, useRef, useState } from "react";
import { ApiError, adaptAgentLog, streamUrl, type ApiAgentLogRecord } from "@/lib/api";
import type { LogLine } from "@/lib/logs";

export interface PollingState<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
}

/**
 * fetcher を intervalMs ごとに実行し、最新結果/エラー/初回ロード状態を返す。
 *
 * - エラー時も最後に取得した data は保持する (接続断でも画面を維持し、
 *   ConnectionBanner で「接続不可」を出す方針)。
 * - アンマウント / interval 変更時に in-flight リクエストを abort する。
 */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs = 5000,
): PollingState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError>();
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  // 最新の fetcher を effect から参照する (render 中の ref 更新は避ける)。
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async (): Promise<void> => {
      try {
        const result = await fetcherRef.current(controller.signal);
        if (cancelled) return;
        setData(result);
        setError(undefined);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof ApiError ? err : new ApiError(0, "不明なエラー"));
      } finally {
        if (!cancelled) {
          setLoading(false);
          timer = setTimeout(() => void tick(), intervalMs);
        }
      }
    };

    void tick();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs]);

  return { data, error, loading };
}

export interface LogStreamState {
  lines: LogLine[];
  connected: boolean;
}

/**
 * Issue の agent.jsonl を SSE で購読し、受信行を LogLine として蓄積する。
 *
 * issue が変わったらレンダー中に状態をリセットする (React 公認の
 * set-state-during-render パターン。effect 内同期 setState を避ける)。
 */
export function useLogStream(issue: number): LogStreamState {
  const [shownIssue, setShownIssue] = useState(issue);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [connected, setConnected] = useState(false);

  if (shownIssue !== issue) {
    setShownIssue(issue);
    setLines([]);
    setConnected(false);
  }

  useEffect(() => {
    const source = new EventSource(streamUrl(issue));

    source.addEventListener("agent", (ev: MessageEvent) => {
      try {
        const rec = JSON.parse(ev.data) as ApiAgentLogRecord;
        setLines((prev) => [...prev, adaptAgentLog(rec)]);
      } catch {
        // 壊れ行はスキップ (SSE は生行を流すため)。
      }
    });
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    return () => source.close();
  }, [issue]);

  return { lines, connected };
}
