"use client";

import { useEffect, useState } from "react";
import { api, actorForRepo, type Prototype } from "@/lib/api";
import { Portal } from "@/components/Portal";
import { IconArrow, IconCheck, IconX } from "@/components/icons";

interface PrototypeGalleryProps {
  items: Prototype[];
  notes: string[];
  /** 対象 Issue 番号（修正依頼の送信先, #145 Phase2）。 */
  issue?: number;
  /** 一覧→詳細から引き回した repo（actor 導出に使う）。 */
  repo?: string;
  /** 反復回数（#145 Phase2）。1 以上で「更新済み」バッジを表示。 */
  iteration?: number;
}

/** sandbox iframe でプロトタイプを描画する。allow-same-origin は付けない（不透明オリジン隔離, #145）。 */
function Frame({ url, title, large }: { url: string; title: string; large?: boolean }) {
  return (
    <iframe
      src={url}
      title={title}
      sandbox="allow-scripts"
      loading="lazy"
      className="w-full rounded-lg border bg-white"
      style={{ borderColor: "var(--color-line)", height: large ? "78vh" : "420px" }}
    />
  );
}

/**
 * UI プロトタイプ・ギャラリー (#145)。
 *
 * PLAN が生成した自己完結 HTML を承認前に「動くプレビュー」として表示する。
 * iframe は sandbox="allow-scripts"（allow-same-origin 無し）で隔離し、拡大表示も可能。
 */
export function PrototypeGallery({ items, notes, issue, repo, iteration = 0 }: PrototypeGalleryProps) {
  const [expanded, setExpanded] = useState<Prototype | null>(null);

  if (items.length === 0) {
    return (
      <p className="text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>
        {notes[0] ?? "この Issue にはまだ UI プロトタイプがありません。"}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {iteration > 1 && (
        <span
          className="inline-flex w-fit items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium"
          style={{ background: "var(--color-line)", color: "var(--color-ink-dim)" }}
        >
          更新済み（{iteration} 回目）
        </span>
      )}
      {items.map((p) => (
        <div key={p.id} className="panel p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-[13px] font-medium">{p.title}</span>
            <div className="flex items-center gap-3">
              <a
                href={p.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[12px]"
                style={{ color: "var(--color-ink-dim)" }}
              >
                新しいタブで開く <IconArrow width={12} height={12} />
              </a>
              <button
                type="button"
                onClick={() => setExpanded(p)}
                className="text-[12px]"
                style={{ color: "var(--color-signal)" }}
              >
                拡大
              </button>
            </div>
          </div>
          <Frame url={p.url} title={p.title} />
        </div>
      ))}

      {issue !== undefined && <PrototypeFeedbackForm issue={issue} repo={repo} iteration={iteration} />}

      {expanded && (
        <Portal>
          <div
            className="fixed inset-0 z-50 flex flex-col bg-[color-mix(in_srgb,var(--color-base)_92%,black)] p-4"
            onClick={() => setExpanded(null)}
          >
            <div className="mb-2 flex items-center justify-between" onClick={(e) => e.stopPropagation()}>
              <span className="text-[13px] font-medium">{expanded.title}</span>
              <button
                type="button"
                onClick={() => setExpanded(null)}
                className="inline-flex items-center gap-1 text-[12.5px]"
                style={{ color: "var(--color-ink-dim)" }}
                aria-label="閉じる"
              >
                <IconX width={14} height={14} /> 閉じる
              </button>
            </div>
            <div className="min-h-0 flex-1" onClick={(e) => e.stopPropagation()}>
              <Frame url={expanded.url} title={expanded.title} large />
            </div>
          </div>
        </Portal>
      )}
    </div>
  );
}

/**
 * プロトタイプ修正依頼フォーム (#145 Phase2)。
 *
 * 「ここ直して」を送ると prototype_revise として control.jsonl に載り、PLAN が
 * 再実行されてプロトタイプが更新される。送信後は再生成を待つ旨を表示する。
 */
function PrototypeFeedbackForm({ issue, repo, iteration }: { issue: number; repo?: string; iteration: number }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // 再生成が完了する (iteration が増える) と送信済み表示を解除し、次の反復を受け付ける (#145 Phase2)。
  useEffect(() => {
    setDone(false);
  }, [iteration]);

  const submit = async () => {
    const feedback = text.trim();
    if (!feedback) return;
    setSending(true);
    setErrorMsg(null);
    try {
      await api.sendPrototypeFeedback(issue, feedback, actorForRepo(repo ?? ""), repo);
      setDone(true);
      setText("");
    } catch {
      setErrorMsg("修正依頼の送信に失敗しました。少し待ってから再試行してください。");
    } finally {
      setSending(false);
    }
  };

  if (done) {
    return (
      <div className="panel flex items-start gap-2 p-3">
        <IconCheck width={15} height={15} className="mt-0.5 shrink-0" style={{ color: "var(--color-cyan)" }} />
        <p className="text-[12.5px] leading-relaxed" style={{ color: "var(--color-cyan)" }}>
          修正依頼を送信しました。プロトタイプを再生成しています。更新後にプレビューが差し替わります。
        </p>
      </div>
    );
  }

  return (
    <div className="panel flex flex-col gap-2 p-3">
      <span className="eyebrow">このUIを修正依頼</span>
      <p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
        例:「左のメニューを上部タブに」「色をもっと落ち着いた配色に」。送信すると案が再生成されます。
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="直してほしい点を具体的に書いてください"
        className="resize-none rounded-lg border bg-transparent px-3 py-2 text-[12.5px] outline-none focus:border-[var(--color-line-2)]"
        style={{ borderColor: "var(--color-line)" }}
      />
      {errorMsg && (
        <p className="text-[12px]" style={{ color: "var(--color-rose)" }}>
          {errorMsg}
        </p>
      )}
      <button
        type="button"
        onClick={() => void submit()}
        disabled={!text.trim() || sending}
        className="w-fit rounded-lg px-3.5 py-1.5 text-[12.5px] font-semibold disabled:opacity-40"
        style={{ color: "#0b0d10", background: "var(--color-signal)" }}
      >
        {sending ? "送信中…" : "修正を依頼"}
      </button>
    </div>
  );
}
