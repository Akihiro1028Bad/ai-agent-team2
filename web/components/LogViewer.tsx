"use client";

import { useEffect, useRef } from "react";
import { useLogStream } from "@/lib/hooks";
import type { LogLine, LogLevel } from "@/lib/logs";
import { IconTerminal } from "./icons";

const LEVEL_COLOR: Record<LogLevel, string> = {
  info: "var(--color-ink-dim)",
  tool: "var(--color-cyan)",
  agent: "var(--color-violet)",
  warn: "var(--color-amber)",
  error: "var(--color-rose)",
  ok: "var(--color-signal)",
};

interface LogViewerProps {
  issueNumber: number;
  /** SSE 接続中の場合に接続インジケーターを表示するかどうか */
  live?: boolean;
}

/** ターミナル風のライブログ。SSE (useLogStream) でリアルタイム表示する */
export function LogViewer({ issueNumber, live = true }: LogViewerProps) {
  const { lines, connected } = useLogStream(issueNumber, live);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: "smooth" });
  }, [lines]);

  const streaming = live && connected;

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
        <span className="ml-auto font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>{lines.length} 行</span>
      </div>
      <div ref={boxRef} className="max-h-[340px] overflow-y-auto p-3.5 font-mono text-[11.5px] leading-[1.8]">
        {lines.map((l: LogLine, i: number) => (
          <div key={i} className="flex gap-2.5 whitespace-pre-wrap break-all">
            <span className="shrink-0" style={{ color: "var(--color-ink-faint)" }}>{l.t}</span>
            <span className="w-[86px] shrink-0 uppercase" style={{ color: LEVEL_COLOR[l.level] }}>[{l.source}]</span>
            <span style={{ color: l.level === "error" ? "var(--color-rose)" : /* v8 ignore next -- warn level not produced by adaptAgentLog pipeline */ l.level === "warn" ? "var(--color-amber)" : "var(--color-ink-dim)" }}>{l.text}</span>
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
