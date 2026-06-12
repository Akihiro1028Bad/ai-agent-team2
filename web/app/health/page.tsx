import { healthItems, latencySeries, pollHistory } from "@/lib/health";
import { IconAlert, IconCheck } from "@/components/icons";

const STATUS_META = {
  ok: { color: "var(--color-signal)", label: "OK" },
  warn: { color: "var(--color-amber)", label: "WARN" },
  error: { color: "var(--color-rose)", label: "ERROR" },
} as const;

function Sparkline({ data }: { data: number[] }) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const w = 280;
  const h = 56;
  const pts = data
    .map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / (max - min)) * (h - 8) - 4}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label="API レイテンシ推移">
      <polyline points={pts} fill="none" stroke="var(--color-cyan)" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

export default function HealthPage() {
  const overall = healthItems.some((h) => h.status === "error")
    ? STATUS_META.error
    : healthItems.some((h) => h.status === "warn")
      ? STATUS_META.warn
      : STATUS_META.ok;
  const lastLatency = latencySeries[latencySeries.length - 1];

  return (
    <div className="mx-auto max-w-[1000px]">
      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">system health</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">ヘルスモニタ</h1>
        </div>
        <span className="inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[12px]" style={{ borderColor: `color-mix(in srgb, ${overall.color} 40%, transparent)`, color: overall.color }}>
          <span className="block h-2 w-2 rounded-full" style={{ background: overall.color }} />
          {overall.label === "OK" ? "ALL SYSTEMS GO" : overall.label === "WARN" ? "DEGRADED" : "ATTENTION REQUIRED"}
        </span>
      </div>

      {/* charts row */}
      <div className="rise mt-6 grid grid-cols-1 gap-4 md:grid-cols-2" style={{ animationDelay: "60ms" }}>
        <div className="panel p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[13px] font-semibold">GitHub API レイテンシ</h2>
            <span className="font-mono text-[12px] tnum" style={{ color: "var(--color-cyan)" }}>{lastLatency}ms</span>
          </div>
          <div className="mt-3">
            <Sparkline data={latencySeries} />
          </div>
        </div>
        <div className="panel p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[13px] font-semibold">ポーリング成功率（直近 30 回）</h2>
            <span className="font-mono text-[12px] tnum" style={{ color: "var(--color-signal)" }}>
              {Math.round((pollHistory.filter(Boolean).length / pollHistory.length) * 100)}%
            </span>
          </div>
          <div className="mt-4 flex gap-1">
            {pollHistory.map((ok, i) => (
              <span
                key={i}
                className="h-7 flex-1 rounded-[2px]"
                style={{ background: ok ? "color-mix(in srgb, var(--color-signal) 55%, var(--color-panel-2))" : "var(--color-rose)" }}
                title={ok ? "成功" : "失敗（アカウント停止期間）"}
              />
            ))}
          </div>
          <p className="mt-2.5 text-[11.5px]" style={{ color: "var(--color-ink-faint)" }}>赤はアカウント一時停止期間の失敗。</p>
        </div>
      </div>

      {/* items */}
      <div className="rise mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2" style={{ animationDelay: "120ms" }}>
        {healthItems.map((h) => {
          const meta = STATUS_META[h.status];
          return (
            <div key={h.key} className="panel flex items-start gap-3 p-4">
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg" style={{ color: meta.color, background: `color-mix(in srgb, ${meta.color} 12%, transparent)` }}>
                {h.status === "ok" ? <IconCheck width={14} height={14} /> : <IconAlert width={14} height={14} />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <h3 className="text-[13px] font-medium">{h.label}</h3>
                  <span className="shrink-0 font-mono text-[11px]" style={{ color: meta.color }}>{h.value}</span>
                </div>
                <p className="mt-1 text-[12px]" style={{ color: "var(--color-ink-faint)" }}>{h.detail}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
