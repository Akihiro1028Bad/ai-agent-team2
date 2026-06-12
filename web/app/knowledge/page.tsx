import Link from "next/link";
import { episodes, knowledgeStats, patterns } from "@/lib/knowledge";
import { SkillStudio } from "@/components/SkillStudio";
import { IconBrain, IconCheck, IconX } from "@/components/icons";

export default function KnowledgePage() {
  return (
    <div className="mx-auto max-w-[1100px]">
      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">self-improvement loop</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">ナレッジ</h1>
        </div>
        <p className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
          episodes {knowledgeStats.episodes} · success {Math.round(knowledgeStats.successRate * 100)}% · patterns {knowledgeStats.patterns} · skills {knowledgeStats.skills}
        </p>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-5 xl:grid-cols-[1fr_380px]">
        {/* episodes */}
        <section className="rise" style={{ animationDelay: "60ms" }}>
          <h2 className="mb-3 text-[13px] font-semibold">エピソード記憶（直近）</h2>
          <div className="flex flex-col gap-3">
            {episodes.map((ep) => {
              const ok = ep.outcome === "success";
              const c = ok ? "var(--color-signal)" : "var(--color-rose)";
              return (
                <div key={ep.id} className="panel p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px]" style={{ borderColor: `color-mix(in srgb, ${c} 35%, transparent)`, color: c }}>
                      {ok ? <IconCheck width={10} height={10} /> : <IconX width={10} height={10} />}
                      {ok ? "SUCCESS" : "FAILURE"}
                    </span>
                    <Link href={`/issues/${ep.issue}`} className="font-mono text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                      {ep.repo}#{ep.issue}
                    </Link>
                    <span className="font-mono text-[10px] uppercase" style={{ color: "var(--color-ink-faint)" }}>{ep.phase}</span>
                    <span className="ml-auto font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>{ep.at}</span>
                  </div>
                  <p className="mt-2 text-[13px]" style={{ color: "var(--color-ink-dim)" }}>{ep.summary}</p>
                  <div className="mt-2.5 flex items-start gap-2 rounded-lg px-3 py-2" style={{ background: "color-mix(in srgb, var(--color-violet) 8%, transparent)" }}>
                    <IconBrain width={13} height={13} className="mt-0.5 shrink-0" style={{ color: "var(--color-violet)" }} />
                    <p className="text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>{ep.lesson}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* patterns + skills */}
        <section className="rise flex flex-col gap-5" style={{ animationDelay: "120ms" }}>
          <div>
            <h2 className="mb-3 text-[13px] font-semibold">抽出パターン</h2>
            <div className="flex flex-col gap-3">
              {patterns.map((p) => (
                <div key={p.id} className="panel p-4">
                  <div className="flex items-center gap-2">
                    <h3 className="min-w-0 flex-1 text-[13px] font-medium">{p.title}</h3>
                    {p.status === "promoted" ? (
                      <span className="shrink-0 rounded px-1.5 py-0.5 font-mono text-[9.5px] uppercase" style={{ color: "var(--color-signal)", background: "color-mix(in srgb, var(--color-signal) 12%, transparent)" }}>skill化済</span>
                    ) : (
                      <span className="shrink-0 rounded px-1.5 py-0.5 font-mono text-[9.5px] uppercase" style={{ color: "var(--color-amber)", background: "color-mix(in srgb, var(--color-amber) 12%, transparent)" }}>候補</span>
                    )}
                  </div>
                  <p className="mt-1.5 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-faint)" }}>{p.description}</p>
                  <div className="mt-2.5 flex items-center gap-3">
                    <div className="h-1 flex-1 overflow-hidden rounded-full" style={{ background: "var(--color-panel-2)" }}>
                      <div className="h-full rounded-full" style={{ width: `${p.confidence * 100}%`, background: "var(--color-violet)" }} />
                    </div>
                    <span className="font-mono text-[10px] tnum" style={{ color: "var(--color-violet)" }}>確信 {(p.confidence * 100).toFixed(0)}%</span>
                    <span className="font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>×{p.occurrences}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <SkillStudio />
        </section>
      </div>
    </div>
  );
}
