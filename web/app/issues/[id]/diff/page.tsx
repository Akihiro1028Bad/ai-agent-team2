import Link from "next/link";
import { getPrDiff } from "@/lib/diff";
import { getIssue } from "@/lib/mock";
import { DiffViewer } from "@/components/DiffViewer";
import { TypeTag } from "@/components/ui";
import { IconArrow } from "@/components/icons";

export default async function IssueDiffPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const n = Number(id);
  const diff = getPrDiff(n);
  const issue = getIssue(n);

  return (
    <div className="mx-auto max-w-[1200px] pb-4">
      <Link href={`/issues/${id}`} className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>
        <IconArrow width={13} height={13} className="rotate-180" /> Issue 詳細
      </Link>

      {diff ? (
        <>
          <div className="rise mt-4">
            <div className="eyebrow">pull request diff</div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="font-mono text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
                {issue.repo}#{diff.issue} · PR #{diff.pr} · {diff.branch}
              </span>
              <TypeTag type={issue.type} />
            </div>
            <h1 className="mt-1.5 text-xl font-semibold tracking-tight sm:text-2xl">{issue.title}</h1>
          </div>
          <div className="rise mt-5" style={{ animationDelay: "80ms" }}>
            <DiffViewer diff={diff} />
          </div>
        </>
      ) : (
        <div className="panel mt-4 p-8 text-center" style={{ color: "var(--color-ink-dim)" }}>
          この Issue にはまだ PR 差分がありません。
        </div>
      )}
    </div>
  );
}
