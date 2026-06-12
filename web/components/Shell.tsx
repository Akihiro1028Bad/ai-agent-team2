"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type SVGProps } from "react";
import { gates, orchestrator } from "@/lib/mock";
import { healthItems } from "@/lib/health";
import { queueEntries } from "@/lib/queue";
import { CommandPalette } from "./CommandPalette";
import { NotificationBell } from "./NotificationBell";
import {
  IconBrain,
  IconDollar,
  IconGantt,
  IconGrid,
  IconHeart,
  IconInbox,
  IconLayers,
  IconMenu,
  IconSliders,
  IconX,
} from "./icons";

interface NavItem {
  href: string;
  label: string;
  icon: (p: SVGProps<SVGSVGElement>) => React.ReactElement;
  exact?: boolean;
  badge?: number;
}

const NAV: NavItem[] = [
  { href: "/", label: "ダッシュボード", icon: IconGrid, exact: true },
  { href: "/approvals", label: "承認待ち", icon: IconInbox, badge: gates.length },
  { href: "/queue", label: "実行キュー", icon: IconLayers, badge: queueEntries.length },
  { href: "/timeline", label: "タイムライン", icon: IconGantt },
  { href: "/costs", label: "コスト", icon: IconDollar },
  { href: "/knowledge", label: "ナレッジ", icon: IconBrain },
  { href: "/health", label: "ヘルスモニタ", icon: IconHeart },
  { href: "/settings", label: "制御・設定", icon: IconSliders },
];

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="grid h-8 w-8 place-items-center rounded-lg border border-line-2 bg-panel-2">
        <span className="block h-2.5 w-2.5 rounded-sm bg-signal glow-signal" />
      </span>
      <div className="leading-tight">
        <div className="font-mono text-[13px] font-semibold tracking-tight">ORCHESTRATOR</div>
        <div className="eyebrow !text-[9px]">control room</div>
      </div>
    </div>
  );
}

function NavList({ pathname, onNav }: { pathname: string; onNav?: () => void }) {
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map((item) => {
        const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNav}
            className="group relative flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] transition-colors"
            style={{
              color: active ? "var(--color-ink)" : "var(--color-ink-dim)",
              background: active ? "var(--color-panel-2)" : "transparent",
            }}
          >
            {active && <span className="absolute left-0 top-1/2 h-5 -translate-y-1/2 w-[3px] rounded-r bg-signal" />}
            <item.icon style={{ color: active ? "var(--color-signal)" : "currentColor" }} />
            <span>{item.label}</span>
            {"badge" in item && item.badge ? (
              <span className="ml-auto rounded-full bg-amber/15 px-1.5 py-0.5 font-mono text-[10px] text-amber" style={{ color: "var(--color-amber)", background: "color-mix(in srgb, var(--color-amber) 15%, transparent)" }}>
                {item.badge}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

const worstHealth = healthItems.some((h) => h.status === "error")
  ? "error"
  : healthItems.some((h) => h.status === "warn")
    ? "warn"
    : "ok";
const healthColor =
  worstHealth === "error" ? "var(--color-rose)" : worstHealth === "warn" ? "var(--color-amber)" : "var(--color-signal)";
const healthLabel =
  worstHealth === "error"
    ? `${healthItems.filter((h) => h.status === "error").length} ERROR`
    : worstHealth === "warn"
      ? `${healthItems.filter((h) => h.status === "warn").length} WARN`
      : "ALL GO";

function SidebarInner({ pathname, onNav }: { pathname: string; onNav?: () => void }) {
  return (
    <div className="flex h-full flex-col gap-6 p-5">
      <Brand />
      <NavList pathname={pathname} onNav={onNav} />
      <div className="mt-auto">
        <Link href="/health" onClick={onNav} className="panel block p-3 transition-colors hover:border-[var(--color-line-2)]">
          <div className="eyebrow mb-2">system health</div>
          <div className="flex items-center gap-2">
            <span className="block h-2 w-2 rounded-full" style={{ background: healthColor }} />
            <span className="font-mono text-[11.5px]" style={{ color: healthColor }}>{healthLabel}</span>
            <span className="ml-auto font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>詳細 →</span>
          </div>
        </Link>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const running = orchestrator.running;

  return (
    <div className="flex min-h-dvh">
      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-[248px] shrink-0 border-r lg:block" style={{ borderColor: "var(--color-line)" }}>
        <SidebarInner pathname={pathname} />
      </aside>

      {/* mobile slide-over */}
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-[270px] border-r bg-base" style={{ background: "var(--color-base)", borderColor: "var(--color-line)" }}>
            <button onClick={() => setOpen(false)} className="absolute right-3 top-4 text-ink-dim" aria-label="閉じる">
              <IconX />
            </button>
            <SidebarInner pathname={pathname} onNav={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* top bar */}
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b px-4 py-3 backdrop-blur-md sm:px-6" style={{ borderColor: "var(--color-line)", background: "color-mix(in srgb, var(--color-base) 82%, transparent)" }}>
          <button className="lg:hidden text-ink-dim" onClick={() => setOpen(true)} aria-label="メニュー">
            <IconMenu width={20} height={20} />
          </button>

          <div className="flex items-center gap-2">
            <span className="pulse" style={{ color: running ? "var(--color-signal)" : "var(--color-ink-faint)" }}>
              <span className="block h-2 w-2 rounded-full" style={{ background: running ? "var(--color-signal)" : "var(--color-ink-faint)" }} />
            </span>
            <span className="font-mono text-[12px]" style={{ color: running ? "var(--color-ink)" : "var(--color-ink-dim)" }}>
              {running ? "RUNNING" : "STOPPED"}
            </span>
            <span className="hidden font-mono text-[11px] text-ink-faint sm:inline" style={{ color: "var(--color-ink-faint)" }}>
              · {orchestrator.account} · poll {orchestrator.pollingIntervalSec}s
            </span>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <CommandPalette />
            <NotificationBell />
          </div>
        </header>

        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
