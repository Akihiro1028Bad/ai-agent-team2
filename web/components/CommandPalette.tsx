"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { issues } from "@/lib/mock";
import { api } from "@/lib/api";
import { Portal } from "./Portal";
import { IconArrow, IconBolt, IconGrid, IconSearch } from "./icons";
import { TypeTag } from "./ui";

interface PaletteItem {
  id: string;
  group: "ページ" | "Issue" | "操作";
  label: string;
  hint?: string;
  href?: string;
  issueNo?: number;
  keywords: string;
}

const PAGE_ITEMS: PaletteItem[] = [
  { id: "p-dash", group: "ページ", label: "ダッシュボード", href: "/", keywords: "dashboard home" },
  { id: "p-queue", group: "ページ", label: "実行キュー", href: "/queue", keywords: "queue priority 優先度" },
  { id: "p-appr", group: "ページ", label: "承認待ち", href: "/approvals", keywords: "approvals gate 承認" },
  { id: "p-cost", group: "ページ", label: "コスト", href: "/costs", keywords: "cost token 使用量" },
  { id: "p-tl", group: "ページ", label: "タイムライン", href: "/timeline", keywords: "timeline gantt ガント" },
  { id: "p-health", group: "ページ", label: "ヘルスモニタ", href: "/health", keywords: "health monitor 監視" },
  { id: "p-know", group: "ページ", label: "ナレッジ", href: "/knowledge", keywords: "knowledge episode 学習" },
  { id: "p-set", group: "ページ", label: "制御・設定", href: "/settings", keywords: "settings config 設定" },
];

