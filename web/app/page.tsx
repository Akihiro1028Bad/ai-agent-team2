"use client";

import { useCallback } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { useActivity } from "@/lib/activity-context";
import { Money, StatusPill, TypeTag, eventIcon, phaseAccent } from "@/components/ui";
import { PhaseRail } from "@/components/PhaseRail";
import { AddIssueButton } from "@/components/AddIssueButton";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { IconArrow } from "@/components/icons";

function Stat({ label, value, accent, sub }: { label: string; value: string; accent: string; sub?: string }) {
  return (
    <div className="panel panel-hover p-4">
      <div className="eyebrow">{label}</div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="font-mono text-3xl font-semibold tnum" style={{ color: accent }}>{value}</span>
        {sub && <span className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>{sub}</span>}
      </div>
    </div>
  );
}

export default function Dashboard() {
  /* v8 ignore next -- usePolling callback is mocked in tests; api.listIssues is tested separately */
  const issuesState = usePolling(useCallback((signal: AbortSignal) => api.listIssues(signal), []), 5000);
  const activityCtx = useActivity();

  const issues = issuesState.data ?? [];
  const activity = (activityCtx.data ?? []).slice(0, 40);
  const error = issuesState.error ?? activityCtx.error;
  const initialLoading = issuesState.loading && issuesState.data === undefined;

  const repoCount = new Set(issues.map((i) => i.repo)).size;
  const stats = {
    active: issues.filter((i) => i.status === "running").length,
    waiting: issues.filter((i) => i.status === "waiting").length,
    suspended: issues.filter((i) => i.status === "suspended").length,
    cost: issues.reduce((sum, i) => sum + i.costUsd, 0),
  };

  return (
    <div className="mx-auto max-w-[1280px]">
      <ConnectionBanner error={error} />

      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">overview</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">ダッシュボード</h1>
        </div>
        <div className="flex items-center gap-3">
          <p className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            {issues.length} issues · {repoCount} repos
          </p>
          <AddIssueButton />
        </div>
      </div>

      {/* stats */}
      <div className="rise mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4" style={{ animationDelay: "60ms" }}>
        <Stat label="稼働中" value={String(stats.active)} accent="var(--color-signal)" sub="agents" />
        <Stat label="人間待ち" value={String(stats.waiting)} accent="var(--color-amber)" sub="gates" />
        <Stat label="中断" value={String(stats.suspended)} accent="var(--color-rose)" />
        <Stat label="実行中コスト" value={`$${stats.cost.toFixed(2)}`} accent="var(--color-cyan)" />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-5 xl:grid-cols-[1fr_320px]">
        {/* issue stream */}
        <section className="rise" style={{ animationDelay: "120ms" }}>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[13px] font-semibold">処理中の Issue</h2>
            <span className="eyebrow">live</span>
          </div>
          <div className="flex flex-col gap-3">
            {initialLoading && (
              <div className="panel p-4 text-[13px]" style={{ color: "var(--color-ink-faint)" }}>
                読み込み中…
              </div>
            )}
            {!initialLoading && issues.length === 0 && (
              <div className="panel p-4 text-[13px]" style={{ color: "var(--color-ink-faint)" }}>
                処理中の Issue はありません。
              </div>
            )}
            {issues.map((issue, i) => (
              <Link
                key={`${issue.repo}#${issue.number}`}
                href={`/issues/${issue.number}?repo=${encodeURIComponent(issue.repo)}`}
                className="panel panel-hover group block p-4 rise"
                style={{ animationDelay: `${140 + i * 45}ms` }}
              >
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
                        {issue.repo}#{issue.number}
                      </span>
                      <TypeTag type={issue.type} />
                    </div>
                    <h3 className="mt-1 truncate text-[15px] font-medium">{issue.title}</h3>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    <StatusPill status={issue.status} />
                    <span className="text-[12px]" style={{ color: "var(--color-ink-dim)" }}>
                      <Money value={issue.costUsd} />
                    </span>
                  </div>
                </div>

                <div className="mt-4">
                  <PhaseRail phase={issue.phase} accent={phaseAccent[issue.phase]} />
                </div>

                <div className="mt-3 flex items-center justify-between">
                  {issue.needsHuman ? (
                    <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: "var(--color-amber)" }}>
                      <span className="block h-1 w-1 rounded-full" style={{ background: "var(--color-amber)" }} />
                      {issue.needsHuman}
                    </span>
                  ) : (
                    <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                      更新 {issue.updated}
                    </span>
                  )}
                  <span className="flex items-center gap-1 text-[12px] opacity-0 transition-opacity group-hover:opacity-100" style={{ color: "var(--color-ink-dim)" }}>
                    詳細 <IconArrow width={13} height={13} />
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </section>

        {/* activity */}
        <section className="rise" style={{ animationDelay: "180ms" }}>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[13px] font-semibold">アクティビティ</h2>
            <span className="eyebrow">events</span>
          </div>
          <div className="panel p-2">
            {!initialLoading && activity.length === 0 ? (
              <p className="px-2.5 py-3 text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
                イベントはまだありません。
              </p>
            ) : (
              <ol className="flex flex-col">
                {activity.map((ev) => {
                  const { icon: Icon, color } = eventIcon(ev.kind);
                  return (
                    <li key={ev.id} className="flex gap-3 rounded-lg px-2.5 py-2.5 transition-colors hover:bg-[var(--color-panel-2)]">
                      <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md" style={{ color, background: `color-mix(in srgb, ${color} 12%, transparent)` }}>
                        <Icon width={13} height={13} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] leading-snug">{ev.title}</p>
                        {ev.detail && <p className="truncate text-[12px]" style={{ color: "var(--color-ink-faint)" }}>{ev.detail}</p>}
                      </div>
                      <span className="shrink-0 font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>{ev.at}</span>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
