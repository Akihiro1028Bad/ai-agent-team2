import type { PhaseKey } from "@/lib/types";
import { MAIN_PHASES, PHASE_LABEL } from "@/lib/mock";

// 条件付きフェーズ(split/revise)を主経路のインデックスへ写像
const MAIN_INDEX: Record<PhaseKey, number> = {
  intake: 0,
  clarify: 1,
  split: 1,
  plan: 2,
  approve: 3,
  implement: 4,
  review: 5,
  revise: 5,
  done: 6,
};

const CONDITIONAL_LABEL: Partial<Record<PhaseKey, string>> = {
  split: "分割中",
  revise: "修正中",
};

interface PhaseRailProps {
  phase: PhaseKey;
  accent: string;
  variant?: "compact" | "full";
}

export function PhaseRail({ phase, accent, variant = "compact" }: PhaseRailProps) {
  const active = MAIN_INDEX[phase];
  const full = variant === "full";

  return (
    <div className="flex w-full items-center">
      {MAIN_PHASES.map((p, i) => {
        const done = i < active;
        const current = i === active;
        const dotColor = done ? "var(--color-cyan)" : current ? accent : "var(--color-line-2)";
        return (
          <div key={p.key} className="flex min-w-0 flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center gap-1.5">
              <span
                className={current ? "pulse" : ""}
                style={{ color: dotColor }}
              >
                <span
                  className="block rounded-full"
                  style={{
                    width: full ? 11 : 8,
                    height: full ? 11 : 8,
                    background: done || current ? dotColor : "transparent",
                    border: done || current ? "none" : `1.5px solid ${dotColor}`,
                    boxShadow: current ? `0 0 12px -2px ${accent}` : "none",
                  }}
                />
              </span>
              {full && (
                <span
                  className="font-mono text-[10px] whitespace-nowrap"
                  style={{ color: current ? "var(--color-ink)" : done ? "var(--color-ink-dim)" : "var(--color-ink-faint)" }}
                >
                  {CONDITIONAL_LABEL[phase] && current ? CONDITIONAL_LABEL[phase] : PHASE_LABEL[p.key]}
                </span>
              )}
            </div>
            {i < MAIN_PHASES.length - 1 && (
              <div
                className="mx-1 h-px flex-1 self-start"
                style={{
                  marginTop: full ? 5 : 3.5,
                  background: done ? "var(--color-cyan)" : "var(--color-line)",
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
