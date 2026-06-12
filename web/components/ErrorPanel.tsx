"use client";

import { useState } from "react";
import type { ErrorInfo } from "@/lib/errors";
import { IconAlert, IconCheck, IconExternal, IconPlay, IconRewind } from "./icons";

/** 中断 Issue のエラー詳細（原因・CI ログ・リカバリ操作） */
export function ErrorPanel({ info }: { info: ErrorInfo }) {
  const [logOpen, setLogOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const flash = (text: string) => {
    setMessage(text);
    setTimeout(() => setMessage(null), 3200);
  };

  return (
    <section className="rise mt-5">
      <h2 className="mb-3 text-[13px] font-semibold">エラー詳細</h2>
      <div className="overflow-hidden rounded-2xl border" style={{ borderColor: "color-mix(in srgb, var(--color-rose) 40%, transparent)", background: "color-mix(in srgb, var(--color-rose) 4%, var(--color-panel))" }}>
        {/* summary */}
        <div className="flex items-start gap-3 px-5 py-4">
          <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg" style={{ color: "var(--color-rose)", background: "color-mix(in srgb, var(--color-rose) 13%, transparent)" }}>
            <IconAlert width={16} height={16} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-2">
              <h3 className="text-[14px] font-semibold" style={{ color: "var(--color-rose)" }}>{info.kind}</h3>
              <span className="font-mono text-[10.5px]" style={{ color: "var(--color-ink-faint)" }}>
                phase: {info.phase} · 試行 {info.attempts}/{info.maxAttempts} · {info.failedAt}
              </span>
            </div>
            <p className="mt-1.5 text-[13px] leading-relaxed" style={{ color: "var(--color-ink-dim)" }}>{info.message}</p>
          </div>
        </div>

        {/* agent analysis */}
        <div className="mx-5 mb-4 rounded-xl border p-3.5" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
          <div className="eyebrow mb-1.5">エージェントの原因分析</div>
          <p className="text-[12.5px] leading-relaxed" style={{ color: "var(--color-ink-dim)" }}>{info.suggestion}</p>
        </div>

        {/* ci log */}
        <div className="mx-5 mb-4">
          <button
            onClick={() => setLogOpen((v) => !v)}
            className="flex w-full items-center justify-between rounded-lg border px-3.5 py-2.5 text-[12.5px]"
            style={{ borderColor: "var(--color-line)", color: "var(--color-ink-dim)" }}
          >
            <span className="font-mono text-[11.5px]">失敗した CI ログ（pytest, 3 failed）</span>
            <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>{logOpen ? "閉じる" : "開く"}</span>
          </button>
          {logOpen && (
            <pre className="mt-2 max-h-[340px] overflow-auto whitespace-pre rounded-lg p-4 font-mono text-[11px] leading-[1.7]" style={{ background: "var(--color-void)", color: "var(--color-ink-dim)" }}>
              {info.ciLog}
            </pre>
          )}
        </div>

        {/* actions */}
        <div className="flex flex-wrap items-center gap-2.5 border-t px-5 py-3.5" style={{ borderColor: "var(--color-line)" }}>
          <button
            onClick={() => flash("分析結果をプロンプトに含めて ci_fix を再実行します（リトライ回数をリセット）")}
            className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-[12.5px] font-semibold"
            style={{ color: "#0b0d10", background: "var(--color-signal)" }}
          >
            <IconPlay width={13} height={13} /> 分析を反映して再開
          </button>
          <button
            onClick={() => flash("計画フェーズへ巻き戻しました（テスト方針から再設計）")}
            className="inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-[12.5px] font-medium"
            style={{ borderColor: "color-mix(in srgb, var(--color-cyan) 40%, transparent)", color: "var(--color-cyan)" }}
          >
            <IconRewind width={13} height={13} /> 計画から再設計
          </button>
          <a
            href="#"
            className="inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-[12.5px]"
            style={{ borderColor: "var(--color-line-2)", color: "var(--color-ink-dim)" }}
          >
            GitHub で開く <IconExternal width={12} height={12} />
          </a>
          {message && (
            <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: "var(--color-cyan)" }}>
              <IconCheck width={13} height={13} /> {message}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
