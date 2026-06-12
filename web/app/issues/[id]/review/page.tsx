import Link from "next/link";
import { getDesignReview } from "@/lib/design-review";
import { getIssue } from "@/lib/mock";
import { ReviewClient } from "@/components/review/ReviewClient";
import { IconArrow } from "@/components/icons";

export default async function DesignReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const n = Number(id);
  const review = getDesignReview(n);
  const issue = getIssue(n);

  return (
    <div className="mx-auto max-w-[920px] pb-4">
      <Link href={`/issues/${id}`} className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>
        <IconArrow width={13} height={13} className="rotate-180" /> Issue 詳細
      </Link>

      {review ? (
        <ReviewClient review={review} issueType={issue.type} />
      ) : (
        <div className="panel mt-4 p-8 text-center" style={{ color: "var(--color-ink-dim)" }}>
          この Issue にはまだ設計レビュー成果物がありません。
        </div>
      )}
    </div>
  );
}
