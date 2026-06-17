"use client";

import { useEffect, useState } from "react";
import { api, type KnowledgeView } from "@/lib/api";

/**
 * 自己改善ループ（#93）の可視化クライアント。
 * GET /api/knowledge を 1 回取得し、エピソード→パターン→Skill の流れを表示する。
 */
export function KnowledgeClient() {
  const [view, setView] = useState<KnowledgeView | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const ac = new AbortController();
    api
      .getKnowledge(ac.signal)
      .then((v) => {
        if (!ac.signal.aborted) setView(v);
      })
      .catch(() => {
        if (!ac.signal.aborted) setFailed(true);
      });
    return () => ac.abort();
  }, []);

  if (failed) {
    return (
      <p className="text-[13px]" style={{ color: "var(--color-ink-faint)" }}>
        ナレッジの取得に失敗しました。オーケストレーター API が起動しているか確認してください。
      </p>
    );
  }
  if (!view) {
    return (
      <p className="text-[13px]" style={{ color: "var(--color-ink-faint)" }}>
        読み込み中…
      </p>
    );
  }

  const { stats } = view;
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="エピソード" value={String(stats.episodes)} />
        <Stat label="成功率" value={`${Math.round(stats.successRate * 100)}%`} />
        <Stat label="パターン" value={String(stats.patterns)} />
        <Stat label="Skill" value={String(stats.skills)} />
      </div>

      {stats.episodes === 0 ? (
        <p className="text-[13px]" style={{ color: "var(--color-ink-faint)" }}>
          まだエピソードがありません。フェーズが完了すると自動で記録されます。
        </p>
      ) : (
        <>
          <Section title="抽出パターン" eyebrow="extracted patterns">
            {view.patterns.length === 0 ? (
              <Empty>まだ繰り返しパターンは検出されていません。</Empty>
            ) : (
              view.patterns.map((p) => (
                <div key={p.id} className="panel p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium">{p.title}</span>
                    <span
                      className="rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold"
                      style={{
                        background: p.status === "promoted" ? "var(--color-signal)" : "var(--color-line)",
                        color: p.status === "promoted" ? "#0b0d10" : "var(--color-ink-dim)",
                      }}
                    >
                      {p.status === "promoted" ? "昇格済み" : "候補"}
                    </span>
                  </div>
                  <p className="mt-1 text-[12px]" style={{ color: "var(--color-ink-dim)" }}>
                    {p.description}
                  </p>
                  <p className="mt-1 text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                    {p.occurrences} 回観測 / 確信度 {Math.round(p.confidence * 100)}%
                  </p>
                </div>
              ))
            )}
          </Section>

          <Section title="生成 Skill" eyebrow="generated skills">
            {view.skills.length === 0 ? (
              <Empty>昇格済みパターンから生成された Skill はまだありません。</Empty>
            ) : (
              view.skills.map((s) => (
                <div key={s.id} className="panel flex items-center justify-between gap-2 p-3">
                  <span className="font-mono text-[12.5px]">{s.name}</span>
                  <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                    更新 {s.updated}
                  </span>
                </div>
              ))
            )}
          </Section>

          <Section title="最近のエピソード" eyebrow="episodes">
            {view.episodes.map((e) => (
              <div key={e.id} className="panel p-3">
                <div className="flex items-center gap-2">
                  <span
                    className="rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold"
                    style={{
                      background: e.outcome === "success" ? "var(--color-cyan)" : "var(--color-rose)",
                      color: "#0b0d10",
                    }}
                  >
                    {e.outcome === "success" ? "成功" : "失敗"}
                  </span>
                  <span className="text-[12px]" style={{ color: "var(--color-ink-dim)" }}>
                    {e.repo}#{e.issue} / {e.phase}
                  </span>
                  <span className="ml-auto text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                    {e.at}
                  </span>
                </div>
                <p className="mt-1 text-[12.5px]">{e.summary}</p>
                {e.lesson && (
                  <p className="mt-1 text-[12px]" style={{ color: "var(--color-ink-dim)" }}>
                    教訓: {e.lesson}
                  </p>
                )}
              </div>
            ))}
          </Section>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel p-3">
      <div className="eyebrow">{label}</div>
      <div className="mt-1 text-xl font-semibold tracking-tight">{value}</div>
    </div>
  );
}

function Section({ title, eyebrow, children }: { title: string; eyebrow: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <div className="eyebrow">{eyebrow}</div>
      <h2 className="text-[14px] font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[12.5px]" style={{ color: "var(--color-ink-faint)" }}>
      {children}
    </p>
  );
}
