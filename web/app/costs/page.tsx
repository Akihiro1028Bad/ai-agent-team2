"use client";

import Link from "next/link";
import { useState } from "react";
import { costSummary, dailyCosts, issueCosts, phaseCosts } from "@/lib/costs";
import { Money } from "@/components/ui";

function BarChart() {
  const [mode, setMode] = useState<"usd" | "tokens">("usd");
  const max = Math.max(...dailyCosts.map((d) => (mode === "usd" ? d.usd : d.tokensM)));
  return (
    <div className="panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-[13px] font-semibold">日別推移（直近 14 日）</h2>
        <div className="inline-flex overflow-hidden rounded-lg border" style={{ borderColor: "var(--color-line)" }}>
          {(["usd", "tokens"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className="px-3 py-1 font-mono text-[11px]"
              style={{ color: mode === m ? "#0b0d10" : "var(--color-ink-dim)", background: mode === m ? "var(--color-cyan)" : "transparent" }}
            >
              {m === "usd" ? "$ コスト" : "トークン"}
            </button>
          ))}
        </div>
      </div>
      <div className="flex h-[180px] items-end gap-1.5 sm:gap-2.5">
        {dailyCosts.map((d) => {
          const v = mode === "usd" ? d.usd : d.tokensM;
          const h = Math.max(4, (v / max) * 160);
          return (
            <div key={d.day} className="group flex flex-1 flex-col items-center gap-1.5">
              <span className="font-mono text-[9px] opacity-0 transition-opacity group-hover:opacity-100" style={{ color: "var(--color-ink-dim)" }}>
                {mode === "usd" ? `$${v.toFixed(1)}` : `${v.toFixed(1)}M`}
              </span>
              <div
                className="w-full rounded-t-[3px] transition-all"
                style={{
                  height: h,
                  background: `color-mix(in srgb, var(--color-cyan) ${40 + (v / max) * 60}%, var(--color-panel-2))`,
                }}
              />
              <span className="font-mono text-[9px]" style={{ color: "var(--color-ink-faint)" }}>{d.day}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PhaseBreakdown() {
  const total = phaseCosts.reduce((s, p) => s + p.usd, 0);
  return (
    <div className="panel p-5">
      <h2 className="mb-4 text-[13px] font-semibold">フェーズ別内訳（今月）</h2>
      <div className="flex h-3 w-full overflow-hidden rounded-full">
        {phaseCosts.map((p) => (
          <div key={p.phase} style={{ width: `${(p.usd / total) * 100}%`, background: p.color }} title={`${p.label} $${p.usd}`} />
        ))}
      </div>
      <div className="mt-4 flex flex-col gap-2">
        {phaseCosts.map((p) => (
          <div key={p.phase} className="flex items-center gap-2.5 text-[12.5px]">
            <span className="block h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} />
            <span style={{ color: "var(--color-ink-dim)" }}>{p.label}</span>
            <span className="ml-auto font-mono tnum" style={{ color: "var(--color-ink)" }}>${p.usd.toFixed(1)}</span>
            <span className="w-[44px] text-right font-mono text-[11px] tnum" style={{ color: "var(--color-ink-faint)" }}>
              {((p.usd / total) * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function CostsPage() {
  const budgetPct = (costSummary.monthUsd / costSummary.monthBudgetUsd) * 100;
  return (
    <div className="mx-auto max-w-[1100px]">
      <div className="rise">
        <div className="eyebrow">cost &amp; tokens</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">コスト</h1>
      </div>

      {/* summary */}
      <div className="rise mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4" style={{ animationDelay: "60ms" }}>
        <div className="panel p-4">
          <div className="eyebrow">今月の合計</div>
          <div className="mt-2 font-mono text-2xl font-semibold tnum" style={{ color: "var(--color-cyan)" }}>${costSummary.monthUsd.toFixed(2)}</div>
        </div>
        <div className="panel p-4">
          <div className="eyebrow">月次予算</div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="font-mono text-2xl font-semibold tnum" style={{ color: budgetPct > 80 ? "var(--color-amber)" : "var(--color-ink)" }}>{budgetPct.toFixed(0)}%</span>
            <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>/ ${costSummary.monthBudgetUsd}</span>
          </div>
          <div className="mt-2 h-1 overflow-hidden rounded-full" style={{ background: "var(--color-panel-2)" }}>
            <div className="h-full rounded-full" style={{ width: `${Math.min(100, budgetPct)}%`, background: budgetPct > 80 ? "var(--color-amber)" : "var(--color-cyan)" }} />
          </div>
        </div>
        <div className="panel p-4">
          <div className="eyebrow">Issue 平均</div>
          <div className="mt-2 font-mono text-2xl font-semibold tnum">${costSummary.avgPerIssueUsd.toFixed(2)}</div>
        </div>
        <div className="panel p-4">
          <div className="eyebrow">完了 Issue 平均</div>
          <div className="mt-2 font-mono text-2xl font-semibold tnum" style={{ color: "var(--color-signal)" }}>${costSummary.avgPerDoneIssueUsd.toFixed(2)}</div>
        </div>
      </div>

      <div className="rise mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[1fr_340px]" style={{ animationDelay: "120ms" }}>
        <BarChart />
        <PhaseBreakdown />
      </div>

      {/* per-issue table */}
      <div className="rise mt-5 panel overflow-hidden" style={{ animationDelay: "180ms" }}>
        <div className="border-b px-5 py-3 text-[13px] font-semibold" style={{ borderColor: "var(--color-line)" }}>Issue 別の使用量</div>
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
              {issueCosts.map((r) => (
                <tr key={r.issue} className="border-t transition-colors hover:bg-[var(--color-panel-2)]" style={{ borderColor: "var(--color-line)" }}>
                  <td className="px-5 py-2.5">
                    <Link href={`/issues/${r.issue}`} className="flex items-center gap-2">
                      <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>{r.repo}#{r.issue}</span>
                      <span className="hidden truncate md:inline">{r.title}</span>
                    </Link>
                  </td>
                  <td className="px-3 py-2.5 text-right"><Money value={r.usd} /></td>
                  <td className="hidden px-3 py-2.5 text-right font-mono tnum sm:table-cell" style={{ color: "var(--color-ink-dim)" }}>{r.inTokensK.toLocaleString()}k</td>
                  <td className="hidden px-3 py-2.5 text-right font-mono tnum sm:table-cell" style={{ color: "var(--color-ink-dim)" }}>{r.outTokensK.toLocaleString()}k</td>
                  <td className="px-5 py-2.5 text-right font-mono tnum" style={{ color: "var(--color-ink-dim)" }}>{r.turns}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
