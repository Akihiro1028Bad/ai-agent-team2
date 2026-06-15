"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { IconCheck, IconX } from "@/components/icons";

interface ApproveButtonProps {
  /** 承認対象の Issue 番号。 */
  issue: number;
  /** マルチリポ一意化のための "owner/repo"（一覧から引き回す, #118）。 */
  repo?: string;
  /** 承認成功後に呼ばれる（一覧の楽観更新など、任意）。 */
  onApproved?: () => void;
  /** 見た目のサイズ。compact は一覧行向け、full は詳細画面向け。 */
  size?: "compact" | "full";
}

/**
 * 計画（設計）承認ボタン（#146）。
 *
 * 空コメントの `POST /api/issues/{n}/review` を送ると backend が「承認」と分類し、
 * control.jsonl 経由で APPROVE→IMPLEMENT へ進む。設計 PR の有無に依存しない。
 * 送信中／受理／失敗の状態を内包し、承認後はフィードバックを表示する。
 */
export function ApproveButton({ issue, repo, onApproved, size = "full" }: ApproveButtonProps) {
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const approve = async () => {
    setSending(true);
    setError(null);
    try {
      const actor = await api.getDefaultActor();
      await api.postReview(issue, [], actor, repo);
      setDone(true);
      onApproved?.();
    } catch {
      setError("承認の送信に失敗しました。少し待ってから再試行してください。");
    } finally {
      setSending(false);
    }
  };

  if (done) {
    return (
      <span
        role="status"
        className="inline-flex items-center gap-1.5 text-[12.5px]"
        style={{ color: "var(--color-cyan)" }}
      >
        <IconCheck width={14} height={14} /> 承認を受理しました。まもなく実装フェーズに進みます。
      </span>
    );
  }

  const pad = size === "compact" ? "px-3 py-1.5 text-[12px]" : "px-5 py-2 text-[13px]";
  return (
    <div className="inline-flex flex-wrap items-center gap-2.5">
      <button
        type="button"
        disabled={sending}
        onClick={() => void approve()}
        className={`inline-flex items-center gap-1.5 rounded-lg font-semibold disabled:opacity-40 ${pad}`}
        style={{ color: "#0b0d10", background: "var(--color-signal)" }}
      >
        <IconCheck width={14} height={14} /> {sending ? "承認中…" : "承認"}
      </button>
      {error && (
        <span className="inline-flex items-center gap-1 text-[12px]" style={{ color: "var(--color-rose)" }}>
          <IconX width={12} height={12} /> {error}
        </span>
      )}
    </div>
  );
}
