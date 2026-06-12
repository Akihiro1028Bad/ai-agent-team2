"use client";

import Link from "next/link";
import { useState } from "react";
import { gates } from "@/lib/mock";
import { getDesignReview } from "@/lib/design-review";
import type { GateItem } from "@/lib/types";
import { TypeTag } from "@/components/ui";
import { IconArrow, IconCheck, IconGate, IconMessage, IconX } from "@/components/icons";

const GATE_META: Record<GateItem["kind"], { label: string; color: string; needsText: boolean }> = {
  "approve-plan": { label: "修正方針の承認", color: "var(--color-amber)", needsText: false },
  "approve-design": { label: "設計の承認", color: "var(--color-amber)", needsText: false },
  hearing: { label: "ヒアリング回答", color: "var(--color-cyan)", needsText: true },
  review: { label: "レビュー応答", color: "var(--color-cyan)", needsText: true },
};

function GateCard({ gate, delay }: { gate: GateItem; delay: number }) {
  const meta = GATE_META[gate.kind];
  const hasReview = getDesignReview(gate.issue) !== null;
  const [resolved, setResolved] = useState<null | string>(null);
  const [text, setText] = useState("");

  return (
    <article className="panel rise overflow-hidden" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-center gap-2 border-b px-5 py-3" style={{ borderColor: "var(--color-line)" }}>
        <span className="grid h-6 w-6 place-items-center rounded-md" style={{ color: meta.color, background: `color-mix(in srgb, ${meta.color} 13%, transparent)` }}>
          {meta.needsText ? <IconMessage width={13} height={13} /> : <IconGate width={13} height={13} />}
        </span>
        <span className="text-[12.5px] font-medium" style={{ color: meta.color }}>{meta.label}</span>
        <span className="ml-auto font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>{gate.age}</span>
      </div>

      <div className="p-5">
        <div className="flex flex-wrap items-center gap-2">
          <Link href={`/issues/${gate.issue}`} className="font-mono text-[12px]" style={{ color: "var(--color-ink-dim)" }}>
            {gate.repo}#{gate.issue}
          </Link>
          <TypeTag type={gate.type} />
        </div>
        <h3 className="mt-1.5 text-[15px] font-medium">{gate.title}</h3>

        <div className="mt-3 rounded-xl border p-3.5" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed" style={{ color: "var(--color-ink-dim)" }}>{gate.prompt}</p>
        </div>

        {hasReview && (
          <Link
            href={`/issues/${gate.issue}/review`}
            className="mt-3 flex items-center justify-between rounded-xl border px-4 py-2.5 transition-colors"
            style={{ borderColor: "color-mix(in srgb, var(--color-signal) 30%, transparent)", background: "color-mix(in srgb, var(--color-signal) 6%, transparent)" }}
          >
            <span className="inline-flex items-center gap-2 text-[12.5px]" style={{ color: "var(--color-signal)" }}>
              <IconGate width={14} height={14} /> 設計レビューを開く（アーキ・図・テスト・計画・画面）
            </span>
            <IconArrow width={13} height={13} style={{ color: "var(--color-signal)" }} />
          </Link>
        )}

        {resolved ? (
          <div className="mt-4 flex items-center gap-2 rounded-lg px-3 py-2.5 text-[13px]" style={{ color: "var(--color-cyan)", background: "color-mix(in srgb, var(--color-cyan) 10%, transparent)" }}>
            <IconCheck width={14} height={14} /> {resolved}
          </div>
        ) : (
          <div className="mt-4">
            {meta.needsText && (
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="回答を入力…（送信するとエージェントへ渡されます）"
                rows={3}
                className="mb-3 w-full resize-none rounded-xl border bg-transparent px-3.5 py-2.5 text-[13px] outline-none placeholder:text-[var(--color-ink-faint)] focus:border-[var(--color-line-2)]"
                style={{ borderColor: "var(--color-line)" }}
              />
            )}
            <div className="flex flex-wrap gap-2.5">
              {meta.needsText ? (
                <button
                  onClick={() => setResolved("回答を送信しました")}
                  disabled={!text.trim()}
                  className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-[13px] font-medium disabled:opacity-40"
                  style={{ color: "#0b0d10", background: "var(--color-signal)" }}
                >
                  <IconArrow width={14} height={14} /> 回答を送信
                </button>
              ) : (
                <>
                  <button
                    onClick={() => setResolved("承認しました → 次フェーズへ")}
                    className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-[13px] font-medium"
                    style={{ color: "#0b0d10", background: "var(--color-signal)" }}
                  >
                    <IconCheck width={14} height={14} /> 承認
                  </button>
                  <button
                    onClick={() => setResolved("差し戻しました → 再計画")}
                    className="inline-flex items-center gap-1.5 rounded-lg border px-4 py-2 text-[13px] font-medium"
                    style={{ borderColor: "color-mix(in srgb, var(--color-rose) 40%, transparent)", color: "var(--color-rose)" }}
                  >
                    <IconX width={14} height={14} /> 差し戻し
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </article>
  );
}

export default function ApprovalsPage() {
  return (
    <div className="mx-auto max-w-[900px]">
      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">human gate</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">承認待ち</h1>
        </div>
        <p className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>{gates.length} 件があなたの判断を待っています</p>
      </div>

      <div className="mt-6 flex flex-col gap-4">
        {gates.map((g, i) => (
          <GateCard key={g.id} gate={g} delay={60 + i * 70} />
        ))}
      </div>
    </div>
  );
}
