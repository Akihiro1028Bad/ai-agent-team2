"use client";

import { useState } from "react";

type Device = "desktop" | "mobile";

export function PrototypeFrame({ html }: { html: string }) {
  const [device, setDevice] = useState<Device>("desktop");
  const mobile = device === "mobile";

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <div className="inline-flex overflow-hidden rounded-lg border" style={{ borderColor: "var(--color-line)" }}>
          {(["desktop", "mobile"] as const).map((d) => (
            <button
              key={d}
              onClick={() => setDevice(d)}
              className="px-3 py-1.5 font-mono text-[11px] transition-colors"
              style={{
                color: device === d ? "#0b0d10" : "var(--color-ink-dim)",
                background: device === d ? "var(--color-cyan)" : "transparent",
              }}
            >
              {d === "desktop" ? "デスクトップ" : "モバイル"}
            </button>
          ))}
        </div>
        <span className="font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>
          {mobile ? "390 × 720" : "responsive"}
        </span>
      </div>

      <div className="flex justify-center rounded-xl border p-4" style={{ borderColor: "var(--color-line)", background: "var(--color-panel-2)" }}>
        <iframe
          title="画面プロトタイプ"
          srcDoc={html}
          sandbox="allow-same-origin"
          className="rounded-lg border bg-white transition-all"
          style={{
            borderColor: "var(--color-line-2)",
            width: mobile ? 390 : "100%",
            height: 520,
          }}
        />
      </div>
    </div>
  );
}
