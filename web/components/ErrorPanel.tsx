"use client";

import type { IssueEvent } from "@/lib/types";
import { ComingSoon } from "@/components/ComingSoon";
import { IconAlert } from "./icons";

interface ErrorPanelProps {
  events: IssueEvent[];
}

/**
 * Issue イベントのうち kind==="error" なものをベストエフォートで表示する。
 * CI ログの構造化は読み取り API 未提供のため、イベント情報のみ表示し
 * データが無ければ ComingSoon を表示する。
 */
export function ErrorPanel({ events }: ErrorPanelProps) {
  if (events.length === 0) {
    return (
      <section className="rise mt-5">
        <h2 className="mb-3 text-[13px] font-semibold">エラー詳細</h2>
        <ComingSoon title="エラー詳細" note="CI ログの構造化は未提供" />
      </section>
    );
  }

  return (
    <section className="rise mt-5">
      <h2 className="mb-3 text-[13px] font-semibold">エラー詳細</h2>
      <div className="overflow-hidden rounded-2xl border" style={{ borderColor: "color-mix(in srgb, var(--color-rose) 40%, transparent)", background: "color-mix(in srgb, var(--color-rose) 4%, var(--color-panel))" }}>
        {events.map((ev) => (
          <div key={ev.id} className="flex items-start gap-3 border-b px-5 py-4 last:border-b-0" style={{ borderColor: "var(--color-line)" }}>
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg" style={{ color: "var(--color-rose)", background: "color-mix(in srgb, var(--color-rose) 13%, transparent)" }}>
              <IconAlert width={16} height={16} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-2">
                <h3 className="text-[14px] font-semibold" style={{ color: "var(--color-rose)" }}>{ev.title}</h3>
                <span className="font-mono text-[10.5px]" style={{ color: "var(--color-ink-faint)" }}>
                  {ev.at}
                </span>
              </div>
              {ev.detail != null && (
                <p className="mt-1.5 text-[13px] leading-relaxed" style={{ color: "var(--color-ink-dim)" }}>{ev.detail}</p>
              )}
            </div>
          </div>
        ))}
        <div className="px-5 py-3" style={{ borderTop: "1px solid var(--color-line)" }}>
          <p className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            CI ログ・原因分析・リカバリ操作の詳細表示は未提供です。
          </p>
        </div>
      </div>
    </section>
  );
}
