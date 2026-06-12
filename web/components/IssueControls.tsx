"use client";

import { useState } from "react";
import { MAIN_PHASES } from "@/lib/mock";
import type { PhaseKey, RunStatus } from "@/lib/types";
import { IconCheck, IconPause, IconPlay, IconRewind, IconStop, IconX } from "./icons";

interface IssueControlsProps {
  issue: number;
  status: RunStatus;
  phase: PhaseKey;
}

/** Issue への介入操作（一時停止/再開・中止・フェーズ巻き戻し） */
export function IssueControls({ issue, status, phase }: IssueControlsProps) {
  const [paused, setPaused] = useState(status === "suspended");
  const [confirming, setConfirming] = useState<"abort" | "rewind" | null>(null);
  const [rewindTo, setRewindTo] = useState<PhaseKey>("plan");
  const [message, setMessage] = useState<string | null>(null);

  const flash = (text: string) => {
    setMessage(text);
    setConfirming(null);
    setTimeout(() => setMessage(null), 3200);
  };

  const phaseIdx = MAIN_PHASES.findIndex((p) => p.key === phase);
  const rewindTargets = MAIN_PHASES.filter((p, i) => i < phaseIdx && p.key !== "done");

  const btn = "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-colors";

  return (
    <div className="mt-4 rounded-xl border p-3" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="eyebrow mr-1">controls</span>

        <button
          onClick={() => {
            setPaused((v) => !v);
            flash(paused ? `#${issue} を再開しました` : `#${issue} を一時停止しました（現在のターン完了後に停止）`);
          }}
          className={btn}
          style={{
            borderColor: `color-mix(in srgb, ${paused ? "var(--color-signal)" : "var(--color-amber)"} 40%, transparent)`,
            color: paused ? "var(--color-signal)" : "var(--color-amber)",
          }}
        >
          {paused ? <IconPlay width={13} height={13} /> : <IconPause width={13} height={13} />}
          {paused ? "再開" : "一時停止"}
        </button>

        <button
          onClick={() => setConfirming(confirming === "rewind" ? null : "rewind")}
          disabled={rewindTargets.length === 0}
          className={`${btn} disabled:opacity-35`}
          style={{ borderColor: "color-mix(in srgb, var(--color-cyan) 40%, transparent)", color: "var(--color-cyan)" }}
        >
          <IconRewind width={13} height={13} /> フェーズ巻き戻し
        </button>

        <button
          onClick={() => setConfirming(confirming === "abort" ? null : "abort")}
          className={btn}
          style={{ borderColor: "color-mix(in srgb, var(--color-rose) 40%, transparent)", color: "var(--color-rose)" }}
        >
          <IconStop width={13} height={13} /> 中止
        </button>

        {message && (
          <span className="ml-auto inline-flex items-center gap-1.5 text-[12px]" style={{ color: "var(--color-cyan)" }}>
            <IconCheck width={13} height={13} /> {message}
          </span>
        )}
      </div>

      {confirming === "rewind" && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border p-3" style={{ borderColor: "var(--color-line-2)" }}>
          <span className="text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>どのフェーズからやり直しますか？</span>
          <div className="flex flex-wrap gap-1.5">
            {rewindTargets.map((p) => (
              <button
                key={p.key}
                onClick={() => setRewindTo(p.key)}
                className="rounded-md border px-2.5 py-1 font-mono text-[11px]"
                style={{
                  borderColor: rewindTo === p.key ? "var(--color-cyan)" : "var(--color-line)",
                  color: rewindTo === p.key ? "var(--color-cyan)" : "var(--color-ink-dim)",
                  background: rewindTo === p.key ? "color-mix(in srgb, var(--color-cyan) 10%, transparent)" : "transparent",
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="ml-auto flex gap-2">
            <button
              onClick={() => flash(`#${issue} を「${MAIN_PHASES.find((p) => p.key === rewindTo)?.label}」フェーズへ巻き戻しました（成果物は保持）`)}
              className="rounded-lg px-3 py-1.5 text-[12px] font-medium"
              style={{ color: "#0b0d10", background: "var(--color-cyan)" }}
            >
              巻き戻す
            </button>
            <button onClick={() => setConfirming(null)} className="text-[12px]" style={{ color: "var(--color-ink-dim)" }}>やめる</button>
          </div>
        </div>
      )}

      {confirming === "abort" && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border p-3" style={{ borderColor: "color-mix(in srgb, var(--color-rose) 40%, transparent)", background: "color-mix(in srgb, var(--color-rose) 6%, transparent)" }}>
          <span className="text-[12.5px]" style={{ color: "var(--color-rose)" }}>
            #{issue} の処理を中止します。worktree とブランチは削除され、Issue にはラベル ai-agent:aborted が付きます。
          </span>
          <div className="ml-auto flex gap-2">
            <button
              onClick={() => flash(`#${issue} を中止しました（worktree をクリーンアップ）`)}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-semibold"
              style={{ color: "#0b0d10", background: "var(--color-rose)" }}
            >
              <IconStop width={12} height={12} /> 中止する
            </button>
            <button onClick={() => setConfirming(null)} className="inline-flex items-center gap-1 text-[12px]" style={{ color: "var(--color-ink-dim)" }}>
              <IconX width={12} height={12} /> やめる
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
