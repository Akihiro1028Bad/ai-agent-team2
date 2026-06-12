"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useState, type SVGProps } from "react";
import { api, adaptHealth } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import type { HealthItem } from "@/lib/health";
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
}

const NAV: NavItem[] = [
  { href: "/", label: "ダッシュボード", icon: IconGrid, exact: true },
  { href: "/approvals", label: "承認待ち", icon: IconInbox },
  { href: "/queue", label: "実行キュー", icon: IconLayers },
  { href: "/timeline", label: "タイムライン", icon: IconGantt },
  { href: "/costs", label: "コスト", icon: IconDollar },
  { href: "/knowledge", label: "ナレッジ", icon: IconBrain },
  { href: "/health", label: "ヘルスモニタ", icon: IconHeart },
  { href: "/settings", label: "制御・設定", icon: IconSliders },
];

interface HealthSummary {
  color: string;
  label: string;
}

/** ヘルス項目から最悪ステータスの概況 (色・ラベル) を導く。 */
function summarizeHealth(items: HealthItem[], offline: boolean): HealthSummary {
  if (offline) return { color: "var(--color-rose)", label: "OFFLINE" };
  if (items.length === 0) return { color: "var(--color-ink-faint)", label: "…" };
  const errors = items.filter((h) => h.status === "error").length;
  const warns = items.filter((h) => h.status === "warn").length;
  if (errors > 0) return { color: "var(--color-rose)", label: `${errors} ERROR` };
  if (warns > 0) return { color: "var(--color-amber)", label: `${warns} WARN` };
  return { color: "var(--color-signal)", label: "ALL GO" };
}

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
          </Link>
        );
      })}
    </nav>
  );
}

function SidebarInner({ pathname, health, onNav }: { pathname: string; health: HealthSummary; onNav?: () => void }) {
  return (
    <div className="flex h-full flex-col gap-6 p-5">
      <Brand />
      <NavList pathname={pathname} onNav={onNav} />
      <div className="mt-auto">
        <Link href="/health" onClick={onNav} className="panel block p-3 transition-colors hover:border-[var(--color-line-2)]">
          <div className="eyebrow mb-2">system health</div>
          <div className="flex items-center gap-2">
            <span className="block h-2 w-2 rounded-full" style={{ background: health.color }} />
            <span className="font-mono text-[11.5px]" style={{ color: health.color }}>{health.label}</span>
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

  // 稼働状態・ヘルス概況を GET /api/health にライブ接続 (#86)。
  /* v8 ignore start -- usePolling callback mocked in tests; api.getHealth is tested separately */
  const healthState = usePolling(useCallback((signal: AbortSignal) => api.getHealth(signal), []), 5000);
  /* v8 ignore stop */
  const offline = healthState.error !== undefined && healthState.data === undefined;
  const running = healthState.data?.running === true && healthState.data.stale !== true;
  const repoCount = healthState.data?.repositories.length ?? 0;
  const healthItems = healthState.data ? adaptHealth(healthState.data) : [];
  const healthSummary = summarizeHealth(healthItems, offline);

  return (
    <div className="flex min-h-dvh">
      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-[248px] shrink-0 border-r lg:block" style={{ borderColor: "var(--color-line)" }}>
        <SidebarInner pathname={pathname} health={healthSummary} />
      </aside>

      {/* mobile slide-over */}
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-[270px] border-r bg-base" style={{ background: "var(--color-base)", borderColor: "var(--color-line)" }}>
            <button onClick={() => setOpen(false)} className="absolute right-3 top-4 text-ink-dim" aria-label="閉じる">
              <IconX />
            </button>
            <SidebarInner pathname={pathname} health={healthSummary} onNav={() => setOpen(false)} />
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
              {offline ? "OFFLINE" : running ? "RUNNING" : "STOPPED"}
            </span>
            <span className="hidden font-mono text-[11px] text-ink-faint sm:inline" style={{ color: "var(--color-ink-faint)" }}>
              · {repoCount} repos
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
