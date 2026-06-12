"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError, type DesignView } from "@/lib/api";
import { DesignReviewClient } from "@/components/review/DesignReviewClient";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { IconArrow } from "@/components/icons";

/**
 * 設計レビューページ (#125)。
 *
 * `GET /api/issues/{n}/design` の実 design.json を 1 回取得して描画する。
 * design.json はレビュー中に変化しない成果物のため、ポーリングではなく初回 fetch とし、
 * 下書きコメントが定期更新で消えないようにする。present=false は「設計未生成」を表示。
 */
export default function DesignReviewPage() {
  const { id: idStr } = useParams<{ id: string }>();
  const id = Number(idStr);

  const [view, setView] = useState<DesignView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ac = new AbortController();
    api
      .getDesign(id, ac.signal)
      .then((v) => {
        if (ac.signal.aborted) return;
        setView(v);
        setError(null);
      })
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });
    return () => ac.abort();
  }, [id]);

  return (
    <div className="mx-auto max-w-[920px] pb-4">
      <Link href={`/issues/${id}`} className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>
        <IconArrow width={13} height={13} className="rotate-180" /> Issue 詳細
      </Link>

      <div className="mt-4">
        <ConnectionBanner error={error} />
      </div>

      {loading && !view ? (
        <p style={{ color: "var(--color-ink-faint)" }}>読み込み中…</p>
      ) : error && !view ? (
        // 取得失敗時は ConnectionBanner で事実を伝えるのみ。
        // 「設計未生成」等の無関係なメッセージは出さない。
        null
      ) : view?.present ? (
        <DesignReviewClient issue={id} view={view} />
      ) : (
        <div className="panel mt-4 p-8 text-center" style={{ color: "var(--color-ink-dim)" }}>
          {view?.reason ?? "この Issue にはまだ設計が生成されていません（PLAN フェーズ未完了）。"}
        </div>
      )}
    </div>
  );
}
