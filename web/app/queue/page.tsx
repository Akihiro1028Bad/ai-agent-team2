"use client";

import { useCallback } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ConnectionBanner } from "@/components/ConnectionBanner";

const PRIORITY_COLOR: Record<string, string> = {
  critical: "var(--color-rose)",
  high: "var(--color-amber)",
  normal: "var(--color-signal)",
  low: "var(--color-ink-faint)",
};

export default function QueuePage() {
  const { data, error, loading } = usePolling(
    useCallback((signal: AbortSignal) => api.getQueue(signal), []),
    3000,
  );

  const queued = data?.queued ?? [];
  const initialLoading = loading && data === undefined;

  return (
    <div className="mx-auto max-w-[900px]">
      <ConnectionBanner error={error} />

      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">task queue</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">実行キュー</h1>
        </div>
        {data && (
          <p className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            待機 {queued.length} · 実行中 {data.activeCount}/{data.maxTotal}
            {data.pausedCount > 0 ? ` · 一時停止 ${data.pausedCount}` : ""}
          </p>
        )}
      </div>

      <div className="rise mt-6 flex flex-col gap-2.5" style={{ animationDelay: "60ms" }}>
        {initialLoading && (
          <div className="panel p-4 text-[13px]" style={{ color: "var(--color-ink-faint)" }}>
            読み込み中…
          </div>
        )}
        {!initialLoading && queued.length === 0 && (
          <div className="panel p-6 text-center text-[13px]" style={{ color: "var(--color-ink-faint)" }}>
            待機中のタスクはありません。
          </div>
        )}
        {queued.map((row, i) => (
          <Link
            key={`${row.repo}#${row.issue}:${row.phase}`}
            href={`/issues/${row.issue}`}
            className="panel panel-hover flex items-center gap-3 p-3.5 rise"
            style={{ animationDelay: `${80 + i * 40}ms` }}
          >
            <span
              className="grid h-6 w-6 shrink-0 place-items-center rounded-md font-mono text-[10px] uppercase"
              style={{
                color: PRIORITY_COLOR[row.priorityLabel] ?? "var(--color-ink-dim)",
                background: `color-mix(in srgb, ${PRIORITY_COLOR[row.priorityLabel] ?? "var(--color-ink-dim)"} 14%, transparent)`,
              }}
              title={`priority: ${row.priorityLabel}`}
            >
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
                  {row.repo}#{row.issue}
                </span>
                <span className="rounded px-1.5 py-0.5 font-mono text-[10px]" style={{ color: "var(--color-ink-dim)", background: "var(--color-panel-2)" }}>
                  {row.phase}
                </span>
              </div>
              <p className="mt-0.5 truncate text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
                {row.reason}
              </p>
            </div>
            <span className="shrink-0 font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
              {row.enqueued}
            </span>
          </Link>
        ))}
      </div>

      <p className="mt-4 text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
        並べ替え・操作は #88 で接続予定
      </p>
    </div>
  );
}
