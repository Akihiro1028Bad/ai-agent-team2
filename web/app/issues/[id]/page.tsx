"use client";

import { useCallback, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { Money, StatusPill, TypeTag, eventIcon, phaseAccent } from "@/components/ui";
import { PhaseRail } from "@/components/PhaseRail";
import { ErrorPanel } from "@/components/ErrorPanel";
import { IssueControls } from "@/components/IssueControls";
import { ApprovalGate } from "@/components/ApprovalGate";
import { LogViewer } from "@/components/LogViewer";
import { HearingThread } from "@/components/review/HearingThread";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { ComingSoon } from "@/components/ComingSoon";
import { IconArrow, IconCheck, IconDiff, IconExternal, IconGate, IconX } from "@/components/icons";
import type { ApiError } from "@/lib/api";

export default function IssueDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  // マルチリポでの番号衝突を避けるため一覧から渡る ?repo= を詳細系へ引き回す (#118)。
  const repo = useSearchParams().get("repo") ?? undefined;
  const repoQuery = repo ? `?repo=${encodeURIComponent(repo)}` : "";

  /* v8 ignore next 3 -- usePolling callback is mocked in tests; api.getIssue is tested separately */
  const fetcher = useCallback(
    (signal: AbortSignal) => api.getIssue(id, repo, signal),
    [id, repo],
  );

  const { data: issue, error, loading } = usePolling(fetcher, 5000);

  // ヒアリング Q&A のライブ表示 (#140)。回答後に状態が追従するようポーリングする。
  /* v8 ignore next 3 -- usePolling callback is mocked in tests; api.getHearing は別途テスト */
  const hearingFetcher = useCallback(
    (signal: AbortSignal) => api.getHearing(id, repo, signal),
    [id, repo],
  );
  const { data: hearing } = usePolling(hearingFetcher, 5000);

  // ヒアリング回答送信 (#88)
  const [replyText, setReplyText] = useState("");
  const [replySending, setReplySending] = useState(false);
  const [replyMessage, setReplyMessage] = useState<{ ok: boolean; text: string } | null>(null);

  // 実 API の PR 番号で導線の表示を判定する (差分リンク)。
  const hasPr = issue?.prNumber != null;
  // 承認待ちを直接承認できるゲートを出すか。計画承認 (approve, #146) と
  // 分割承認 (split, #150) の両方を対象にする。設計 PR の有無に依存しない。
  const isApprovalGate =
    (issue?.phase === "approve" || issue?.phase === "split") && issue?.status === "waiting";
  // 設計レビューへの標準導線。approve フェーズはゲート側にレビューリンクを内包する
  // ため、重複を避けてここでは設計 PR がある非 approve 時のみ出す (#146)。
  const hasReview = issue?.designPrNumber != null && !isApprovalGate;

  if (loading && !issue) {
    return (
      <div className="mx-auto max-w-[1100px]">
        <ConnectionBanner error={error} />
        <p style={{ color: "var(--color-ink-faint)" }}>読み込み中…</p>
      </div>
    );
  }

  const is404 = (error as ApiError | undefined)?.status === 404;
  if (is404 || (!issue && !loading)) {
    return (
      <div className="mx-auto max-w-[1100px]">
        <ConnectionBanner error={error} />
        <p style={{ color: "var(--color-ink-dim)" }}>Issue が見つかりません</p>
      </div>
    );
  }

  /* v8 ignore next 7 -- defensive guard: unreachable because the two preceding checks exhaust all !issue states */
  if (!issue) {
    return (
      <div className="mx-auto max-w-[1100px]">
        <ConnectionBanner error={error} />
        <p style={{ color: "var(--color-ink-faint)" }}>読み込み中…</p>
      </div>
    );
  }

  const errorEvents = issue.events.filter((ev) => ev.kind === "error");

  return (
    <div className="mx-auto max-w-[1100px]">
      <ConnectionBanner error={error} />

      <Link href="/" className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>
        <IconArrow width={13} height={13} className="rotate-180" /> ダッシュボード
      </Link>

      {/* header */}
      <div className="rise mt-4 panel p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>{issue.repo}#{issue.number}</span>
              <TypeTag type={issue.type} />
              {issue.prNumber != null && (
                <a href="#" className="inline-flex items-center gap-1 font-mono text-[11px]" style={{ color: "var(--color-cyan)" }}>
                  PR #{issue.prNumber} <IconExternal width={11} height={11} />
                </a>
              )}
            </div>
            <h1 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">{issue.title}</h1>
            {/* Issue 本文は読み取り API 非提供 */}
            <ComingSoon title="Issue 本文" note="読み取り API 未提供（GitHub 本文は別途）" />
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusPill status={issue.status} />
            <div className="text-right">
              <div className="eyebrow">cost</div>
              <div className="text-[15px]" style={{ color: "var(--color-ink)" }}><Money value={issue.costUsd} /></div>
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-xl border p-4" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
          <PhaseRail phase={issue.phase} accent={phaseAccent[issue.phase]} variant="full" />
        </div>

        <IssueControls issue={issue.number} status={issue.status} phase={issue.phase} repo={issue.repo} />

        {/* 承認ゲート: 計画承認 (#146) / 分割承認 (#150) */}
        {isApprovalGate && (
          <ApprovalGate issue={issue.number} repo={repo} kind={issue.phase === "split" ? "split" : "plan"} repoFullName={issue.repo} />
        )}

        {/* ヒアリング Q&A ライブ表示 (#140)。往復履歴・状態・ラウンド数を可視化 */}
        {hearing && Array.isArray(hearing.turns) &&
          (hearing.turns.length > 0 || hearing.state === "waiting" || hearing.state === "in_progress") && (
          <div className="mt-4">
            <HearingThread state={hearing.state} rounds={hearing.rounds} turns={hearing.turns} />
          </div>
        )}

        {/* ヒアリング回答ボックス (clarify-wait 時のみ表示) */}
        {issue.phase === "clarify" && issue.status === "waiting" && (
          <div className="mt-4 rounded-xl border p-4" style={{ borderColor: "color-mix(in srgb, var(--color-amber) 35%, transparent)", background: "color-mix(in srgb, var(--color-amber) 6%, transparent)" }}>
            <div className="mb-2 flex items-center gap-2">
              <span className="block h-1.5 w-1.5 rounded-full" style={{ background: "var(--color-amber)" }} />
              <span className="text-[12.5px] font-medium" style={{ color: "var(--color-amber)" }}>
                エージェントが回答を待っています
              </span>
            </div>
            <textarea
              value={replyText}
              onChange={(e) => setReplyText(e.target.value)}
              disabled={replySending}
              placeholder="回答を入力…（送信するとエージェントへ渡されます）"
              rows={3}
              className="mb-3 w-full resize-none rounded-xl border bg-transparent px-3.5 py-2.5 text-[13px] outline-none placeholder:text-[var(--color-ink-faint)] focus:border-[var(--color-line-2)] disabled:opacity-50"
              style={{ borderColor: "var(--color-line)" }}
            />
            <div className="flex items-center gap-3">
              <button
                disabled={replySending || replyText.trim().length === 0}
                onClick={() => {
                  const text = replyText.trim();
                  /* v8 ignore next -- button is disabled when replyText is empty; this guard is unreachable via UI */
                  if (!text) return;
                  setReplySending(true);
                  setReplyMessage(null);
                  api.postReply(id, text)
                    .then(() => {
                      setReplyText("");
                      setReplyMessage({ ok: true, text: "回答を送信しました。エージェントが処理を再開します。" });
                      setTimeout(() => setReplyMessage(null), 4000);
                    })
                    .catch(() => {
                      setReplyMessage({ ok: false, text: "送信に失敗しました。少し待ってから再試行してください。" });
                    })
                    .finally(() => setReplySending(false));
                }}
                className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-[13px] font-medium disabled:opacity-40"
                style={{ color: "#0b0d10", background: "var(--color-amber)" }}
              >
                <IconArrow width={14} height={14} /> {replySending ? "送信中…" : "回答を送信"}
              </button>
              {replyMessage && (
                <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: replyMessage.ok ? "var(--color-cyan)" : "var(--color-rose)" }}>
                  {replyMessage.ok ? <IconCheck width={13} height={13} /> : <IconX width={13} height={13} />}
                  {replyMessage.text}
                </span>
              )}
            </div>
          </div>
        )}

        {hasPr && (
          <Link href={`/issues/${id}/diff${repoQuery}`} className="mt-4 flex items-center justify-between rounded-xl border px-4 py-3 transition-colors" style={{ borderColor: "color-mix(in srgb, var(--color-cyan) 32%, transparent)", background: "color-mix(in srgb, var(--color-cyan) 7%, transparent)" }}>
            <span className="inline-flex items-center gap-2 text-[13px]" style={{ color: "var(--color-cyan)" }}>
              <IconDiff width={15} height={15} /> PR #{issue.prNumber} の差分を見る
            </span>
            <IconArrow width={14} height={14} style={{ color: "var(--color-cyan)" }} />
          </Link>
        )}

        {hasReview && (
          <Link href={`/issues/${id}/review${repoQuery}`} className="mt-4 flex items-center justify-between rounded-xl border px-4 py-3 transition-colors" style={{ borderColor: "color-mix(in srgb, var(--color-signal) 32%, transparent)", background: "color-mix(in srgb, var(--color-signal) 7%, transparent)" }}>
            <span className="inline-flex items-center gap-2 text-[13px]" style={{ color: "var(--color-signal)" }}>
              <IconGate width={15} height={15} /> 設計レビューを開く（アーキ・図・テスト・計画・画面）
            </span>
            <IconArrow width={14} height={14} style={{ color: "var(--color-signal)" }} />
          </Link>
        )}

        {issue.needsHuman != null && !isApprovalGate && (
          <Link href="/approvals" className="mt-4 flex items-center justify-between rounded-xl border px-4 py-3" style={{ borderColor: "color-mix(in srgb, var(--color-amber) 35%, transparent)", background: "color-mix(in srgb, var(--color-amber) 8%, transparent)" }}>
            <span className="inline-flex items-center gap-2 text-[13px]" style={{ color: "var(--color-amber)" }}>
              <span className="block h-1.5 w-1.5 rounded-full" style={{ background: "var(--color-amber)" }} /> {issue.needsHuman}
            </span>
            <span className="inline-flex items-center gap-1 text-[12.5px]" style={{ color: "var(--color-amber)" }}>承認画面へ <IconArrow width={13} height={13} /></span>
          </Link>
        )}
      </div>

      {errorEvents.length > 0 && <ErrorPanel events={errorEvents} />}

      <section className="rise mt-5" style={{ animationDelay: "60ms" }}>
        <h2 className="mb-3 text-[13px] font-semibold">ライブ実行ログ</h2>
        <LogViewer issueNumber={id} live={issue.status === "running"} />
      </section>

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[1fr_360px]">
        {/* timeline */}
        <section className="rise" style={{ animationDelay: "80ms" }}>
          <h2 className="mb-3 text-[13px] font-semibold">タイムライン</h2>
          <div className="panel p-4">
            {issue.events.length === 0 ? (
              <p className="text-[13px]" style={{ color: "var(--color-ink-faint)" }}>イベントはまだありません。</p>
            ) : (
              <ol className="relative ml-1 flex flex-col gap-0.5 border-l pl-5" style={{ borderColor: "var(--color-line)" }}>
                {issue.events.map((ev) => {
                  const { icon: Icon, color } = eventIcon(ev.kind);
                  return (
                    <li key={ev.id} className="relative py-2.5">
                      <span className="absolute -left-[27px] top-3 grid h-5 w-5 place-items-center rounded-full border" style={{ color, borderColor: "var(--color-line-2)", background: "var(--color-panel)" }}>
                        <Icon width={11} height={11} />
                      </span>
                      <div className="flex items-baseline justify-between gap-3">
                        <p className="text-[13.5px]">{ev.title}</p>
                        <span className="shrink-0 font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>{ev.at}</span>
                      </div>
                      {ev.detail != null && <p className="mt-0.5 text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>{ev.detail}</p>}
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </section>

        {/* right: subtasks */}
        <section className="rise flex flex-col gap-5" style={{ animationDelay: "140ms" }}>
          {issue.subtasks != null && issue.subtasks.length > 0 && (
            <div>
              <h2 className="mb-3 text-[13px] font-semibold">サブタスク</h2>
              <div className="panel p-2">
                {issue.subtasks.map((s) => (
                  <div key={s.id} className="flex items-center gap-3 rounded-lg px-3 py-2.5">
                    <span className="grid h-5 w-5 place-items-center rounded-md border" style={{ borderColor: s.done ? "transparent" : "var(--color-line-2)", background: s.done ? "color-mix(in srgb, var(--color-cyan) 18%, transparent)" : "transparent", color: "var(--color-cyan)" }}>
                      {s.done && <IconCheck width={12} height={12} />}
                    </span>
                    <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>#{s.id}</span>
                    <span className="text-[13px]" style={{ color: s.done ? "var(--color-ink-dim)" : "var(--color-ink)" }}>{s.title}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
