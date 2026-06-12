"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type DesignView, type ReviewCommentInput } from "@/lib/api";
import { Commentable, ReviewProvider, useReview } from "./inline-review";
import { IconArrow, IconCheck } from "@/components/icons";

/** 設計書テキスト (Markdown) を 1 ブロックとして描画する (anchor 採番はしない)。 */
function Prose({ children }: { children: string }) {
  return (
    <div className="md text-[13.5px] leading-relaxed" style={{ color: "var(--color-ink-dim)" }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

function SectionHead({ n, title, count }: { n: string; title: string; count?: string }) {
  return (
    <div className="mb-3 flex items-center gap-2.5">
      <span className="grid h-6 w-6 place-items-center rounded-md font-mono text-[11px]" style={{ color: "var(--color-signal)", background: "color-mix(in srgb, var(--color-signal) 12%, transparent)" }}>{n}</span>
      <h2 className="text-[14px] font-semibold">{title}</h2>
      {count && <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>{count}</span>}
    </div>
  );
}

/**
 * レビュー提出バー (#89/#125)。
 *
 * 下書きコメントの anchor は実 design.json のサーバ anchor (sum-1/tc-01/arch-1/st-1)
 * がそのまま載るため、差し戻し feedback が設計要素へ厳密に紐づく。
 * backend が comments の有無/種別で承認/差し戻し/質問を分類するので、
 * 送信内容 (全コメント or 空) だけ渡し、結果メッセージは outcome で出し分ける。
 */
function SubmitBar({ issue, repo }: { issue: number; repo?: string }) {
  const { comments, setLocked } = useReview();
  const points = comments.filter((c) => c.tag === "指摘").length;
  const questions = comments.filter((c) => c.tag === "質問").length;
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

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
      const outcome = await api.postReview(issue, toSend, actor, repo);
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
    </div>
  );
}

const CAT_COLOR: Record<string, string> = {
  正常: "var(--color-cyan)",
  異常: "var(--color-rose)",
  境界: "var(--color-amber)",
};

/** test_cases の text 先頭にある区分ラベル (正常/異常/境界) を取り出す (表示用)。 */
function testCategory(text: string): string | null {
  for (const cat of Object.keys(CAT_COLOR)) {
    if (text.includes(cat)) return cat;
  }
  return null;
}

interface DesignReviewClientProps {
  issue: number;
  view: DesignView;
  repo?: string;
}

function Body({ issue, view, repo }: DesignReviewClientProps) {
  const { summary, architecture, testCases, subtasks, planDepth, uiImpact } = view;

  const nav = [
    ...(summary ? [{ href: "#summary", label: "概要" }] : []),
    ...(architecture.length ? [{ href: "#arch", label: "アーキテクチャ" }] : []),
    ...(testCases.length ? [{ href: "#test", label: "テスト" }] : []),
    ...(subtasks.length ? [{ href: "#plan", label: "実装計画" }] : []),
  ];

  return (
    <>
      <div className="rise mt-4">
        <div className="eyebrow">design review · plan 成果物 · インラインレビュー可</div>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <span className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>#{issue}</span>
          {planDepth && (
            <span className="rounded px-1.5 py-0.5 font-mono text-[10px]" style={{ color: "var(--color-signal)", background: "color-mix(in srgb, var(--color-signal) 12%, transparent)" }}>plan: {planDepth}</span>
          )}
          {uiImpact != null && (
            <span className="rounded px-1.5 py-0.5 font-mono text-[10px]" style={{ color: uiImpact ? "var(--color-amber)" : "var(--color-ink-faint)", background: "color-mix(in srgb, var(--color-line) 40%, transparent)" }}>
              {uiImpact ? "UI 影響あり" : "UI 影響なし"}
            </span>
          )}
        </div>
        <h1 className="mt-1.5 text-xl font-semibold tracking-tight sm:text-2xl">設計レビュー</h1>
      </div>

      {nav.length > 0 && (
        <nav className="rise sticky top-[57px] z-10 -mx-1 mt-4 flex gap-1.5 overflow-x-auto py-2 backdrop-blur-md" style={{ background: "color-mix(in srgb, var(--color-base) 80%, transparent)" }}>
          {nav.map((s) => (
            <a key={s.href} href={s.href} className="shrink-0 rounded-lg border px-3 py-1.5 text-[12.5px]" style={{ borderColor: "var(--color-line)", color: "var(--color-ink-dim)" }}>{s.label}</a>
          ))}
        </nav>
      )}

      <div className="mt-3 flex flex-col gap-5">
        {/* 概要 (sum-1) */}
        {summary && (
          <section id="summary" className="panel rise scroll-mt-28 p-5">
            <SectionHead n="1" title="概要" />
            <Commentable anchor={summary.anchor} label={`概要 (${summary.anchor})`}>
              <Prose>{summary.text}</Prose>
            </Commentable>
          </section>
        )}

        {/* アーキテクチャ (arch-1..) */}
        {architecture.length > 0 && (
          <section id="arch" className="panel rise scroll-mt-28 p-5">
            <SectionHead n="2" title="アーキテクチャ" count={`${architecture.length} 段落`} />
            <div className="flex flex-col gap-2">
              {architecture.map((a) => (
                <Commentable key={a.anchor} anchor={a.anchor} label={`アーキテクチャ (${a.anchor})`}>
                  <Prose>{a.text}</Prose>
                </Commentable>
              ))}
            </div>
          </section>
        )}

        {/* テストケース (tc-01..) */}
        {testCases.length > 0 && (
          <section id="test" className="panel rise scroll-mt-28 p-5">
            <SectionHead n="3" title="テストケース" count={`${testCases.length} ケース`} />
            <div className="flex flex-col gap-1.5">
              {testCases.map((tc) => {
                const cat = testCategory(tc.text);
                return (
                  <Commentable key={tc.anchor} anchor={tc.anchor} label={`テスト (${tc.anchor})`}>
                    <div className="flex items-start gap-2 rounded-lg border px-3 py-2 text-[12.5px]" style={{ borderColor: "var(--color-line)" }}>
                      <span className="shrink-0 font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>{tc.anchor}</span>
                      {cat && (
                        <span className="shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px]" style={{ color: CAT_COLOR[cat], background: `color-mix(in srgb, ${CAT_COLOR[cat]} 12%, transparent)` }}>{cat}</span>
                      )}
                      <span className="min-w-0 flex-1" style={{ color: "var(--color-ink-dim)" }}>{tc.text}</span>
                    </div>
                  </Commentable>
                );
              })}
            </div>
          </section>
        )}

        {/* 実装計画サブタスク (st-1..) */}
        {subtasks.length > 0 && (
          <section id="plan" className="panel rise scroll-mt-28 p-5">
            <SectionHead n="4" title="実装計画（サブタスク）" count={`${subtasks.length} 件`} />
            <div className="flex flex-col gap-2.5">
              {subtasks.map((s) => (
                <Commentable key={s.anchor} anchor={s.anchor} label={`サブタスク (${s.anchor})`}>
                  <div className="rounded-xl border p-3.5" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px]" style={{ color: "var(--color-signal)" }}>{s.anchor}</span>
                      {s.id != null && <span className="font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>id={s.id}</span>}
                      <span className="text-[13.5px] font-medium">{s.title}</span>
                    </div>
                  </div>
                </Commentable>
              ))}
            </div>
          </section>
        )}
      </div>

      <SubmitBar issue={issue} repo={repo} />
    </>
  );
}

/**
 * 設計レビュー画面 (実 design.json 駆動, #125)。
 *
 * 各 Commentable の anchor はサーバの安定 anchor をそのまま用いるため、
 * 差し戻し feedback が design.json の該当要素へ厳密に紐づく (#89 残課題の解消)。
 * Mermaid 図 / プロトタイプ / エビデンス等のリッチ要素は design.json の範囲外のため
 * 本コンポーネントでは描画しない (#90 設定 / #91 エビデンスで段階的に供給)。
 */
export function DesignReviewClient(props: DesignReviewClientProps) {
  return (
    <ReviewProvider>
      <Body {...props} />
    </ReviewProvider>
  );
}
