"use client";

import Link from "next/link";
import { ApproveButton } from "@/components/review/ApproveButton";
import { IconArrow, IconGate } from "@/components/icons";

interface ApprovalGateProps {
  /** 承認対象の Issue 番号。 */
  issue: number;
  /** マルチリポ一意化のための "owner/repo"（一覧から引き回す, #118）。 */
  repo?: string;
}

/**
 * 計画承認ゲート（#146）。
 *
 * approve フェーズで待機中の Issue に対し、詳細画面から直接かつ分かりやすく承認できる
 * 導線を提供する。設計 PR の有無に依存せず（フェーズが approve であれば必ず表示）、
 * 指摘・質問が必要な場合は設計レビュー画面へ誘導する。
 */
export function ApprovalGate({ issue, repo }: ApprovalGateProps) {
  const repoQuery = repo ? `?repo=${encodeURIComponent(repo)}` : "";
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
          この計画は承認待ちです
        </span>
      </div>
      <p className="mb-3 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>
        内容を確認のうえ承認すると、実装フェーズに進みます。指摘・質問がある場合は設計レビューから差し戻せます。
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <ApproveButton issue={issue} repo={repo} />
        <Link
          href={`/issues/${issue}/review${repoQuery}`}
          className="inline-flex items-center gap-1.5 text-[12.5px]"
          style={{ color: "var(--color-signal)" }}
        >
          設計レビューを開く（指摘・質問・差し戻し） <IconArrow width={13} height={13} />
        </Link>
      </div>
    </div>
  );
}
