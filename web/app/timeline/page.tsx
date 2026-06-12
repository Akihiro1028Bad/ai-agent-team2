import Link from "next/link";
import { issues, MAIN_PHASES } from "@/lib/mock";
import { StatusPill, TypeTag, phaseAccent } from "@/components/ui";

/** フェーズ遷移のガント風タイムライン（モック: 開始/現在位置を割合で持つ） */
const SPANS: Record<number, { startPct: number; phases: { key: string; pct: number }[] }> = {
  129: { startPct: 2, phases: [{ key: "intake", pct: 3 }, { key: "clarify", pct: 22 }, { key: "plan", pct: 10 }, { key: "approve", pct: 14 }, { key: "implement", pct: 30 }] },
  131: { startPct: 30, phases: [{ key: "intake", pct: 4 }, { key: "plan", pct: 12 }, { key: "approve", pct: 24 }] },
  128: { startPct: 12, phases: [{ key: "intake", pct: 4 }, { key: "clarify", pct: 48 }] },
  126: { startPct: 20, phases: [{ key: "intake", pct: 5 }, { key: "split", pct: 38 }] },
  124: { startPct: 0, phases: [{ key: "intake", pct: 3 }, { key: "clarify", pct: 10 }, { key: "plan", pct: 12 }, { key: "approve", pct: 8 }, { key: "implement", pct: 34 }, { key: "review", pct: 20 }] },
  120: { startPct: 0, phases: [{ key: "intake", pct: 4 }, { key: "plan", pct: 14 }, { key: "approve", pct: 10 }, { key: "implement", pct: 28 }, { key: "review", pct: 12 }, { key: "done", pct: 4 }] },
  118: { startPct: 8, phases: [{ key: "intake", pct: 4 }, { key: "plan", pct: 10 }, { key: "implement", pct: 36 }] },
  116: { startPct: 24, phases: [{ key: "intake", pct: 3 }, { key: "plan", pct: 12 }, { key: "implement", pct: 26 }, { key: "review", pct: 14 }] },
};

const HOURS = ["6:00", "8:00", "10:00", "12:00", "14:00", "16:00"];

export default function TimelinePage() {
  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">phase gantt</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">タイムライン</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {MAIN_PHASES.map((p) => (
            <span key={p.key} className="inline-flex items-center gap-1.5 text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
              <span className="block h-2 w-2 rounded-sm" style={{ background: phaseAccent[p.key] }} />
              {p.label}
            </span>
          ))}
        </div>
      </div>

      <div className="rise mt-6 panel overflow-x-auto p-5" style={{ animationDelay: "80ms" }}>
        <div className="min-w-[760px]">
          {/* time axis */}
          <div className="mb-3 ml-[260px] flex justify-between border-b pb-2 font-mono text-[10px]" style={{ borderColor: "var(--color-line)", color: "var(--color-ink-faint)" }}>
            {HOURS.map((h) => <span key={h}>{h}</span>)}
          </div>

          <div className="flex flex-col gap-2.5">
            {issues.map((issue) => {
              const span = SPANS[issue.number];
              if (!span) return null;
              const running = issue.status === "running";
              return (
                <Link key={issue.number} href={`/issues/${issue.number}`} className="group flex items-center gap-3">
                  <div className="flex w-[248px] shrink-0 items-center gap-2">
                    <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>#{issue.number}</span>
                    <span className="truncate text-[12.5px] transition-colors group-hover:text-[var(--color-ink)]" style={{ color: "var(--color-ink-dim)" }}>{issue.title}</span>
                  </div>
                  <div className="relative h-7 flex-1 overflow-hidden rounded-md" style={{ background: "var(--color-panel-2)" }}>
                    <div className="absolute inset-y-0 flex" style={{ left: `${span.startPct}%` }}>
                      {span.phases.map((seg, i) => {
                        const color = phaseAccent[seg.key as keyof typeof phaseAccent] ?? "var(--color-ink-dim)";
                        const last = i === span.phases.length - 1;
                        return (
                          <div
                            key={i}
                            className={last && running ? "animate-pulse" : ""}
                            style={{
                              width: `${seg.pct * 6}px`,
                              background: `color-mix(in srgb, ${color} ${last ? 75 : 40}%, var(--color-panel-2))`,
                              borderRight: "2px solid var(--color-base)",
                            }}
                            title={seg.key}
                          />
                        );
                      })}
                      {running && (
                        <span className="mx-1 self-center">
                          <span className="block h-1.5 w-1.5 rounded-full" style={{ background: "var(--color-signal)" }} />
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="hidden w-[180px] shrink-0 items-center justify-end gap-2 sm:flex">
                    <TypeTag type={issue.type} />
                    <StatusPill status={issue.status} />
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      </div>

      <p className="rise mt-3 text-[11.5px]" style={{ color: "var(--color-ink-faint)", animationDelay: "140ms" }}>
        各バーはフェーズ滞在時間（モック値）。実装ではフェーズ遷移イベントのタイムスタンプから生成します。
      </p>
    </div>
  );
}
