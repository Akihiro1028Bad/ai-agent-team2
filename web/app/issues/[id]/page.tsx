import Link from "next/link";
import { getIssue } from "@/lib/mock";
import { getDesignReview } from "@/lib/design-review";
import { getPrDiff } from "@/lib/diff";
import { getErrorInfo } from "@/lib/errors";
import { getLogs } from "@/lib/logs";
import { Money, StatusPill, TypeTag, eventIcon, phaseAccent } from "@/components/ui";
import { PhaseRail } from "@/components/PhaseRail";
import { ErrorPanel } from "@/components/ErrorPanel";
import { IssueControls } from "@/components/IssueControls";
import { LogViewer } from "@/components/LogViewer";
import { IconArrow, IconCheck, IconDiff, IconExternal, IconGate } from "@/components/icons";

export default async function IssueDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const issue = getIssue(Number(id));
  const hasReview = getDesignReview(Number(id)) !== null;
  const prDiff = getPrDiff(Number(id));
  const logs = getLogs(Number(id));
  const errorInfo = getErrorInfo(Number(id));

  return (
    <div className="mx-auto max-w-[1100px]">
      <Link href="/" className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>
        <IconArrow width={13} height={13} className="rotate-180" /> ダッシュボード
      </Link>

      {/* header */}
      <div className="rise mt-4 panel p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>{issue.repo}#{issue.number}</span>
              <TypeTag type={issue.type} />
              {issue.prNumber && (
                <a href="#" className="inline-flex items-center gap-1 font-mono text-[11px]" style={{ color: "var(--color-cyan)" }}>
                  PR #{issue.prNumber} <IconExternal width={11} height={11} />
                </a>
              )}
            </div>
            <h1 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">{issue.title}</h1>
            <p className="mt-2 max-w-2xl text-[13.5px] leading-relaxed" style={{ color: "var(--color-ink-dim)" }}>{issue.body}</p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusPill status={issue.status} />
            <div className="text-right">
              <div className="eyebrow">cost</div>
              <div className="text-[15px]" style={{ color: "var(--color-ink)" }}><Money value={issue.costUsd} /></div>
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-xl border p-4" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
          <PhaseRail phase={issue.phase} accent={phaseAccent[issue.phase]} variant="full" />
        </div>

        <IssueControls issue={issue.number} status={issue.status} phase={issue.phase} />

        {prDiff && (
          <Link href={`/issues/${id}/diff`} className="mt-4 flex items-center justify-between rounded-xl border px-4 py-3 transition-colors" style={{ borderColor: "color-mix(in srgb, var(--color-cyan) 32%, transparent)", background: "color-mix(in srgb, var(--color-cyan) 7%, transparent)" }}>
            <span className="inline-flex items-center gap-2 text-[13px]" style={{ color: "var(--color-cyan)" }}>
              <IconDiff width={15} height={15} /> PR #{prDiff.pr} の差分を見る（{prDiff.files.length} files, +{prDiff.files.reduce((s, f) => s + f.add, 0)} −{prDiff.files.reduce((s, f) => s + f.del, 0)}）
            </span>
            <IconArrow width={14} height={14} style={{ color: "var(--color-cyan)" }} />
          </Link>
        )}

        {hasReview && (
          <Link href={`/issues/${id}/review`} className="mt-4 flex items-center justify-between rounded-xl border px-4 py-3 transition-colors" style={{ borderColor: "color-mix(in srgb, var(--color-signal) 32%, transparent)", background: "color-mix(in srgb, var(--color-signal) 7%, transparent)" }}>
            <span className="inline-flex items-center gap-2 text-[13px]" style={{ color: "var(--color-signal)" }}>
              <IconGate width={15} height={15} /> 設計レビューを開く（アーキ・図・テスト・計画・画面）
            </span>
            <IconArrow width={14} height={14} style={{ color: "var(--color-signal)" }} />
          </Link>
        )}

        {issue.needsHuman && (
          <Link href="/approvals" className="mt-4 flex items-center justify-between rounded-xl border px-4 py-3" style={{ borderColor: "color-mix(in srgb, var(--color-amber) 35%, transparent)", background: "color-mix(in srgb, var(--color-amber) 8%, transparent)" }}>
            <span className="inline-flex items-center gap-2 text-[13px]" style={{ color: "var(--color-amber)" }}>
              <span className="block h-1.5 w-1.5 rounded-full" style={{ background: "var(--color-amber)" }} /> {issue.needsHuman}
            </span>
            <span className="inline-flex items-center gap-1 text-[12.5px]" style={{ color: "var(--color-amber)" }}>承認画面へ <IconArrow width={13} height={13} /></span>
          </Link>
        )}
      </div>

      {errorInfo && <ErrorPanel info={errorInfo} />}

      {logs.length > 0 && (
        <section className="rise mt-5" style={{ animationDelay: "60ms" }}>
          <h2 className="mb-3 text-[13px] font-semibold">ライブ実行ログ</h2>
          <LogViewer lines={logs} live={issue.status === "running"} />
        </section>
      )}

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[1fr_360px]">
        {/* timeline */}
        <section className="rise" style={{ animationDelay: "80ms" }}>
          <h2 className="mb-3 text-[13px] font-semibold">タイムライン</h2>
          <div className="panel p-4">
            <ol className="relative ml-1 flex flex-col gap-0.5 border-l pl-5" style={{ borderColor: "var(--color-line)" }}>
              {issue.events.map((ev) => {
                const { icon: Icon, color } = eventIcon(ev.kind);
                return (
                  <li key={ev.id} className="relative py-2.5">
                    <span className="absolute -left-[27px] top-3 grid h-5 w-5 place-items-center rounded-full border" style={{ color, borderColor: "var(--color-line-2)", background: "var(--color-panel)" }}>
                      <Icon width={11} height={11} />
                    </span>
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="text-[13.5px]">{ev.title}</p>
                      <span className="shrink-0 font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>{ev.at}</span>
                    </div>
                    {ev.detail && <p className="mt-0.5 text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>{ev.detail}</p>}
                  </li>
                );
              })}
            </ol>
          </div>
        </section>

        {/* right: subtasks + design */}
        <section className="rise flex flex-col gap-5" style={{ animationDelay: "140ms" }}>
          {issue.subtasks && (
            <div>
              <h2 className="mb-3 text-[13px] font-semibold">サブタスク</h2>
              <div className="panel p-2">
                {issue.subtasks.map((s) => (
                  <div key={s.id} className="flex items-center gap-3 rounded-lg px-3 py-2.5">
                    <span className="grid h-5 w-5 place-items-center rounded-md border" style={{ borderColor: s.done ? "transparent" : "var(--color-line-2)", background: s.done ? "color-mix(in srgb, var(--color-cyan) 18%, transparent)" : "transparent", color: "var(--color-cyan)" }}>
                      {s.done && <IconCheck width={12} height={12} />}
                    </span>
                    <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>#{s.id}</span>
                    <span className="text-[13px]" style={{ color: s.done ? "var(--color-ink-dim)" : "var(--color-ink)" }}>{s.title}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

        </section>
      </div>
    </div>
  );
}
