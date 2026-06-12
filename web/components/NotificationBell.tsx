"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { notifications, type NotificationKind } from "@/lib/notifications";
import { IconAlert, IconBell, IconCheck, IconGate, IconMessage } from "./icons";

const KIND_META: Record<NotificationKind, { color: string; icon: typeof IconGate }> = {
  gate: { color: "var(--color-amber)", icon: IconGate },
  error: { color: "var(--color-rose)", icon: IconAlert },
  done: { color: "var(--color-cyan)", icon: IconCheck },
  info: { color: "var(--color-signal)", icon: IconMessage },
};

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [readIds, setReadIds] = useState<Set<string>>(
    () => new Set(notifications.filter((n) => n.read).map((n) => n.id)),
  );
  const ref = useRef<HTMLDivElement>(null);

  const unread = notifications.filter((n) => !readIds.has(n.id)).length;

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const markAll = () => setReadIds(new Set(notifications.map((n) => n.id)));

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative grid h-8 w-8 place-items-center rounded-lg border"
        style={{ borderColor: "var(--color-line)", color: open ? "var(--color-ink)" : "var(--color-ink-dim)" }}
        aria-label={`通知（未読 ${unread} 件）`}
      >
        <IconBell width={15} height={15} />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full px-1 font-mono text-[9px] font-semibold" style={{ background: "var(--color-rose)", color: "#0b0d10" }}>
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-50 w-[min(380px,calc(100vw-32px))] overflow-hidden rounded-2xl border" style={{ borderColor: "var(--color-line-2)", background: "var(--color-panel)", boxShadow: "0 20px 60px -20px rgba(0,0,0,0.8)" }}>
          <div className="flex items-center justify-between border-b px-4 py-2.5" style={{ borderColor: "var(--color-line)" }}>
            <span className="text-[12.5px] font-semibold">通知</span>
            <button onClick={markAll} className="text-[11.5px]" style={{ color: "var(--color-cyan)" }}>
              すべて既読にする
            </button>
          </div>
          <div className="max-h-[60vh] overflow-y-auto p-1.5">
            {notifications.map((n) => {
              const meta = KIND_META[n.kind];
              const isRead = readIds.has(n.id);
              const inner = (
                <div
                  className="flex gap-2.5 rounded-xl px-2.5 py-2.5 transition-colors hover:bg-[var(--color-panel-2)]"
                  style={{ opacity: isRead ? 0.55 : 1 }}
                >
                  <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md" style={{ color: meta.color, background: `color-mix(in srgb, ${meta.color} 12%, transparent)` }}>
                    <meta.icon width={12} height={12} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="text-[12.5px] font-medium leading-snug">{n.title}</p>
                      <span className="shrink-0 font-mono text-[9.5px]" style={{ color: "var(--color-ink-faint)" }}>{n.at}</span>
                    </div>
                    <p className="mt-0.5 text-[11.5px] leading-snug" style={{ color: "var(--color-ink-faint)" }}>{n.body}</p>
                  </div>
                  {!isRead && <span className="mt-1.5 block h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: "var(--color-signal)" }} />}
                </div>
              );
              return n.href ? (
                <Link
                  key={n.id}
                  href={n.href}
                  onClick={() => {
                    setReadIds((prev) => new Set([...prev, n.id]));
                    setOpen(false);
                  }}
                  className="block"
                >
                  {inner}
                </Link>
              ) : (
                <div key={n.id}>{inner}</div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
