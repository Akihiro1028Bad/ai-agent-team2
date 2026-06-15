"use client";

import { useCallback } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { ApproveButton } from "@/components/review/ApproveButton";

// フェーズバッジ
function PhaseBadge({ phase }: { phase: "approve" | "review" | "split" }) {
  const label = phase === "approve" ? "計画承認待ち" : phase === "split" ? "分割承認待ち" : "PRレビュー待ち";
  const color = phase === "review" ? "var(--color-cyan)" : "var(--color-amber)";
  return (
    <span
      className="rounded-md border px-2 py-0.5 font-mono text-[10px]"
      style={{ borderColor: `color-mix(in srgb, ${color} 40%, transparent)`, color }}
    >
      {label}
    </span>
  );
}

export default function ApprovalsPage() {
  /* v8 ignore next 3 -- usePolling callback is mocked in tests; api.getApprovals is tested separately */
  const { data, error, loading } = usePolling(
    useCallback((signal: AbortSignal) => api.getApprovals(signal), []),
    5000,
  );

  const rows = data ?? [];
  const initialLoading = loading && data === undefined;

  return (
    <div className="mx-auto max-w-[900px]">
      <ConnectionBanner error={error} />

      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">human gate</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">承認待ち</h1>
        </div>
        {data && (
          <p className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            {rows.length} 件が承認待ちです
          </p>
        )}
      </div>

      {/* 承認方法の注記 */}
      <div
        className="mt-4 rounded-xl border px-4 py-3 text-[12.5px]"
        style={{ borderColor: "var(--color-line)", color: "var(--color-ink-dim)", background: "var(--color-panel-2)" }}
      >
        計画承認待ち・分割承認待ちは、この画面の「承認」ボタンからそのまま承認できます。差し戻しは詳細画面から行ってください。PR レビュー待ちは詳細から差分を確認できます。
      </div>

      <div className="rise mt-6 flex flex-col gap-2.5" style={{ animationDelay: "60ms" }}>
        {initialLoading && (
          <div className="panel p-4 text-[13px]" style={{ color: "var(--color-ink-faint)" }}>
            読み込み中…
          </div>
        )}
        {!initialLoading && rows.length === 0 && (
          <div className="panel p-6 text-center text-[13px]" style={{ color: "var(--color-ink-faint)" }}>
            承認待ちの Issue はありません。
          </div>
        )}
        {rows.map((row, i) => (
          <div
            key={`${row.repo}#${row.issue}:${row.phase}`}
            className="panel rise flex flex-wrap items-center gap-3 p-4"
            style={{ animationDelay: `${80 + i * 40}ms` }}
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  href={`/issues/${row.issue}?repo=${encodeURIComponent(row.repo)}`}
                  className="font-mono text-[13px] font-medium hover:underline"
                  style={{ color: "var(--color-ink)" }}
                >
                  {row.repo}#{row.issue}
                </Link>
                <PhaseBadge phase={row.phase} />
                {row.prNumber != null && (
                  <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                    PR #{row.prNumber}
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                {row.updatedAt}
              </span>
              {/* 計画承認 (#146) / 分割承認 (#150) は画面から直接承認できる。PR レビュー待ちは詳細へ誘導。 */}
              {(row.phase === "approve" || row.phase === "split") && (
                <ApproveButton issue={row.issue} repo={row.repo} size="compact" />
              )}
              <Link
                href={`/issues/${row.issue}?repo=${encodeURIComponent(row.repo)}`}
                className="rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-colors"
                style={{ borderColor: "var(--color-line)", color: "var(--color-ink-dim)" }}
              >
                詳細を見る
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
