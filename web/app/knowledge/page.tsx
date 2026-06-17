import { KnowledgeClient } from "@/components/knowledge/KnowledgeClient";

export default function KnowledgePage() {
  return (
    <div className="mx-auto max-w-[1100px]">
      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">self-improvement loop</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">ナレッジ</h1>
        </div>
      </div>

      <div className="rise mt-6" style={{ animationDelay: "60ms" }}>
        <KnowledgeClient />
      </div>
    </div>
  );
}
