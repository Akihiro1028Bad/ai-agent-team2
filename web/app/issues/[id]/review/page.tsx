"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError, type DesignView, type PrototypeView } from "@/lib/api";
import type { EvidenceView } from "@/lib/evidence";
import { DesignReviewClient } from "@/components/review/DesignReviewClient";
import { EvidenceGallery } from "@/components/review/EvidenceGallery";
import { PrototypeGallery } from "@/components/review/PrototypeGallery";
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
  // 一覧→詳細から引き回した repo で一意化 (#118)。
  const repo = useSearchParams().get("repo") ?? undefined;
  const repoQuery = repo ? `?repo=${encodeURIComponent(repo)}` : "";

  const [view, setView] = useState<DesignView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  // エビデンス (#91)。design とは独立に取得し、失敗してもレビュー本体は妨げない。
  const [evidence, setEvidence] = useState<EvidenceView | null>(null);
  // UI プロトタイプ (#145)。承認前のプレビュー。取得失敗してもレビュー本体は妨げない。
  const [prototypes, setPrototypes] = useState<PrototypeView | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    api
      .getDesign(id, repo, ac.signal)
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
  }, [id, repo]);

  useEffect(() => {
    const ac = new AbortController();
    api
      .getEvidence(id, ac.signal)
      .then((v) => {
        if (!ac.signal.aborted) setEvidence(v);
      })
      .catch(() => {
        // エビデンス取得失敗はレビュー画面を妨げない（非表示にとどめる）。
      });
    return () => ac.abort();
  }, [id]);

  useEffect(() => {
    const ac = new AbortController();
    api
      .getPrototypes(id, ac.signal)
      .then((v) => {
        if (!ac.signal.aborted) setPrototypes(v);
      })
      .catch(() => {
        // プロトタイプ取得失敗はレビュー画面を妨げない（非表示にとどめる）。
      });
    return () => ac.abort();
  }, [id]);

  return (
    <div className="mx-auto max-w-[920px] pb-4">
      <Link href={`/issues/${id}${repoQuery}`} className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>
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
        <DesignReviewClient issue={id} view={view} repo={repo} />
      ) : (
        <div className="panel mt-4 p-8 text-center" style={{ color: "var(--color-ink-dim)" }}>
          {view?.reason ?? "この Issue にはまだ設計が生成されていません（PLAN フェーズ未完了）。"}
        </div>
      )}

      {prototypes && prototypes.items.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-1 text-[14px] font-semibold">UI プロトタイプ</h2>
          <p className="mb-3 text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            提案 UI を実際に操作して確認できます（モックデータの使い捨てプレビュー）。
          </p>
          <PrototypeGallery items={prototypes.items} notes={prototypes.notes} />
        </section>
      )}

      {evidence && (
        <section className="mt-8">
          <h2 className="mb-3 text-[14px] font-semibold">エビデンス</h2>
          <EvidenceGallery items={evidence.items} notes={evidence.notes} />
        </section>
      )}
    </div>
  );
}