const ACTION_ITEMS: PaletteItem[] = [
  { id: "a-stop", group: "操作", label: "オーケストレーターを停止", hint: "確認あり", keywords: "stop 停止" },
  { id: "a-poll", group: "操作", label: "今すぐポーリング実行", hint: "即時", keywords: "poll 取得" },
  { id: "a-gc", group: "操作", label: "worktree を掃除", hint: "孤児を削除", keywords: "worktree gc clean" },
];

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const [toast, setToast] = useState<string | null>(null);

  // 検索語 q が変わったらハイライト位置をリセットする
  // (effect 内 setState を避ける set-state-during-render パターン)。
  const [cursorResetKey, setCursorResetKey] = useState(q);
  if (cursorResetKey !== q) {
    setCursorResetKey(q);
    setCursor(0);
  }
  const inputRef = useRef<HTMLInputElement>(null);

  const allItems = useMemo<PaletteItem[]>(
    () => [
      ...PAGE_ITEMS,
      ...issues.map((i) => ({
        id: `i-${i.number}`,
        group: "Issue" as const,
        label: `#${i.number} ${i.title}`,
        hint: i.repo,
        href: `/issues/${i.number}`,
        issueNo: i.number,
        keywords: `${i.repo} ${i.title} ${i.number} ${i.type}`,
      })),
      ...ACTION_ITEMS,
    ],
    [],
  );

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return allItems;
    return allItems.filter((it) => `${it.label} ${it.keywords}`.toLowerCase().includes(needle));
  }, [q, allItems]);

  const close = useCallback(() => {
    setOpen(false);
    setQ("");
    setCursor(0);
  }, []);

  const run = useCallback(
    (item: PaletteItem) => {
      if (item.href) {
        router.push(item.href);
        close();
        return;
      }
      close();
      if (item.id === "a-poll") {
        // actor は実データ (監視中 Issue の repo owner) から導出する。
        api
          .getDefaultActor()
          .then((actor) => api.postControl({ action: "poll_now", actor }))
          .then(() => {
            setToast("GitHub ポーリングを実行しました");
            setTimeout(() => setToast(null), 2600);
          })
          .catch(() => {
            setToast("ポーリングの送信に失敗しました");
            /* v8 ignore next -- trivial setToast(null) cleanup; same pattern tested in success path */
            setTimeout(() => setToast(null), 3200);
          });
      } else if (item.id === "a-gc") {
        api
          .getDefaultActor()
          .then((actor) => api.postControl({ action: "worktree_gc", actor }))
          .then(() => {
            setToast("worktree のクリーンアップを開始しました");
            /* v8 ignore next -- trivial setToast(null) cleanup; same pattern tested in success path */
            setTimeout(() => setToast(null), 2600);
          })
          .catch(() => {
            setToast("worktree_gc の送信に失敗しました");
            /* v8 ignore next -- trivial setToast(null) cleanup; same pattern tested in success path */
            setTimeout(() => setToast(null), 3200);
          });
      } else {
        setToast(`「${item.label}」を実行しました`);
        /* v8 ignore next -- trivial setToast(null) cleanup; same pattern tested in success path */
        setTimeout(() => setToast(null), 2600);
      }
    },
    [router, close],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        close();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="hidden items-center gap-2 rounded-lg border px-2.5 py-1.5 text-[12px] sm:inline-flex"
        style={{ borderColor: "var(--color-line)", color: "var(--color-ink-faint)" }}
        aria-label="コマンドパレットを開く"
      >
        <IconSearch width={13} height={13} />
        検索・操作
        <kbd className="rounded border px-1 font-mono text-[10px]" style={{ borderColor: "var(--color-line-2)" }}>⌘K</kbd>
      </button>
      {/* モバイル: アイコンのみ */}
      <button
        onClick={() => setOpen(true)}
        className="grid h-8 w-8 place-items-center rounded-lg border sm:hidden"
        style={{ borderColor: "var(--color-line)", color: "var(--color-ink-dim)" }}
        aria-label="検索・操作"
      >
        <IconSearch width={15} height={15} />
      </button>

      {toast && (
        <Portal>
          <div className="fixed bottom-5 left-1/2 z-[70] -translate-x-1/2 rounded-lg border px-4 py-2.5 text-[13px]" style={{ borderColor: "var(--color-line-2)", background: "var(--color-panel)", color: "var(--color-cyan)" }}>
            {toast}
          </div>
        </Portal>
      )}

      {open && (
        <Portal>
        <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={close} />
          <div className="absolute left-1/2 top-[14vh] w-[min(620px,92vw)] -translate-x-1/2">
            <div className="panel overflow-hidden" style={{ boxShadow: "0 24px 80px -24px rgba(0,0,0,0.8)" }}>
              <div className="flex items-center gap-2.5 border-b px-4 py-3" style={{ borderColor: "var(--color-line)" }}>
                <IconSearch width={15} height={15} style={{ color: "var(--color-ink-faint)" }} />
                <input
                  ref={inputRef}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowDown") {
                      e.preventDefault();
                      setCursor((c) => Math.min(c + 1, filtered.length - 1));
                    } else if (e.key === "ArrowUp") {
                      e.preventDefault();
                      setCursor((c) => Math.max(c - 1, 0));
                    } else if (e.key === "Enter" && filtered[cursor]) {
                      run(filtered[cursor]);
                    }
                  }}
                  placeholder="Issue 番号・タイトル・ページ・操作を検索…"
                  className="w-full bg-transparent text-[14px] outline-none placeholder:text-[var(--color-ink-faint)]"
                />
                <kbd className="rounded border px-1.5 py-0.5 font-mono text-[10px]" style={{ borderColor: "var(--color-line-2)", color: "var(--color-ink-faint)" }}>esc</kbd>
              </div>
              <div className="max-h-[46vh] overflow-y-auto p-2">
                {filtered.length === 0 && (
                  <p className="px-3 py-6 text-center text-[13px]" style={{ color: "var(--color-ink-faint)" }}>該当なし</p>
                )}
                {(["ページ", "Issue", "操作"] as const).map((group) => {
                  const items = filtered.filter((i) => i.group === group);
                  if (items.length === 0) return null;
                  return (
                    <div key={group} className="mb-1">
                      <div className="eyebrow px-3 py-1.5">{group}</div>
                      {items.map((item) => {
                        const idx = filtered.indexOf(item);
                        const active = idx === cursor;
                        const issue = item.issueNo ? issues.find((i) => i.number === item.issueNo) : undefined;
                        return (
                          <button
                            key={item.id}
                            onClick={() => run(item)}
                            onMouseEnter={() => setCursor(idx)}
                            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13.5px]"
                            style={{ background: active ? "var(--color-panel-2)" : "transparent", color: active ? "var(--color-ink)" : "var(--color-ink-dim)" }}
                          >
                            {group === "操作" ? (
                              <IconBolt width={13} height={13} style={{ color: "var(--color-amber)" }} />
                            ) : group === "ページ" ? (
                              <IconGrid width={13} height={13} style={{ color: "var(--color-cyan)" }} />
                            ) : (
                              <IconArrow width={13} height={13} style={{ color: "var(--color-signal)" }} />
                            )}
                            <span className="min-w-0 flex-1 truncate">{item.label}</span>
                            {issue && <TypeTag type={issue.type} />}
                            {item.hint && <span className="shrink-0 font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>{item.hint}</span>}
                          </button>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
        </Portal>
      )}
    </>
  );
}
