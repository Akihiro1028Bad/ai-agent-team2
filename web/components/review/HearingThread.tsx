"use client";

import type { HearingState, HearingTurn } from "@/lib/api";

interface HearingThreadProps {
  state: HearingState;
  rounds: number;
  turns: HearingTurn[];
}

const STATE_META: Record<HearingState, { label: string; color: string }> = {
  waiting: { label: "回答待ち", color: "var(--color-amber)" },
  in_progress: { label: "エージェント検討中", color: "var(--color-signal)" },
  done: { label: "ヒアリング完了", color: "var(--color-cyan)" },
  none: { label: "ヒアリングなし", color: "var(--color-ink-faint)" },
};

/**
 * ヒアリング (clarify) Q&A をスレッド形式で表示する (#139)。
 *
 * 承認前の文脈として、エージェントの質問と人間の回答の往復・現在状態・ラウンド数を
 * 示す。turns が空 (state="none") の場合は「ヒアリングなし」を控えめに表示する。
 */
export function HearingThread({ state, rounds, turns }: HearingThreadProps) {
  const meta = STATE_META[state];

  return (
    <div className="panel p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span
          className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px]"
          style={{ borderColor: `color-mix(in srgb, ${meta.color} 40%, transparent)`, color: meta.color }}
        >
          <span className="block h-1.5 w-1.5 rounded-full" style={{ background: meta.color }} />
          {meta.label}
        </span>
        {rounds > 0 && (
          <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
            {rounds} ラウンド
          </span>
        )}
      </div>

      {turns.length === 0 ? (
        <p className="text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>
          この Issue ではヒアリングは行われていません。
        </p>
      ) : (
        <ol className="flex flex-col gap-2.5">
          {turns.map((t, i) => {
            const isQ = t.role === "question";
            return (
              <li
                key={`${i}:${t.createdAt ?? ""}`}
                className="rounded-lg border p-3"
                style={{
                  borderColor: "var(--color-line)",
                  background: isQ ? "var(--color-panel-2)" : "transparent",
                }}
              >
                <div className="mb-1 flex items-center gap-2 text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                  <span
                    className="rounded px-1.5 py-0.5 font-medium"
                    style={{
                      color: isQ ? "var(--color-signal)" : "var(--color-cyan)",
                      background: `color-mix(in srgb, ${isQ ? "var(--color-signal)" : "var(--color-cyan)"} 12%, transparent)`,
                    }}
                  >
                    {isQ ? "質問" : "回答"}
                  </span>
                  {t.author && <span className="font-mono">{t.author}</span>}
                </div>
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed" style={{ color: "var(--color-ink-dim)" }}>
                  {t.body}
                </p>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
