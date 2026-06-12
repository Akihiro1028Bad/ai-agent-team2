"use client";

import Link from "next/link";
import { useState } from "react";
import { PRIORITY_META, queueEntries, type QueueEntry } from "@/lib/queue";
import { TypeTag } from "@/components/ui";
import { IconCheck, IconDown, IconUp } from "@/components/icons";

function move(list: QueueEntry[], from: number, to: number): QueueEntry[] {
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

function setPriority(list: QueueEntry[], idx: number, priority: QueueEntry["priority"]): QueueEntry[] {
  return list.map((e, i) => (i === idx ? { ...e, priority } : e));
}

export default function QueuePage() {
  const [entries, setEntries] = useState(queueEntries);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  const update = (next: QueueEntry[]) => {
    setEntries(next);
    setDirty(true);
    setSavedAt(null);
  };

  return (
    <div className="mx-auto max-w-[900px]">
      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">task queue</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">実行キュー</h1>
        </div>
        <p className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
          {entries.length} 件待機 · 実行枠 3/4 使用中
        </p>
      </div>

      <p className="rise mt-2 text-[12.5px]" style={{ color: "var(--color-ink-dim)", animationDelay: "40ms" }}>
        上から順に実行枠が空き次第ピックアップされます。矢印で並べ替え、優先度を変更できます。
      </p>

      <div className="rise mt-5 flex flex-col gap-3" style={{ animationDelay: "80ms" }}>
        {entries.map((e, i) => {
          const pm = PRIORITY_META[e.priority];
          return (
            <div key={e.issue} className="panel flex items-center gap-3 p-4">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg font-mono text-[13px] font-semibold" style={{ color: "var(--color-ink-dim)", background: "var(--color-panel-2)" }}>
                {i + 1}
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link href={`/issues/${e.issue}`} className="font-mono text-[11.5px]" style={{ color: "var(--color-ink-faint)" }}>
                    {e.repo}#{e.issue}
                  </Link>
                  <TypeTag type={e.type} />
                  <button
                    onClick={() => {
                      const order = ["high", "normal", "low"] as const;
                      const next = order[(order.indexOf(e.priority) + 1) % order.length];
                      update(setPriority(entries, i, next));
                    }}
                    className="rounded px-1.5 py-0.5 font-mono text-[10px] sm:pointer-events-none"
                    style={{ color: pm.color, background: `color-mix(in srgb, ${pm.color} 12%, transparent)` }}
                    title="タップで優先度を切替"
                  >
                    優先度: {pm.label}
                  </button>
                </div>
                <h3 className="mt-1 truncate text-[14px] font-medium">{e.title}</h3>
                <p className="mt-0.5 text-[11.5px]" style={{ color: "var(--color-ink-faint)" }}>{e.reason} · 投入 {e.enqueued}</p>
              </div>

              {/* priority buttons */}
              <div className="hidden shrink-0 gap-1 sm:flex">
                {(["high", "normal", "low"] as const).map((p) => (
                  <button
                    key={p}
                    onClick={() => update(setPriority(entries, i, p))}
                    className="rounded-md border px-2 py-1 font-mono text-[10px]"
                    style={{
                      borderColor: e.priority === p ? PRIORITY_META[p].color : "var(--color-line)",
                      color: e.priority === p ? PRIORITY_META[p].color : "var(--color-ink-faint)",
                    }}
                  >
                    {PRIORITY_META[p].label}
                  </button>
                ))}
              </div>

              {/* reorder */}
              <div className="flex shrink-0 flex-col gap-1">
                <button
                  onClick={() => update(move(entries, i, i - 1))}
                  disabled={i === 0}
                  className="grid h-6 w-6 place-items-center rounded-md border disabled:opacity-25"
                  style={{ borderColor: "var(--color-line-2)", color: "var(--color-ink-dim)" }}
                  aria-label="上へ"
                >
                  <IconUp width={12} height={12} />
                </button>
                <button
                  onClick={() => update(move(entries, i, i + 1))}
                  disabled={i === entries.length - 1}
                  className="grid h-6 w-6 place-items-center rounded-md border disabled:opacity-25"
                  style={{ borderColor: "var(--color-line-2)", color: "var(--color-ink-dim)" }}
                  aria-label="下へ"
                >
                  <IconDown width={12} height={12} />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* save bar */}
      <div className="rise sticky bottom-4 mt-5" style={{ animationDelay: "140ms" }}>
        <div className="panel flex items-center gap-3 p-3" style={{ background: "color-mix(in srgb, var(--color-panel) 92%, black)" }}>
          {savedAt ? (
            <span className="inline-flex items-center gap-2 px-2 text-[13px]" style={{ color: "var(--color-cyan)" }}>
              <IconCheck width={14} height={14} /> キューの順序を保存しました（{savedAt}）
            </span>
          ) : (
            <span className="px-2 text-[12.5px]" style={{ color: dirty ? "var(--color-amber)" : "var(--color-ink-faint)" }}>
              {dirty ? "未保存の変更があります" : "変更はありません"}
            </span>
          )}
          <button
            onClick={() => {
              setSavedAt(new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" }));
              setDirty(false);
            }}
            disabled={!dirty}
            className="ml-auto rounded-lg px-4 py-2 text-[13px] font-semibold disabled:opacity-40"
            style={{ color: "#0b0d10", background: "var(--color-signal)" }}
          >
            順序を保存
          </button>
        </div>
      </div>
    </div>
  );
}
