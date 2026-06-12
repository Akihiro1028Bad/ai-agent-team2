"use client";

import { useState } from "react";
import type { PrDiff } from "@/lib/diff";

/** PR 差分ビューア（ファイルリスト + unified diff） */
export function DiffViewer({ diff }: { diff: PrDiff }) {
  const [selected, setSelected] = useState(0);
  const file = diff.files[selected];
  const totalAdd = diff.files.reduce((s, f) => s + f.add, 0);
  const totalDel = diff.files.reduce((s, f) => s + f.del, 0);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
      {/* file list */}
      <aside className="panel self-start p-2">
        <div className="flex items-center justify-between px-2.5 py-2">
          <span className="eyebrow">{diff.files.length} files</span>
          <span className="font-mono text-[11px]">
            <span style={{ color: "var(--color-signal)" }}>+{totalAdd}</span>{" "}
            <span style={{ color: "var(--color-rose)" }}>−{totalDel}</span>
          </span>
        </div>
        {diff.files.map((f, i) => (
          <button
            key={f.path}
            onClick={() => setSelected(i)}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left"
            style={{ background: i === selected ? "var(--color-panel-2)" : "transparent" }}
          >
            <span className="min-w-0 flex-1 truncate font-mono text-[11px]" style={{ color: i === selected ? "var(--color-ink)" : "var(--color-ink-dim)" }}>
              {f.path}
            </span>
            <span className="shrink-0 font-mono text-[10px]">
              <span style={{ color: "var(--color-signal)" }}>+{f.add}</span>{" "}
              <span style={{ color: "var(--color-rose)" }}>−{f.del}</span>
            </span>
          </button>
        ))}
      </aside>

      {/* diff body */}
      <div className="panel overflow-hidden">
        <div className="border-b px-4 py-2.5 font-mono text-[12px]" style={{ borderColor: "var(--color-line)", color: "var(--color-ink-dim)" }}>
          {file.path}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-mono text-[11.5px] leading-[1.7]">
            <tbody>
              {file.lines.map((l, i) => {
                if (l.kind === "hunk") {
                  return (
                    <tr key={i}>
                      <td colSpan={3} className="px-4 py-1.5" style={{ color: "var(--color-cyan)", background: "color-mix(in srgb, var(--color-cyan) 6%, transparent)" }}>
                        {l.text}
                      </td>
                    </tr>
                  );
                }
                const bg =
                  l.kind === "add"
                    ? "color-mix(in srgb, var(--color-signal) 8%, transparent)"
                    : l.kind === "del"
                      ? "color-mix(in srgb, var(--color-rose) 9%, transparent)"
                      : "transparent";
                const mark = l.kind === "add" ? "+" : l.kind === "del" ? "−" : " ";
                const markColor = l.kind === "add" ? "var(--color-signal)" : l.kind === "del" ? "var(--color-rose)" : "var(--color-ink-faint)";
                return (
                  <tr key={i} style={{ background: bg }}>
                    <td className="w-[44px] select-none px-2 text-right" style={{ color: "var(--color-ink-faint)" }}>{l.oldNo ?? ""}</td>
                    <td className="w-[44px] select-none border-r px-2 text-right" style={{ color: "var(--color-ink-faint)", borderColor: "var(--color-line)" }}>{l.newNo ?? ""}</td>
                    <td className="whitespace-pre px-3">
                      <span className="mr-2 select-none" style={{ color: markColor }}>{mark}</span>
                      <span style={{ color: l.kind === "ctx" ? "var(--color-ink-dim)" : "var(--color-ink)" }}>{l.text}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
