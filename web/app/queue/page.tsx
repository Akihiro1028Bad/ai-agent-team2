"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { api, actorForRepo, type ControlRequest } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import type { QueueRow } from "@/lib/api";

const PRIORITY_COLOR: Record<string, string> = {
  critical: "var(--color-rose)",
  high: "var(--color-amber)",
  normal: "var(--color-signal)",
  low: "var(--color-ink-faint)",
};

const PRIORITY_OPTIONS: { value: number; label: string }[] = [
  { value: 1, label: "critical" },
  { value: 2, label: "high" },
  { value: 5, label: "normal" },
  { value: 10, label: "low" },
];

function PrioritySelector({
  row,
  onSent,
}: {
  row: QueueRow;
  onSent: (msg: string) => void;
}) {
  const [sending, setSending] = useState(false);

  const handleChange = async (priority: number) => {
    setSending(true);
    try {
      const req: ControlRequest = {
        action: "set_priority",
        issue: row.issue,
        phase: row.phase,
        priority,
        actor: actorForRepo(row.repo),
      };
      await api.postControl(req);
      onSent(`#${row.issue} の優先度を変更しました（次回ポーリングで反映）`);
    } catch {
      onSent("優先度の変更に失敗しました");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex items-center gap-1.5">
      {PRIORITY_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          disabled={sending || row.priority === opt.value}
          onClick={() => void handleChange(opt.value)}
          title={`優先度: ${opt.label}`}
          className="rounded border px-2 py-0.5 font-mono text-[10px] transition-colors disabled:opacity-40"
          /* v8 ignore start */
          style={{
            borderColor: row.priority === opt.value
              ? `color-mix(in srgb, ${PRIORITY_COLOR[opt.label] ?? "var(--color-ink-dim)"} 60%, transparent)`
              : "var(--color-line)",
            color: row.priority === opt.value
              ? PRIORITY_COLOR[opt.label] ?? "var(--color-ink-dim)"
              : "var(--color-ink-faint)",
            background: row.priority === opt.value
              ? `color-mix(in srgb, ${PRIORITY_COLOR[opt.label] ?? "var(--color-ink-dim)"} 14%, transparent)`
              : "transparent",
          }}
          /* v8 ignore stop */
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function QueuePage() {
  /* v8 ignore next 3 -- usePolling callback is mocked in tests; api.getQueue is tested separately */
  const { data, error, loading } = usePolling(
    useCallback((signal: AbortSignal) => api.getQueue(signal), []),
    3000,
  );

  // 送信済みメッセージ（楽観更新はせず次回ポーリングで反映する旨を表示）
  const [sentMsg, setSentMsg] = useState<string | null>(null);

  const handleSent = useCallback((msg: string) => {
    setSentMsg(msg);
    setTimeout(() => setSentMsg(null), 3500);
  }, []);

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

      {sentMsg && (
        <div className="mt-3 rounded-lg border px-4 py-2 text-[12.5px]" style={{ borderColor: "var(--color-cyan)", color: "var(--color-cyan)", background: "color-mix(in srgb, var(--color-cyan) 8%, transparent)" }}>
          {sentMsg}（次回ポーリングで反映されます）
        </div>
      )}

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
          <div
            key={`${row.repo}#${row.issue}:${row.phase}`}
            className="panel rise flex flex-col gap-2 p-3.5"
            style={{ animationDelay: `${80 + i * 40}ms` }}
          >
            <div className="flex items-center gap-3">
              <span
                className="grid h-6 w-6 shrink-0 place-items-center rounded-md font-mono text-[10px] uppercase"
                /* v8 ignore start */
                style={{
                  color: PRIORITY_COLOR[row.priorityLabel] ?? "var(--color-ink-dim)",
                  background: `color-mix(in srgb, ${PRIORITY_COLOR[row.priorityLabel] ?? "var(--color-ink-dim)"} 14%, transparent)`,
                }}
                /* v8 ignore stop */
                title={`priority: ${row.priorityLabel}`}
              >
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Link
                    href={`/issues/${row.issue}`}
                    className="font-mono text-[12px] hover:underline"
                    style={{ color: "var(--color-ink-faint)" }}
                  >
                    {row.repo}#{row.issue}
                  </Link>
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
            </div>
            {/* 優先度変更 */}
            <div className="flex items-center gap-2 pl-9">
              <span className="font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>優先度:</span>
              <PrioritySelector row={row} onSent={handleSent} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
