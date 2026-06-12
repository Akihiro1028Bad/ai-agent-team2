"use client";

import { useState } from "react";
import type { DesignReview } from "@/lib/design-review";
import { getDesignRevision } from "@/lib/diff";
import { getEvidences } from "@/lib/evidence";
import type { IssueType } from "@/lib/types";
import { api, type ReviewCommentInput } from "@/lib/api";
import { EvidenceGallery } from "./EvidenceGallery";
import { TypeTag } from "@/components/ui";
import { Mermaid } from "@/components/Mermaid";
import { PrototypeFrame } from "@/components/PrototypeFrame";
import { IconArrow, IconCheck } from "@/components/icons";
import { CommentableMarkdown, Commentable, ReviewProvider, useReview } from "./inline-review";

const CAT_COLOR: Record<string, string> = {
  正常: "var(--color-cyan)",
  異常: "var(--color-rose)",
  境界: "var(--color-amber)",
};

function SectionHead({ n, title, count }: { n: string; title: string; count?: string }) {
  return (
    <div className="mb-3 flex items-center gap-2.5">
      <span className="grid h-6 w-6 place-items-center rounded-md font-mono text-[11px]" style={{ color: "var(--color-signal)", background: "color-mix(in srgb, var(--color-signal) 12%, transparent)" }}>{n}</span>
      <h2 className="text-[14px] font-semibold">{title}</h2>
      {count && <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>{count}</span>}
    </div>
  );
}

