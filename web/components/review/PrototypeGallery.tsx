"use client";

import { useState } from "react";
import type { Prototype } from "@/lib/api";
import { Portal } from "@/components/Portal";
import { IconArrow, IconX } from "@/components/icons";

interface PrototypeGalleryProps {
  items: Prototype[];
  notes: string[];
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
export function PrototypeGallery({ items, notes }: PrototypeGalleryProps) {
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
