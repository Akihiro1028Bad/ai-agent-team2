"use client";

import { useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { DiffViewer } from "@/components/DiffViewer";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { IconArrow } from "@/components/icons";

export default function IssueDiffPage() {
  const { id } = useParams<{ id: string }>();
  const n = Number(id);

  const fetcher = useCallback((signal: AbortSignal) => api.getDiff(n, signal), [n]);
  const { data: diff, error, loading } = usePolling(fetcher, 8000);

  const is404 = error?.status === 404;

  return (
    <div className="mx-auto max-w-[1200px] pb-4">
      <Link
        href={`/issues/${id}`}
        className="inline-flex items-center gap-1.5 text-[12.5px]"
        style={{ color: "var(--color-ink-dim)" }}
      >
        <IconArrow width={13} height={13} className="rotate-180" /> Issue 詳細
      </Link>

      <ConnectionBanner error={is404 ? undefined : error} />

      {is404 ? (
        <div className="panel mt-4 p-8 text-center" style={{ color: "var(--color-ink-dim)" }}>
          この Issue にはまだ PR がありません。
        </div>
      ) : loading ? (
        <div className="panel mt-4 p-8 text-center" style={{ color: "var(--color-ink-faint)" }}>
          読み込み中…
        </div>
      ) : diff && diff.files.length > 0 ? (
        <>
          <div className="rise mt-4">
            <div className="eyebrow">pull request diff</div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
                {diff.pr > 0 && `PR #${diff.pr}`}
                {diff.branch ? ` · ${diff.branch}` : ""}
              </span>
            </div>
          </div>
          <div className="rise mt-5" style={{ animationDelay: "80ms" }}>
            <DiffViewer diff={diff} />
          </div>
        </>
      ) : diff && diff.files.length === 0 ? (
        <div className="panel mt-4 p-8 text-center" style={{ color: "var(--color-ink-dim)" }}>
          差分ファイルがありません。
        </div>
      ) : null}
    </div>
  );
}
