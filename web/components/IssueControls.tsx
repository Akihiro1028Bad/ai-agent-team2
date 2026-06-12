"use client";

import { useState } from "react";
import { MAIN_PHASES } from "@/lib/mock";
import type { PhaseKey, RunStatus } from "@/lib/types";
import { api, actorForRepo, type ControlAction } from "@/lib/api";
import { IconCheck, IconPause, IconPlay, IconRewind, IconStop, IconX } from "./icons";

// rewind target の型 (API 仕様に合わせた完全リスト)
type RewindTarget =
  | "intake"
  | "clarify"
  | "clarify-wait"
  | "split"
  | "plan"
  | "approve"
  | "implement"
  | "review"
  | "revise";

const REWIND_TARGETS: { value: RewindTarget; label: string }[] = [
  { value: "intake", label: "受付" },
  { value: "clarify", label: "ヒアリング" },
  { value: "clarify-wait", label: "ヒアリング待ち" },
  { value: "split", label: "分割" },
  { value: "plan", label: "計画" },
  { value: "approve", label: "承認" },
  { value: "implement", label: "実装" },
  { value: "review", label: "レビュー" },
  { value: "revise", label: "修正" },
];

interface IssueControlsProps {
  issue: number;
  status: RunStatus;
  phase: PhaseKey;
  /** Issue の repo ("owner/repo")。actor 導出に使う。 */
  repo: string;
}

