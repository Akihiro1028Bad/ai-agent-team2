"use client";

import { useCallback } from "react";
import { api, adaptHealth } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { ComingSoon } from "@/components/ComingSoon";
import { IconAlert, IconCheck } from "@/components/icons";
import type { HealthItem } from "@/lib/health";

const STATUS_META = {
  ok: { color: "var(--color-signal)", label: "OK" },
  warn: { color: "var(--color-amber)", label: "WARN" },
  error: { color: "var(--color-rose)", label: "ERROR" },
} as const;

export default function HealthPage() {
  const fetcher = useCallback((signal: AbortSignal) => api.getHealth(signal), []);
  const { data: health, error, loading } = usePolling(fetcher, 5000);

  const items: HealthItem[] = health ? adaptHealth(health) : [];

  const overall =
    items.some((h) => h.status === "error")
      ? STATUS_META.error
      : items.some((h) => h.status === "warn")
        ? STATUS_META.warn
        : STATUS_META.ok;

  return (
    <div className="mx-auto max-w-[1000px]">
      <ConnectionBanner error={error} />

      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">system health</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">ヘルスモニタ</h1>
        </div>
        {!loading && (
          <span
            className="inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[12px]"
            style={{
              borderColor: `color-mix(in srgb, ${overall.color} 40%, transparent)`,
              color: overall.color,
            }}
          >
            <span className="block h-2 w-2 rounded-full" style={{ background: overall.color }} />
            {overall.label === "OK"
              ? "ALL SYSTEMS GO"
              : overall.label === "WARN"
                ? "DEGRADED"
                : "ATTENTION REQUIRED"}
          </span>
        )}
      </div>

      {health?.stale && (
        <div
          className="mt-3 flex items-center gap-2 rounded-xl border px-4 py-2.5 text-[13px]"
          style={{
            borderColor: "var(--color-amber)",
            background: "color-mix(in srgb, var(--color-amber) 12%, transparent)",
            color: "var(--color-amber)",
          }}
        >
          <span
            aria-hidden
            className="block h-2 w-2 shrink-0 rounded-full"
            style={{ background: "var(--color-amber)" }}
          />
          <span>
            {health.reason
              ? `停止・ハング中: ${health.reason}`
              : "オーケストレーターが停止またはハング中の可能性があります。"}
          </span>
        </div>
      )}

      {/* charts row — API 非提供 */}
      <div className="rise mt-6 grid grid-cols-1 gap-4 md:grid-cols-2" style={{ animationDelay: "60ms" }}>
        <ComingSoon title="GitHub API レイテンシ" note="読み取り API 未提供" />
        <ComingSoon title="ポーリング成功率" note="読み取り API 未提供" />
      </div>

      {/* items */}
      {loading ? (
        <div className="rise mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2" style={{ animationDelay: "120ms" }}>
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="panel animate-pulse p-4">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 h-7 w-7 shrink-0 rounded-lg" style={{ background: "var(--color-panel-2)" }} />
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="h-3 w-2/3 rounded" style={{ background: "var(--color-panel-2)" }} />
                  <div className="h-3 w-full rounded" style={{ background: "var(--color-panel-2)" }} />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rise mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2" style={{ animationDelay: "120ms" }}>
          {items.map((h) => {
            const meta = STATUS_META[h.status];
            return (
              <div key={h.key} className="panel flex items-start gap-3 p-4">
                <span
                  className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg"
                  style={{
                    color: meta.color,
                    background: `color-mix(in srgb, ${meta.color} 12%, transparent)`,
                  }}
                >
                  {h.status === "ok" ? (
                    <IconCheck width={14} height={14} />
                  ) : (
                    <IconAlert width={14} height={14} />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <h3 className="text-[13px] font-medium">{h.label}</h3>
                    <span className="shrink-0 font-mono text-[11px]" style={{ color: meta.color }}>
                      {h.value}
                    </span>
                  </div>
                  <p className="mt-1 text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
                    {h.detail}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
