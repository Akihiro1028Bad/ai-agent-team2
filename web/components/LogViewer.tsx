"use client";

import { useEffect, useRef, useState } from "react";
import type { LogLine, LogLevel } from "@/lib/logs";
import { IconPause, IconPlay, IconTerminal } from "./icons";

const LEVEL_COLOR: Record<LogLevel, string> = {
  info: "var(--color-ink-dim)",
  tool: "var(--color-cyan)",
  agent: "var(--color-violet)",
  warn: "var(--color-amber)",
  error: "var(--color-rose)",
  ok: "var(--color-signal)",
};

/** ターミナル風のライブログ。lines を順に「ストリーミング」表示する */
export function LogViewer({ lines, live = true }: { lines: LogLine[]; live?: boolean }) {
  const [count, setCount] = useState(live ? Math.min(4, lines.length) : lines.length);
  const [playing, setPlaying] = useState(live);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!playing || count >= lines.length) return;
    const t = setTimeout(() => setCount((c) => c + 1), 900 + Math.random() * 900);
    return () => clearTimeout(t);
  }, [playing, count, lines.length]);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: "smooth" });
  }, [count]);

  const visible = lines.slice(0, count);
  const streaming = playing && count < lines.length;

  return (
    <div className="overflow-hidden rounded-xl border" style={{ borderColor: "var(--color-line)", background: "var(--color-void)" }}>
      <div className="flex items-center gap-2 border-b px-3.5 py-2" style={{ borderColor: "var(--color-line)" }}>
        <IconTerminal width={13} height={13} style={{ color: "var(--color-signal)" }} />
        <span className="font-mono text-[11px]" style={{ color: "var(--color-ink-dim)" }}>agent.log</span>
        {streaming && (
          <span className="pulse ml-1" style={{ color: "var(--color-signal)" }}>
            <span className="block h-1.5 w-1.5 rounded-full" style={{ background: "var(--color-signal)" }} />
          </span>
        )}
        <span className="ml-auto font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>{visible.length} / {lines.length} 行</span>
        {live && (
          <button onClick={() => setPlaying((v) => !v)} className="grid h-6 w-6 place-items-center rounded-md border" style={{ borderColor: "var(--color-line-2)", color: "var(--color-ink-dim)" }} aria-label={playing ? "一時停止" : "再生"}>
            {playing ? <IconPause width={11} height={11} /> : <IconPlay width={11} height={11} />}
          </button>
        )}
      </div>
      <div ref={boxRef} className="max-h-[340px] overflow-y-auto p-3.5 font-mono text-[11.5px] leading-[1.8]">
        {visible.map((l, i) => (
          <div key={i} className="flex gap-2.5 whitespace-pre-wrap break-all">
            <span className="shrink-0" style={{ color: "var(--color-ink-faint)" }}>{l.t}</span>
            <span className="w-[86px] shrink-0 uppercase" style={{ color: LEVEL_COLOR[l.level] }}>[{l.source}]</span>
            <span style={{ color: l.level === "error" ? "var(--color-rose)" : l.level === "warn" ? "var(--color-amber)" : "var(--color-ink-dim)" }}>{l.text}</span>
          </div>
        ))}
        {streaming && (
          <span className="mt-1 inline-block h-3.5 w-2 animate-pulse" style={{ background: "var(--color-signal)" }} />
        )}
        {lines.length === 0 && <p style={{ color: "var(--color-ink-faint)" }}>この Issue の実行ログはありません。</p>}
      </div>
    </div>
  );
}