/** Issue への介入操作（一時停止/再開・中止・フェーズ巻き戻し） */
export function IssueControls({ issue, status, phase, repo }: IssueControlsProps) {
  const [paused, setPaused] = useState(status === "suspended");
  const [confirming, setConfirming] = useState<"abort" | "rewind" | null>(null);
  const [rewindTo, setRewindTo] = useState<RewindTarget>("plan");
  const [message, setMessage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  // どのボタンが送信中かを管理する (連打防止)
  const [pending, setPending] = useState<"pause" | "abort" | "rewind" | "retry" | null>(null);

  const flash = (text: string) => {
    setMessage(text);
    setErrorMsg(null);
    setConfirming(null);
    const id = setTimeout(() => setMessage(null), 3200);
    return id;
  };

  const flashError = (text: string) => {
    setErrorMsg(text);
    setMessage(null);
    const id = setTimeout(() => setErrorMsg(null), 4000);
    return id;
  };

  const actor = actorForRepo(repo);

  const sendControl = async (
    key: "pause" | "abort" | "rewind" | "retry",
    req: ControlAction,
    successMsg: string,
    optimistic?: () => void,
    rollback?: () => void,
  ) => {
    setPending(key);
    optimistic?.();
    try {
      await api.postControl(req);
      flash(successMsg);
    } catch {
      rollback?.();
      flashError("送信に失敗しました。少し待ってから再試行してください。");
    } finally {
      setPending(null);
    }
  };

  const phaseIdx = MAIN_PHASES.findIndex((p) => p.key === phase);
  const rewindTargets = MAIN_PHASES.filter((p, i) => i < phaseIdx && p.key !== "done");

  const btn = "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-colors disabled:opacity-40";

  return (
    <div className="mt-4 rounded-xl border p-3" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="eyebrow mr-1">controls</span>

        {/* 一時停止 / 再開 */}
        <button
          disabled={pending !== null}
          onClick={() => {
            const nextPaused = !paused;
            void sendControl(
              "pause",
              { action: nextPaused ? "pause" : "resume", issue, actor },
              nextPaused
                ? `#${issue} を一時停止しました（現在のターン完了後に停止）`
                : `#${issue} を再開しました`,
              () => setPaused(nextPaused),
              () => setPaused(!nextPaused),
            );
          }}
          className={btn}
          style={{
            borderColor: `color-mix(in srgb, ${paused ? "var(--color-signal)" : "var(--color-amber)"} 40%, transparent)`,
            color: paused ? "var(--color-signal)" : "var(--color-amber)",
          }}
        >
          {paused ? <IconPlay width={13} height={13} /> : <IconPause width={13} height={13} />}
          {pending === "pause" ? "送信中…" : paused ? "再開" : "一時停止"}
        </button>

        {/* フェーズ巻き戻し */}
        <button
          onClick={() => setConfirming(confirming === "rewind" ? null : "rewind")}
          disabled={rewindTargets.length === 0 || pending !== null}
          className={`${btn} disabled:opacity-35`}
          style={{ borderColor: "color-mix(in srgb, var(--color-cyan) 40%, transparent)", color: "var(--color-cyan)" }}
        >
          <IconRewind width={13} height={13} /> フェーズ巻き戻し
        </button>

        {/* 中止 */}
        <button
          onClick={() => setConfirming(confirming === "abort" ? null : "abort")}
          disabled={pending !== null}
          className={btn}
          style={{ borderColor: "color-mix(in srgb, var(--color-rose) 40%, transparent)", color: "var(--color-rose)" }}
        >
          <IconStop width={13} height={13} /> 中止
        </button>

        {/* 成功フラッシュ */}
        {message && (
          <span className="ml-auto inline-flex items-center gap-1.5 text-[12px]" style={{ color: "var(--color-cyan)" }}>
            <IconCheck width={13} height={13} /> {message}
          </span>
        )}

        {/* エラーフラッシュ */}
        {errorMsg && (
          <span className="ml-auto inline-flex items-center gap-1.5 text-[12px]" style={{ color: "var(--color-rose)" }}>
            <IconX width={13} height={13} /> {errorMsg}
          </span>
        )}
      </div>

      {/* rewind 確認パネル */}
      {confirming === "rewind" && (
        <div className="mt-3 flex flex-col gap-2 rounded-lg border p-3" style={{ borderColor: "var(--color-line-2)" }}>
          <span className="text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>
            どのフェーズからやり直しますか？
          </span>
          {/* MAIN_PHASES ボタン（既存レール準拠） */}
          {rewindTargets.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {rewindTargets.map((p) => (
                <button
                  key={p.key}
                  onClick={() => setRewindTo(p.key as RewindTarget)}
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
          )}
          {/* MAIN_PHASES にない拡張ターゲット */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>その他:</span>
            <select
              value={rewindTo}
              onChange={(e) => setRewindTo(e.target.value as RewindTarget)}
              className="rounded border bg-transparent px-2 py-1 text-[11px] outline-none"
              style={{ borderColor: "var(--color-line)", color: "var(--color-ink-dim)" }}
            >
              {REWIND_TARGETS.map((t) => (
                <option key={t.value} value={t.value}>{t.label} ({t.value})</option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button
              disabled={pending === "rewind"}
              onClick={() => {
                void sendControl(
                  "rewind",
                  { action: "rewind", issue, target: rewindTo, actor },
                  `#${issue} を「${REWIND_TARGETS.find((t) => t.value === rewindTo)?.label ?? rewindTo}」フェーズへ巻き戻しました（成果物は保持）`,
                );
              }}
              className="rounded-lg px-3 py-1.5 text-[12px] font-medium disabled:opacity-40"
              style={{ color: "#0b0d10", background: "var(--color-cyan)" }}
            >
              {pending === "rewind" ? "送信中…" : "巻き戻す"}
            </button>
            <button onClick={() => setConfirming(null)} className="text-[12px]" style={{ color: "var(--color-ink-dim)" }}>やめる</button>
          </div>
        </div>
      )}

      {/* abort 確認パネル */}
      {confirming === "abort" && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border p-3" style={{ borderColor: "color-mix(in srgb, var(--color-rose) 40%, transparent)", background: "color-mix(in srgb, var(--color-rose) 6%, transparent)" }}>
          <span className="text-[12.5px]" style={{ color: "var(--color-rose)" }}>
            #{issue} の処理を中止します。worktree とブランチは削除され、Issue にはラベル ai-agent:aborted が付きます。
          </span>
          <div className="ml-auto flex gap-2">
            <button
              disabled={pending === "abort"}
              onClick={() => {
                void sendControl(
                  "abort",
                  { action: "abort", issue, actor },
                  `#${issue} を中止しました（worktree をクリーンアップ）`,
                );
              }}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-semibold disabled:opacity-40"
              style={{ color: "#0b0d10", background: "var(--color-rose)" }}
            >
              <IconStop width={12} height={12} /> {pending === "abort" ? "送信中…" : "中止する"}
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
