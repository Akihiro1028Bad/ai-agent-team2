"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { ApproveButton } from "@/components/review/ApproveButton";
import { IconArrow, IconCheck, IconGate, IconX } from "@/components/icons";

interface ApprovalGateProps {
  /** 承認対象の Issue 番号。 */
  issue: number;
  /** マルチリポ一意化のための "owner/repo"（一覧から引き回す, #118）。 */
  repo?: string;
  /** ゲートの種別。plan = 計画承認 (#146)、split = 分割承認 (#150)。 */
  kind?: "plan" | "split";
  /** GitHub リンク生成用の "owner/repo"（split で提案コメント参照に使う）。 */
  repoFullName?: string;
}

/**
 * 差し戻し（理由付き）— split 承認ゲート専用 (#150)。
 *
 * 設計承認と違い分割提案は構造化された Web ビューを持たないため、理由テキストを
 * 1 件の指摘コメントとして送る。backend は指摘ありを changes_requested に分類し、
 * SPLIT→CLARIFY へ差し戻す。
 */
function SplitRejectBox({ issue, repo }: { issue: number; repo?: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const text = reason.trim();
    if (!text) return;
    setSending(true);
    setError(null);
    try {
      const actor = await api.getDefaultActor();
      await api.postReview(issue, [{ anchor: "split", anchorLabel: "分割提案", tag: "指摘", body: text }], actor, repo);
      setDone(true);
    } catch {
      setError("差し戻しの送信に失敗しました。少し待ってから再試行してください。");
    } finally {
      setSending(false);
    }
  };

  if (done) {
    return (
      <span role="status" className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--color-amber)" }}>
        <IconCheck width={14} height={14} /> 差し戻しました。修正のうえ再提案されます。
      </span>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-[12.5px] underline"
        style={{ color: "var(--color-ink-dim)" }}
      >
        差し戻す（修正を依頼）
      </button>
    );
  }

  return (
    <div className="w-full">
      <textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        disabled={sending}
        rows={2}
        placeholder="修正してほしい点を入力…（例: サブタスクをもっと細かく分けてください）"
        className="mb-2 w-full resize-none rounded-lg border bg-transparent px-3 py-2 text-[13px] outline-none placeholder:text-[var(--color-ink-faint)] disabled:opacity-50"
        style={{ borderColor: "var(--color-line)" }}
      />
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={sending || reason.trim().length === 0}
          onClick={() => void submit()}
          className="inline-flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-[12.5px] font-medium disabled:opacity-40"
          style={{ color: "#0b0d10", background: "var(--color-amber)" }}
        >
          <IconArrow width={13} height={13} /> {sending ? "送信中…" : "差し戻して送信"}
        </button>
        {error && (
          <span className="inline-flex items-center gap-1 text-[12px]" style={{ color: "var(--color-rose)" }}>
            <IconX width={12} height={12} /> {error}
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * 承認ゲート（#146 計画承認 / #150 分割承認）。
 *
 * 承認待ちの Issue を詳細画面から直接かつ分かりやすく承認できる導線を提供する。
 * 設計 PR の有無に依存しない。計画承認は設計レビューへ、分割承認は GitHub の
 * 提案コメントへ誘導し、必要なら差し戻せる。
 */
export function ApprovalGate({ issue, repo, kind = "plan", repoFullName }: ApprovalGateProps) {
  const repoQuery = repo ? `?repo=${encodeURIComponent(repo)}` : "";
  const isSplit = kind === "split";
  const title = isSplit ? "この Issue は分割提案の承認待ちです" : "この計画は承認待ちです";
  const desc = isSplit
    ? "提案された分割案を確認のうえ承認すると、子 Issue の作成（分割実行）に進みます。修正が必要な場合は差し戻せます。"
    : "内容を確認のうえ承認すると、実装フェーズに進みます。指摘・質問がある場合は設計レビューから差し戻せます。";
  const issueUrl = repoFullName ? `https://github.com/${repoFullName}/issues/${issue}` : null;

  return (
    <div
      className="mt-4 rounded-xl border p-4"
      style={{
        borderColor: "color-mix(in srgb, var(--color-signal) 38%, transparent)",
        background: "color-mix(in srgb, var(--color-signal) 7%, transparent)",
      }}
    >
      <div className="mb-1 flex items-center gap-2">
        <IconGate width={15} height={15} style={{ color: "var(--color-signal)" }} />
        <span className="text-[13px] font-semibold" style={{ color: "var(--color-signal)" }}>
          {title}
        </span>
      </div>
      <p className="mb-3 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>
        {desc}
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <ApproveButton issue={issue} repo={repo} />
        {isSplit ? (
          <>
            {issueUrl && (
              <a
                href={issueUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-[12.5px]"
                style={{ color: "var(--color-signal)" }}
              >
                分割提案を GitHub で見る <IconArrow width={13} height={13} />
              </a>
            )}
            <SplitRejectBox issue={issue} repo={repo} />
          </>
        ) : (
          <Link
            href={`/issues/${issue}/review${repoQuery}`}
            className="inline-flex items-center gap-1.5 text-[12.5px]"
            style={{ color: "var(--color-signal)" }}
          >
            設計レビューを開く（指摘・質問・差し戻し） <IconArrow width={13} height={13} />
          </Link>
        )}
      </div>
    </div>
  );
}
