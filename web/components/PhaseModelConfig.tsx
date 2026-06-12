"use client";

import { useState } from "react";
import { defaultPhaseModels, MODEL_META, type ModelId, type PhaseModelConfig as Row } from "@/lib/model-config";
import { IconCheck } from "./icons";

function setRow(rows: Row[], i: number, patch: Partial<Row>): Row[] {
  return rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
}

/** フェーズごとに使用モデル・拡張思考・最大ターン数を設定する */
export function PhaseModelConfig() {
  const [rows, setRows] = useState(defaultPhaseModels);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  const update = (i: number, patch: Partial<Row>) => {
    setRows((prev) => setRow(prev, i, patch));
    setDirty(true);
    setSaved(false);
  };

  return (
    <div className="panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b px-5 py-3" style={{ borderColor: "var(--color-line)" }}>
        <span className="text-[13px] font-semibold">フェーズ別モデル</span>
        <span className="font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>config.yaml → agents.phase_models</span>
        <div className="ml-auto flex items-center gap-2.5">
          {saved && (
            <span className="inline-flex items-center gap-1 text-[12px]" style={{ color: "var(--color-cyan)" }}>
              <IconCheck width={13} height={13} /> 保存しました
            </span>
          )}
          <button
            onClick={() => {
              setDirty(false);
              setSaved(true);
            }}
            disabled={!dirty}
            className="rounded-lg px-3.5 py-1.5 text-[12px] font-semibold disabled:opacity-40"
            style={{ color: "#0b0d10", background: "var(--color-signal)" }}
          >
            保存
          </button>
        </div>
      </div>

      <div className="flex flex-col">
        {rows.map((r, i) => (
          <div key={r.phase} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-5 py-3.5 last:border-0" style={{ borderColor: "var(--color-line)" }}>
            <div className="w-[150px] min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] uppercase" style={{ color: "var(--color-ink-faint)" }}>{r.phase}</span>
                <span className="text-[13px] font-medium">{r.label}</span>
              </div>
              <p className="mt-0.5 text-[10.5px] leading-snug" style={{ color: "var(--color-ink-faint)" }}>{r.hint}</p>
            </div>

            {/* model segmented */}
            <div className="inline-flex overflow-hidden rounded-lg border" style={{ borderColor: "var(--color-line)" }}>
              {(Object.keys(MODEL_META) as ModelId[]).map((m) => {
                const meta = MODEL_META[m];
                const active = r.model === m;
                return (
                  <button
                    key={m}
                    onClick={() => update(i, { model: m })}
                    title={meta.costNote}
                    className="px-2.5 py-1.5 font-mono text-[11px] transition-colors"
                    style={{ color: active ? "#0b0d10" : "var(--color-ink-dim)", background: active ? meta.color : "transparent" }}
                  >
                    {meta.label}
                  </button>
                );
              })}
            </div>

            {/* thinking toggle */}
            <button
              onClick={() => update(i, { thinking: !r.thinking })}
              className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px]"
              style={{
                borderColor: r.thinking ? "color-mix(in srgb, var(--color-violet) 45%, transparent)" : "var(--color-line)",
                color: r.thinking ? "var(--color-violet)" : "var(--color-ink-faint)",
                background: r.thinking ? "color-mix(in srgb, var(--color-violet) 9%, transparent)" : "transparent",
              }}
            >
              <span className="block h-1.5 w-1.5 rounded-full" style={{ background: r.thinking ? "var(--color-violet)" : "var(--color-line-2)" }} />
              拡張思考
            </button>

            {/* max turns */}
            <div className="ml-auto flex items-center gap-1.5">
              <span className="font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>max turns</span>
              <div className="inline-flex items-center overflow-hidden rounded-lg border" style={{ borderColor: "var(--color-line)" }}>
                <button onClick={() => update(i, { maxTurns: Math.max(1, r.maxTurns - 5) })} className="px-2 py-1 text-[13px]" style={{ color: "var(--color-ink-dim)" }} aria-label="減らす">−</button>
                <span className="w-[34px] text-center font-mono text-[12px] tnum">{r.maxTurns}</span>
                <button onClick={() => update(i, { maxTurns: r.maxTurns + 5 })} className="px-2 py-1 text-[13px]" style={{ color: "var(--color-ink-dim)" }} aria-label="増やす">＋</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <p className="px-5 py-3 text-[11.5px]" style={{ color: "var(--color-ink-faint)", background: "var(--color-panel-2)" }}>
        計画など判断が重い工程に Opus + 拡張思考、実装量産は Sonnet、判定だけの工程は Haiku が目安。リポジトリ単位の上書きは config.yaml 側で対応予定。
      </p>
    </div>
  );
}
