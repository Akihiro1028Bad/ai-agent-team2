"use client";

import { useCallback, useState } from "react";
import { orchestrator } from "@/lib/mock";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { PhaseModelConfig } from "@/components/PhaseModelConfig";
import { IconCpu, IconExternal, IconPause, IconPlay } from "@/components/icons";

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b py-4 last:border-0" style={{ borderColor: "var(--color-line)" }}>
      <div>
        <div className="text-[13.5px]">{label}</div>
        {hint && <div className="mt-0.5 text-[12px]" style={{ color: "var(--color-ink-faint)" }}>{hint}</div>}
      </div>
      {children}
    </div>
  );
}

export default function SettingsPage() {
  const [running, setRunning] = useState(orchestrator.running);
  const [interval, setIntervalSec] = useState(orchestrator.pollingIntervalSec);
  // 監視リポジトリは実 config を表示する (#144)。設定は頻繁に変わらないため緩めの間隔。
  /* v8 ignore next 3 -- usePolling callback is mocked in tests; api.getRepositories is tested separately */
  const { data: repos, error: reposError, loading: reposLoading } = usePolling(
    useCallback((signal: AbortSignal) => api.getRepositories(signal), []),
    30000,
  );
  const repoRows = repos ?? [];

  return (
    <div className="mx-auto max-w-[820px]">
      <div className="rise">
        <div className="eyebrow">configuration</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">制御・設定</h1>
      </div>

      {/* control */}
      <section className="rise mt-6" style={{ animationDelay: "60ms" }}>
        <h2 className="mb-3 text-[13px] font-semibold">オーケストレーター</h2>
        <div className="panel p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="pulse" style={{ color: running ? "var(--color-signal)" : "var(--color-ink-faint)" }}>
                <span className="block h-2.5 w-2.5 rounded-full" style={{ background: running ? "var(--color-signal)" : "var(--color-ink-faint)" }} />
              </span>
              <div>
                <div className="font-mono text-[13px]">{running ? "RUNNING" : "STOPPED"}</div>
                <div className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>account: {orchestrator.account}</div>
              </div>
            </div>
            <button
              onClick={() => setRunning((v) => !v)}
              className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-[13px] font-medium"
              style={{ color: "#0b0d10", background: running ? "var(--color-rose)" : "var(--color-signal)" }}
            >
              {running ? <IconPause width={14} height={14} /> : <IconPlay width={14} height={14} />}
              {running ? "停止" : "起動"}
            </button>
          </div>

          <div className="mt-4">
            <Field label="ポーリング間隔" hint="短いほど GitHub API 消費が増える（推奨 300s 以上）">
              <div className="inline-flex overflow-hidden rounded-lg border" style={{ borderColor: "var(--color-line)" }}>
                {[60, 120, 300, 600].map((s) => (
                  <button
                    key={s}
                    onClick={() => setIntervalSec(s)}
                    className="px-3 py-1.5 font-mono text-[12px] transition-colors"
                    style={{ color: interval === s ? "#0b0d10" : "var(--color-ink-dim)", background: interval === s ? "var(--color-cyan)" : "transparent" }}
                  >
                    {s}s
                  </button>
                ))}
              </div>
            </Field>
            <Field label="最大同時実行数" hint="worktree で並行処理する Issue 数の上限">
              <span className="font-mono text-[14px] tnum">{orchestrator.maxConcurrent}</span>
            </Field>
          </div>
        </div>
      </section>

      {/* phase models */}
      <section className="rise mt-6" style={{ animationDelay: "90ms" }}>
        <h2 className="mb-3 text-[13px] font-semibold">エージェント実行モデル</h2>
        <PhaseModelConfig />
      </section>

      {/* repos — 実 config.yaml を表示 (#144) */}
      <section className="rise mt-6" style={{ animationDelay: "120ms" }}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[13px] font-semibold">監視リポジトリ</h2>
          <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>config.yaml</span>
        </div>
        <div className="panel divide-y" style={{ borderColor: "var(--color-line)" }}>
          {reposLoading && repos === undefined ? (
            <div className="px-4 py-3 text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>読み込み中…</div>
          ) : reposError ? (
            <div className="px-4 py-3 text-[12.5px]" style={{ color: "var(--color-rose)" }}>設定の取得に失敗しました。</div>
          ) : repoRows.length === 0 ? (
            <div className="px-4 py-3 text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>監視リポジトリは未設定です。`ai-agent setup` で追加してください。</div>
          ) : (
            repoRows.map((r) => (
              <div key={`${r.owner}/${r.repo}`} className="flex items-center gap-3 px-4 py-3" style={{ borderColor: "var(--color-line)" }}>
                <IconCpu width={15} height={15} style={{ color: "var(--color-ink-faint)" }} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 font-mono text-[13px]">
                    {r.owner}/<span style={{ color: "var(--color-ink)" }}>{r.repo}</span>
                    <IconExternal width={11} height={11} style={{ color: "var(--color-ink-faint)" }} />
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-2 font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                    <span>label:{r.label}</span><span>·</span><span>base:{r.baseBranch}</span>
                    {r.account && (<><span>·</span><span>account:{r.account}</span></>)}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      {/* notifications */}
      <section className="rise mt-6 mb-2" style={{ animationDelay: "180ms" }}>
        <h2 className="mb-3 text-[13px] font-semibold">通知</h2>
        <div className="panel p-5">
          <Field label="Slack 通知" hint="フェーズ遷移・承認待ち・完了を Webhook で通知">
            <span className="rounded-full px-2.5 py-0.5 text-[11px]" style={{ color: "var(--color-signal)", background: "color-mix(in srgb, var(--color-signal) 12%, transparent)" }}>接続済み</span>
          </Field>
          <Field label="デスクトップ通知" hint="承認が必要になったらブラウザ通知">
            <span className="rounded-full px-2.5 py-0.5 text-[11px]" style={{ color: "var(--color-ink-faint)", background: "var(--color-panel-2)" }}>オフ</span>
          </Field>
        </div>
      </section>
    </div>
  );
}