function SubmitBar({ issue }: { issue: number }) {
  const { comments, setLocked, locked } = useReview();
  const points = comments.filter((c) => c.tag === "指摘").length;
  const questions = comments.filter((c) => c.tag === "質問").length;
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  // POST /api/issues/{n}/review に実接続 (#89)。
  // backend が comments の有無/種別で承認/差し戻し/質問を分類するため、
  // 送信内容（全コメント or 空）だけ渡し、結果メッセージは outcome で出し分ける。
  const OUTCOME_MESSAGE: Record<string, string> = {
    approved: `#${issue} の設計を承認しました → 実装を開始します。`,
    changes_requested: `指摘で差し戻しました → PLAN で再設計します（指摘 ${points} 件）。`,
    questions: `質問を送信しました → エージェントが回答します（質問 ${questions} 件）。`,
  };

  const submit = async (toSend: ReviewCommentInput[]) => {
    setSending(true);
    setError(null);
    try {
      const actor = await api.getDefaultActor();
      const outcome = await api.postReview(issue, toSend, actor);
      setLocked(true);
      setDone(OUTCOME_MESSAGE[outcome] ?? "レビューを提出しました。");
    } catch {
      setError("提出に失敗しました。少し待ってから再試行してください。");
    } finally {
      setSending(false);
    }
  };

  const toInput = (): ReviewCommentInput[] =>
    comments.map((c) => ({ anchor: c.anchor, anchorLabel: c.anchorLabel, tag: c.tag, body: c.body }));

  const submitReturn = () => void submit(toInput());
  const submitQuestions = () => void submit(toInput());
  const approve = () => void submit([]);

  return (
    <div className="sticky bottom-4 z-20 mt-6">
      <div className="panel glow-signal p-3 sm:p-4" style={{ background: "color-mix(in srgb, var(--color-panel) 92%, black)" }}>
        {done ? (
          <div className="flex items-center gap-2 px-2 py-1.5 text-[13.5px]" style={{ color: "var(--color-cyan)" }}>
            <IconCheck width={15} height={15} /> {done}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-3 text-[12.5px]">
              <span style={{ color: "var(--color-ink-dim)" }}>下書き</span>
              <span className="font-mono" style={{ color: points ? "var(--color-rose)" : "var(--color-ink-faint)" }}>指摘 {points}</span>
              <span className="font-mono" style={{ color: questions ? "var(--color-cyan)" : "var(--color-ink-faint)" }}>質問 {questions}</span>
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-2.5">
              {error && (
                <span className="self-center text-[12px]" style={{ color: "var(--color-rose)" }}>{error}</span>
              )}
              {points > 0 ? (
                <button disabled={sending} onClick={submitReturn} className="inline-flex items-center gap-1.5 rounded-lg px-5 py-2 text-[13px] font-semibold disabled:opacity-40" style={{ color: "#0b0d10", background: "var(--color-rose)" }}>
                  <IconArrow width={14} height={14} /> {sending ? "提出中…" : `差し戻して提出（${points + questions}）`}
                </button>
              ) : questions > 0 ? (
                <>
                  <button disabled={sending} onClick={submitQuestions} className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-[13px] font-medium disabled:opacity-40" style={{ color: "#0b0d10", background: "var(--color-cyan)" }}>
                    <IconArrow width={14} height={14} /> {sending ? "送信中…" : `質問を送信（${questions}）`}
                  </button>
                  <button disabled={sending} onClick={approve} className="inline-flex items-center gap-1.5 rounded-lg px-5 py-2 text-[13px] font-semibold disabled:opacity-40" style={{ color: "#0b0d10", background: "var(--color-signal)" }}>
                    <IconCheck width={15} height={15} /> 承認
                  </button>
                </>
              ) : (
                <>
                  <span className="hidden self-center text-[12px] sm:inline" style={{ color: "var(--color-ink-faint)" }}>
                    各部分にホバーして指摘/質問を追加できます
                  </span>
                  <button disabled={sending} onClick={approve} className="inline-flex items-center gap-1.5 rounded-lg px-5 py-2 text-[13px] font-semibold disabled:opacity-40" style={{ color: "#0b0d10", background: "var(--color-signal)" }}>
                    <IconCheck width={15} height={15} /> {sending ? "送信中…" : "承認"}
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>
      {locked && !done && null}
    </div>
  );
}

interface ReviewClientProps {
  review: DesignReview;
  issueType: IssueType;
}

const REV_KIND: Record<string, { mark: string; color: string }> = {
  add: { mark: "+", color: "var(--color-signal)" },
  del: { mark: "−", color: "var(--color-rose)" },
  mod: { mark: "±", color: "var(--color-amber)" },
};

function RevisionPanel({ issue }: { issue: number }) {
  const rev = getDesignRevision(issue);
  const [open, setOpen] = useState(true);
  if (!rev) return null;
  return (
    <section className="panel rise overflow-hidden" style={{ borderColor: "color-mix(in srgb, var(--color-violet) 35%, transparent)" }}>
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2.5 px-5 py-3 text-left">
        <span className="rounded px-1.5 py-0.5 font-mono text-[10px]" style={{ color: "var(--color-violet)", background: "color-mix(in srgb, var(--color-violet) 14%, transparent)" }}>
          v{rev.version}
        </span>
        <span className="text-[13px] font-semibold">差し戻し後の再設計 — 前回からの変更点（{rev.changes.length} 件）</span>
        <span className="ml-auto font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>{open ? "閉じる" : "開く"}</span>
      </button>
      {open && (
        <div className="border-t px-5 py-4" style={{ borderColor: "var(--color-line)" }}>
          <p className="mb-3 rounded-lg px-3 py-2 text-[12.5px]" style={{ color: "var(--color-rose)", background: "color-mix(in srgb, var(--color-rose) 7%, transparent)" }}>
            {rev.reason}
          </p>
          <ul className="flex flex-col gap-1.5">
            {rev.changes.map((c, i) => {
              const k = REV_KIND[c.kind];
              return (
                <li key={i} className="flex items-start gap-2.5 text-[12.5px]">
                  <span className="mt-0.5 w-4 shrink-0 text-center font-mono font-semibold" style={{ color: k.color }}>{k.mark}</span>
                  <span className="shrink-0 font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>[{c.section}]</span>
                  <span style={{ color: "var(--color-ink-dim)" }}>{c.text}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

function Body({ review, issueType }: ReviewClientProps) {
  const evidenceItems = getEvidences(review.issue);
  const nav = [
    { href: "#arch", label: "アーキテクチャ" },
    { href: "#diagram", label: "図" },
    { href: "#test", label: "テスト" },
    { href: "#plan", label: "実装計画" },
    ...(review.prototypeHtml ? [{ href: "#proto", label: "プロトタイプ" }] : []),
    ...(evidenceItems.length ? [{ href: "#evidence", label: "エビデンス" }] : []),
  ];

  return (
    <>
      {/* header */}
      <div className="rise mt-4">
        <div className="eyebrow">design review · plan 成果物 · インラインレビュー可</div>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <span className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>{review.repo}#{review.issue}</span>
          <TypeTag type={issueType} />
        </div>
        <h1 className="mt-1.5 text-xl font-semibold tracking-tight sm:text-2xl">{review.title}</h1>
      </div>

      <nav className="rise sticky top-[57px] z-10 -mx-1 mt-4 flex gap-1.5 overflow-x-auto py-2 backdrop-blur-md" style={{ background: "color-mix(in srgb, var(--color-base) 80%, transparent)" }}>
        {nav.map((s) => (
          <a key={s.href} href={s.href} className="shrink-0 rounded-lg border px-3 py-1.5 text-[12.5px]" style={{ borderColor: "var(--color-line)", color: "var(--color-ink-dim)" }}>{s.label}</a>
        ))}
      </nav>

      <div className="mt-3 flex flex-col gap-5">
        <RevisionPanel issue={review.issue} />

        {/* 1 architecture */}
        <section id="arch" className="panel rise scroll-mt-28 p-5">
          <SectionHead n="1" title="アーキテクチャ説明" />
          <CommentableMarkdown prefix="arch">{review.architecture}</CommentableMarkdown>
        </section>

        {/* 2 diagram */}
        <section id="diagram" className="panel rise scroll-mt-28 p-5">
          <SectionHead n="2" title="アーキテクチャ図" count="mermaid" />
          <Commentable anchor="diagram" label="アーキテクチャ図">
            <div className="rounded-xl border p-4" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
              <Mermaid chart={review.diagram} />
            </div>
          </Commentable>
        </section>

        {/* 3 test */}
        <section id="test" className="panel rise scroll-mt-28 p-5">
          <SectionHead n="3" title="テスト方針・テストケース" count={`${review.testCases.length} ケース`} />
          <CommentableMarkdown prefix="strategy">{review.testStrategy}</CommentableMarkdown>
          <div className="mt-4 flex flex-col gap-1.5">
            <div className="grid grid-cols-[64px_56px_84px_1fr] gap-2 px-2 font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--color-ink-faint)" }}>
              <span>ID</span><span>区分</span><span>対象</span><span>ケース</span>
            </div>
            {review.testCases.map((tc) => (
              <Commentable key={tc.id} anchor={`tc-${tc.id}`} label={`テストケース ${tc.id}`}>
                <div className="grid grid-cols-[64px_56px_84px_1fr] items-center gap-2 rounded-lg border px-2 py-2 text-[12.5px]" style={{ borderColor: "var(--color-line)" }}>
                  <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>{tc.id}</span>
                  <span><span className="rounded px-1.5 py-0.5 font-mono text-[10px]" style={{ color: CAT_COLOR[tc.category], background: `color-mix(in srgb, ${CAT_COLOR[tc.category]} 12%, transparent)` }}>{tc.category}</span></span>
                  <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-dim)" }}>{tc.target}</span>
                  <span>{tc.title}</span>
                </div>
              </Commentable>
            ))}
          </div>
        </section>

        {/* 4 plan */}
        <section id="plan" className="panel rise scroll-mt-28 p-5">
          <SectionHead n="4" title="実装計画（サブタスク）" count={`${review.subtasks.length} 件`} />
          <div className="flex flex-col gap-2.5">
            {review.subtasks.map((s) => (
              <Commentable key={s.id} anchor={`st-${s.id}`} label={`subtask-${s.id}`}>
                <div className="rounded-xl border p-3.5" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[11px]" style={{ color: "var(--color-signal)" }}>subtask-{s.id}</span>
                    <span className="text-[13.5px] font-medium">{s.title}</span>
                    {s.dependsOn.length > 0 && <span className="ml-auto font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>depends_on [{s.dependsOn.join(", ")}]</span>}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {s.files.map((f) => (
                      <span key={f} className="rounded border px-1.5 py-0.5 font-mono text-[10px]" style={{ borderColor: "var(--color-line)", color: f.includes("test") ? "var(--color-cyan)" : "var(--color-ink-dim)" }}>{f}</span>
                    ))}
                  </div>
                </div>
              </Commentable>
            ))}
          </div>
        </section>

        {/* 5 prototype */}
        {review.prototypeHtml && (
          <section id="proto" className="panel rise scroll-mt-28 p-5">
            <SectionHead n="5" title="画面プロトタイプ" count="responsive" />
            <Commentable anchor="proto" label="画面プロトタイプ">
              <PrototypeFrame html={review.prototypeHtml} />
            </Commentable>
          </section>
        )}

        {/* 6 evidence */}
        {evidenceItems.length > 0 && (
          <section id="evidence" className="panel rise scroll-mt-28 p-5">
            <SectionHead n={review.prototypeHtml ? "6" : "5"} title="動作エビデンス" count={`${evidenceItems.length} 件`} />
            <p className="mb-3 text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>
              実装ブランチでの実際の動作記録。クリックで拡大、DEMO は自動再生でループします。
            </p>
            <Commentable anchor="evidence" label="動作エビデンス">
              <EvidenceGallery items={evidenceItems} />
            </Commentable>
          </section>
        )}
      </div>

      <SubmitBar issue={review.issue} />
    </>
  );
}

export function ReviewClient(props: ReviewClientProps) {
  return (
    <ReviewProvider>
      <Body {...props} />
    </ReviewProvider>
  );
}
