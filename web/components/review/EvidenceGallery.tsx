"use client";

import { useState } from "react";
import type { Evidence } from "@/lib/evidence";
import { Portal } from "@/components/Portal";
import { IconPlay, IconTerminal, IconX } from "@/components/icons";

const KIND_META = {
  screenshot: { label: "SCREENSHOT", color: "var(--color-cyan)" },
  video: { label: "DEMO", color: "var(--color-rose)" },
  terminal: { label: "TEST RUN", color: "var(--color-signal)" },
} as const;

function FramePreview({ ev, large }: { ev: Evidence; large?: boolean }) {
  const mobile = ev.viewport === "mobile";
  if (ev.kind === "terminal") {
    return (
      <pre
        className={`overflow-auto whitespace-pre rounded-lg p-4 font-mono text-[11px] leading-[1.7] ${large ? "max-h-[70vh]" : "max-h-[180px]"}`}
        style={{ background: "var(--color-void)", color: "var(--color-ink-dim)" }}
      >
        {ev.payload}
      </pre>
    );
  }
  if (large) {
    return (
      <div className="flex justify-center">
        <iframe
          srcDoc={ev.payload}
          sandbox="allow-same-origin"
          title={ev.title}
          className="rounded-lg border bg-white"
          style={{ borderColor: "var(--color-line-2)", width: mobile ? 390 : "100%", height: "min(64vh, 560px)" }}
        />
      </div>
    );
  }
  // 縮小プレビュー（操作不可）
  return (
    <div className="relative h-[180px] overflow-hidden rounded-lg border" style={{ borderColor: "var(--color-line)" }}>
      <iframe
        srcDoc={ev.payload}
        sandbox="allow-same-origin"
        title={ev.title}
        tabIndex={-1}
        className="pointer-events-none absolute left-0 top-0 origin-top-left bg-white"
        style={{ width: mobile ? 390 : 1000, height: mobile ? 560 : 600, transform: mobile ? "scale(0.46)" : "scale(0.36)" }}
      />
      {ev.kind === "video" && (
        <span className="absolute inset-0 grid place-items-center bg-black/30">
          <span className="grid h-11 w-11 place-items-center rounded-full" style={{ background: "rgba(11,13,16,0.85)", color: "var(--color-rose)" }}>
            <IconPlay width={18} height={18} />
          </span>
        </span>
      )}
    </div>
  );
}

function Lightbox({ ev, onClose }: { ev: Evidence; onClose: () => void }) {
  const [playKey, setPlayKey] = useState(0);
  const meta = KIND_META[ev.kind];
  return (
    <Portal>
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/75 backdrop-blur-sm" onClick={onClose} />
      <div className="absolute left-1/2 top-1/2 w-[min(960px,94vw)] -translate-x-1/2 -translate-y-1/2">
        <div className="panel overflow-hidden">
          <div className="flex items-center gap-2.5 border-b px-4 py-3" style={{ borderColor: "var(--color-line)" }}>
            <span className="rounded px-1.5 py-0.5 font-mono text-[9.5px]" style={{ color: meta.color, background: `color-mix(in srgb, ${meta.color} 13%, transparent)` }}>{meta.label}</span>
            <span className="text-[13px] font-medium">{ev.title}</span>
            {ev.kind === "video" && (
              <button
                onClick={() => setPlayKey((k) => k + 1)}
                className="ml-2 inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]"
                style={{ borderColor: "var(--color-line-2)", color: "var(--color-ink-dim)" }}
              >
                <IconPlay width={11} height={11} /> 最初から再生
              </button>
            )}
            <button onClick={onClose} className="ml-auto" style={{ color: "var(--color-ink-dim)" }} aria-label="閉じる">
              <IconX width={16} height={16} />
            </button>
          </div>
          <div className="p-4">
            <div key={playKey}>
              <FramePreview ev={ev} large />
            </div>
            {ev.kind === "video" && (
              <div className="mt-3 flex items-center gap-3">
                <IconPlay width={13} height={13} style={{ color: "var(--color-rose)" }} />
                <div className="h-1 flex-1 overflow-hidden rounded-full" style={{ background: "var(--color-panel-2)" }}>
                  <div
                    key={playKey}
                    className="h-full rounded-full"
                    style={{ background: "var(--color-rose)", animation: `evprogress ${ev.durationSec ?? 9}s linear infinite` }}
                  />
                </div>
                <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>0:{String(ev.durationSec ?? 9).padStart(2, "0")} loop</span>
                <style>{`@keyframes evprogress{from{width:0%}to{width:100%}}`}</style>
              </div>
            )}
            <p className="mt-3 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>{ev.caption}</p>
          </div>
        </div>
      </div>
    </div>
    </Portal>
  );
}

/** エビデンス一覧（クリックで拡大。video は自動再生デモ） */
export function EvidenceGallery({ items }: { items: Evidence[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const open = items.find((e) => e.id === openId);

  return (
    <>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {items.map((ev) => {
          const meta = KIND_META[ev.kind];
          return (
            <button key={ev.id} onClick={() => setOpenId(ev.id)} className="group rounded-xl border p-3 text-left transition-colors hover:border-[var(--color-line-2)]" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
              <div className="mb-2 flex items-center gap-2">
                <span className="rounded px-1.5 py-0.5 font-mono text-[9.5px]" style={{ color: meta.color, background: `color-mix(in srgb, ${meta.color} 13%, transparent)` }}>
                  {meta.label}
                </span>
                <span className="truncate text-[12.5px] font-medium">{ev.title}</span>
                {ev.kind === "terminal" && <IconTerminal width={12} height={12} className="ml-auto shrink-0" style={{ color: "var(--color-ink-faint)" }} />}
              </div>
              <FramePreview ev={ev} />
              <p className="mt-2 line-clamp-2 text-[11.5px]" style={{ color: "var(--color-ink-faint)" }}>{ev.caption}</p>
            </button>
          );
        })}
      </div>
      {open && <Lightbox ev={open} onClose={() => setOpenId(null)} />}
    </>
  );
}
