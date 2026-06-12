"use client";

import Link from "next/link";
import { useMemo } from "react";
import { api, adaptCostRows, type ApiCostsResponse } from "@/lib/api";
import type { IssueSummary } from "@/lib/types";
import type { IssueCostRow } from "@/lib/costs";
import { usePolling } from "@/lib/hooks";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { ComingSoon } from "@/components/ComingSoon";
import { Money } from "@/components/ui";
import { phaseAccent } from "@/components/ui";

// フェーズ別内訳（実 API から集計）
interface PhaseCostRow {
  phase: string;
  usd: number;
}

function aggregatePhases(costs: ApiCostsResponse): PhaseCostRow[] {
  const acc = new Map<string, number>();
  for (const issue of costs.issues) {
    for (const [phase, usd] of Object.entries(issue.phases)) {
      acc.set(phase, (acc.get(phase) ?? 0) + usd);
    }
  }
  return Array.from(acc.entries())
    .map(([phase, usd]) => ({ phase, usd }))
    .sort((a, b) => b.usd - a.usd);
}

function phaseColor(phase: string): string {
  return (phaseAccent as Record<string, string>)[phase] ?? "var(--color-ink-dim)";
}

function PhaseBreakdown({ costs }: { costs: ApiCostsResponse }) {
  const rows = useMemo(() => aggregatePhases(costs), [costs]);
  const total = rows.reduce((s, p) => s + p.usd, 0);

  if (rows.length === 0) {
    return (
      <div className="panel p-5">
        <h2 className="mb-4 text-[13px] font-semibold">フェーズ別内訳</h2>
        <p className="text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>データなし</p>
      </div>
    );
  }

  return (
    <div className="panel p-5">
      <h2 className="mb-4 text-[13px] font-semibold">フェーズ別内訳</h2>
      <div className="flex h-3 w-full overflow-hidden rounded-full">
        {rows.map((p) => (
          <div
            key={p.phase}
            style={{ width: `${(p.usd / total) * 100}%`, background: phaseColor(p.phase) }}
            title={`${p.phase} $${p.usd.toFixed(3)}`}
          />
        ))}
      </div>
      <div className="mt-4 flex flex-col gap-2">
        {rows.map((p) => (
          <div key={p.phase} className="flex items-center gap-2.5 text-[12.5px]">
            <span className="block h-2.5 w-2.5 rounded-sm" style={{ background: phaseColor(p.phase) }} />
            <span style={{ color: "var(--color-ink-dim)" }}>{p.phase}</span>
            <span className="ml-auto font-mono tnum" style={{ color: "var(--color-ink)" }}>${p.usd.toFixed(3)}</span>
            <span className="w-[44px] text-right font-mono text-[11px] tnum" style={{ color: "var(--color-ink-faint)" }}>
              {((p.usd / total) * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function IssueTable({ rows, loading }: { rows: IssueCostRow[]; loading: boolean }) {
  return (
    <div className="rise mt-5 panel overflow-hidden" style={{ animationDelay: "180ms" }}>
      <div className="border-b px-5 py-3 text-[13px] font-semibold" style={{ borderColor: "var(--color-line)" }}>
        Issue 別の使用量
      </div>
      {loading && rows.length === 0 ? (
        <div className="px-5 py-8 text-center text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>
          読み込み中…
        </div>
      ) : rows.length === 0 ? (
        <div className="px-5 py-8 text-center text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>
          データなし
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--color-ink-faint)" }}>
                <th className="px-5 py-2.5 text-left font-medium">issue</th>
                <th className="px-3 py-2.5 text-right font-medium">cost</th>
                <th className="hidden px-3 py-2.5 text-right font-medium sm:table-cell">in tokens</th>
                <th className="hidden px-3 py-2.5 text-right font-medium sm:table-cell">out tokens</th>
                <th className="px-5 py-2.5 text-right font-medium">turns</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={`${r.repo}-${r.issue}`}
                  className="border-t transition-colors hover:bg-[var(--color-panel-2)]"
                  style={{ borderColor: "var(--color-line)" }}
                >
                  <td className="px-5 py-2.5">
                    <Link href={`/issues/${r.issue}`} className="flex items-center gap-2">
                      <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                        {r.repo}#{r.issue}
                      </span>
                      <span className="hidden truncate md:inline">{r.title}</span>
                    </Link>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Money value={r.usd} />
                  </td>
                  <td className="hidden px-3 py-2.5 text-right font-mono tnum sm:table-cell" style={{ color: "var(--color-ink-dim)" }}>
                    {r.inTokensK === 0 ? "—" : `${r.inTokensK.toLocaleString()}k`}
                  </td>
                  <td className="hidden px-3 py-2.5 text-right font-mono tnum sm:table-cell" style={{ color: "var(--color-ink-dim)" }}>
                    {r.outTokensK === 0 ? "—" : `${r.outTokensK.toLocaleString()}k`}
                  </td>
                  <td className="px-5 py-2.5 text-right font-mono tnum" style={{ color: "var(--color-ink-dim)" }}>
                    {r.turns === 0 ? "—" : r.turns}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function CostsPage() {
  const {
    data: costs,
    error: costsError,
    loading: costsLoading,
  } = usePolling<ApiCostsResponse>((signal) => api.getCosts(signal));

  const {
    data: issues,
    error: issuesError,
  } = usePolling<IssueSummary[]>((signal) => api.listIssues(signal));

  const firstError = costsError ?? issuesError;

  const titleByIssue = useMemo<Map<number, string>>(() => {
    const m = new Map<number, string>();
    if (issues) {
      for (const iss of issues) {
        m.set(iss.number, iss.title);
      }
    }
    return m;
  }, [issues]);

  const costRows = useMemo<IssueCostRow[]>(() => {
    if (!costs) return [];
    return adaptCostRows(costs, titleByIssue);
  }, [costs, titleByIssue]);

  return (
    <div className="mx-auto max-w-[1100px]">
      <ConnectionBanner error={firstError} />

      <div className="rise">
        <div className="eyebrow">cost &amp; tokens</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">コスト</h1>
      </div>

      {/* summary */}
      <div className="rise mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4" style={{ animationDelay: "60ms" }}>
        <div className="panel p-4">
          <div className="eyebrow">累計コスト</div>
          <div className="mt-2 font-mono text-2xl font-semibold tnum" style={{ color: "var(--color-cyan)" }}>
            {costsLoading && !costs ? (
              <span style={{ color: "var(--color-ink-faint)" }}>…</span>
            ) : (
              `$${(costs?.total_usd ?? 0).toFixed(2)}`
            )}
          </div>
        </div>
        <div className="panel p-4">
          <div className="eyebrow">月次予算</div>
          <ComingSoon title="月次予算" note="予算設定 API は未提供" />
        </div>
        <div className="panel p-4">
          <div className="eyebrow">Issue 平均</div>
          <ComingSoon title="Issue 平均" note="集計 API は未提供" />
        </div>
        <div className="panel p-4">
          <div className="eyebrow">完了 Issue 平均</div>
          <ComingSoon title="完了 Issue 平均" note="集計 API は未提供" />
        </div>
      </div>

      <div className="rise mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[1fr_340px]" style={{ animationDelay: "120ms" }}>
        {/* 日次推移は API 非提供 */}
        <ComingSoon title="日次コスト推移" note="読み取り API 未提供（日別集計は今後）" />

        {/* フェーズ別内訳 */}
        {costs ? (
          <PhaseBreakdown costs={costs} />
        ) : (
          <div className="panel p-5">
            <h2 className="mb-4 text-[13px] font-semibold">フェーズ別内訳</h2>
            <p className="text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>
              {costsLoading ? "読み込み中…" : "データなし"}
            </p>
          </div>
        )}
      </div>

      <IssueTable rows={costRows} loading={costsLoading} />
    </div>
  );
}
