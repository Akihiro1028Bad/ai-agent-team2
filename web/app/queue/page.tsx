import { ComingSoon } from "@/components/ComingSoon";

export default function QueuePage() {
  return (
    <div className="mx-auto max-w-[900px]">
      <div className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">task queue</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">実行キュー</h1>
        </div>
      </div>

      <div className="rise mt-6" style={{ animationDelay: "60ms" }}>
        <ComingSoon
          title="実行キュー"
          note="GET /api/queue は #96 で提供予定（未接続）"
        />
      </div>
    </div>
  );
}
