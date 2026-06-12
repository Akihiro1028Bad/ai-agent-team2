"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { StatusPill, TypeTag } from "@/components/ui";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { ComingSoon } from "@/components/ComingSoon";
import type { IssueSummary } from "@/lib/types";

export default function TimelinePage() {
  const { data: issues, error, loading } = usePolling(
    (signal) => api.listIssues(signal),
  );

  return (
    <div className="mx-auto max-w-[1200px]">
      <ConnectionBanner error={error} />

      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">phase gantt</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">タイムライン</h1>
        </div>
      </div>

      {/* Issue 一覧（実データ） */}
      {loading && !issues && (
        <div className="rise mt-6 panel p-6 text-center font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
          読み込み中…
        </div>
      )}

      {issues && issues.length > 0 && (
        <div className="rise mt-6 panel p-5" style={{ animationDelay: "60ms" }}>
          <div className="flex flex-col gap-2.5">
            {issues.map((issue: IssueSummary) => (
              <Link
                key={`${issue.repo}#${issue.number}`}
                href={`/issues/${issue.number}`}
                className="group flex items-center gap-3"
              >
                <div className="flex w-[248px] shrink-0 items-center gap-2">
                  <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                    #{issue.number}
                  </span>
                  <span
                    className="truncate text-[12.5px] transition-colors group-hover:text-[var(--color-ink)]"
                    style={{ color: "var(--color-ink-dim)" }}
                  >
                    {issue.title}
                  </span>
                </div>
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <span
                    className="rounded px-2 py-0.5 font-mono text-[10px] uppercase"
                    style={{ color: "var(--color-ink-faint)", background: "var(--color-panel-2)" }}
                  >
                    {issue.phase}
                  </span>
                </div>
                <div className="hidden w-[180px] shrink-0 items-center justify-end gap-2 sm:flex">
                  <TypeTag type={issue.type} />
                  <StatusPill status={issue.status} />
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {issues && issues.length === 0 && (
        <div className="rise mt-6 panel p-6 text-center font-mono text-[12px]" style={{ color: "var(--color-ink-faint)", animationDelay: "60ms" }}>
          処理中の Issue はありません
        </div>
      )}

      {/* ガント（フェーズ時刻区間は API 未提供のため準備中） */}
      <div className="rise mt-6" style={{ animationDelay: "80ms" }}>
        <ComingSoon
          title="フェーズ別タイムライン"
          note="フェーズ区間の時刻は今後（events から再構成予定）"
        />
      </div>
    </div>
  );
}
