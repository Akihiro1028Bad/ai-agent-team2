"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  createContext,
  useContext,
  useId,
  useState,
  type ReactNode,
} from "react";
import { IconCheck, IconEdit, IconMessage, IconX } from "@/components/icons";

export type CommentTag = "指摘" | "質問";

export interface DraftComment {
  id: string;
  anchor: string;
  anchorLabel: string;
  tag: CommentTag;
  body: string;
}

interface ReviewCtx {
  comments: DraftComment[];
  forAnchor: (anchor: string) => DraftComment[];
  add: (anchor: string, anchorLabel: string, tag: CommentTag, body: string) => void;
  update: (id: string, tag: CommentTag, body: string) => void;
  remove: (id: string) => void;
  locked: boolean;
  setLocked: (v: boolean) => void;
}

const Ctx = createContext<ReviewCtx | null>(null);

export function useReview(): ReviewCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useReview must be used within ReviewProvider");
  return c;
}

export function ReviewProvider({ children }: { children: ReactNode }) {
  const [comments, setComments] = useState<DraftComment[]>([]);
  const [locked, setLocked] = useState(false);
  let seq = comments.length;

  const value: ReviewCtx = {
    comments,
    forAnchor: (anchor) => comments.filter((c) => c.anchor === anchor),
    add: (anchor, anchorLabel, tag, body) =>
      setComments((prev) => [
        ...prev,
        { id: `c${Date.now()}-${seq++}`, anchor, anchorLabel, tag, body },
      ]),
    update: (id, tag, body) =>
      setComments((prev) => prev.map((c) => (c.id === id ? { ...c, tag, body } : c))),
    remove: (id) => setComments((prev) => prev.filter((c) => c.id !== id)),
    locked,
    setLocked,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

const TAG_COLOR: Record<CommentTag, string> = {
  指摘: "var(--color-rose)",
  質問: "var(--color-cyan)",
};

function Composer({ anchor, label, onClose }: { anchor: string; label: string; onClose: () => void }) {
  const { add } = useReview();
  const [tag, setTag] = useState<CommentTag>("指摘");
  const [body, setBody] = useState("");

  return (
    <div className="mt-2 rounded-xl border p-3" style={{ borderColor: "var(--color-line-2)", background: "var(--color-panel-2)" }}>
      <div className="mb-2 flex items-center gap-2">
        <span className="font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>@ {label}</span>
        <div className="ml-auto inline-flex overflow-hidden rounded-lg border" style={{ borderColor: "var(--color-line)" }}>
          {(["指摘", "質問"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTag(t)}
              className="px-2.5 py-1 text-[11px] font-medium transition-colors"
              style={{ color: tag === t ? "#0b0d10" : "var(--color-ink-dim)", background: tag === t ? TAG_COLOR[t] : "transparent" }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      <textarea
        autoFocus
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={2}
        placeholder={tag === "指摘" ? "修正してほしい点…" : "確認したいこと…"}
        className="w-full resize-none rounded-lg border bg-transparent px-3 py-2 text-[13px] outline-none focus:border-[var(--color-line-2)]"
        style={{ borderColor: "var(--color-line)" }}
      />
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => {
            if (body.trim()) add(anchor, label, tag, body.trim());
            onClose();
          }}
          disabled={!body.trim()}
          className="rounded-lg px-3 py-1.5 text-[12px] font-medium disabled:opacity-40"
          style={{ color: "#0b0d10", background: "var(--color-signal)" }}
        >
          下書きに追加
        </button>
        <button onClick={onClose} className="rounded-lg px-3 py-1.5 text-[12px]" style={{ color: "var(--color-ink-dim)" }}>
          やめる
        </button>
      </div>
    </div>
  );
}

function ThreadItem({ c }: { c: DraftComment }) {
  const { update, remove, locked } = useReview();
  const [editing, setEditing] = useState(false);
  const [tag, setTag] = useState<CommentTag>(c.tag);
  const [body, setBody] = useState(c.body);

  if (editing && !locked) {
    return (
      <div className="rounded-lg border p-2.5" style={{ borderColor: "var(--color-line-2)", background: "var(--color-panel-2)" }}>
        <div className="mb-2 inline-flex overflow-hidden rounded-lg border" style={{ borderColor: "var(--color-line)" }}>
          {(["指摘", "質問"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTag(t)}
              className="px-2.5 py-1 text-[11px] font-medium"
              style={{ color: tag === t ? "#0b0d10" : "var(--color-ink-dim)", background: tag === t ? TAG_COLOR[t] : "transparent" }}
            >
              {t}
            </button>
          ))}
        </div>
        <textarea
          autoFocus
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={2}
          className="w-full resize-none rounded-lg border bg-transparent px-3 py-2 text-[13px] outline-none focus:border-[var(--color-line-2)]"
          style={{ borderColor: "var(--color-line)" }}
        />
        <div className="mt-2 flex gap-2">
          <button
            onClick={() => {
              if (body.trim()) update(c.id, tag, body.trim());
              setEditing(false);
            }}
            disabled={!body.trim()}
            className="rounded-lg px-3 py-1 text-[11.5px] font-medium disabled:opacity-40"
            style={{ color: "#0b0d10", background: "var(--color-signal)" }}
          >
            保存
          </button>
          <button
            onClick={() => {
              setTag(c.tag);
              setBody(c.body);
              setEditing(false);
            }}
            className="text-[11.5px]"
            style={{ color: "var(--color-ink-dim)" }}
          >
            キャンセル
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2 rounded-lg border px-3 py-2" style={{ borderColor: `color-mix(in srgb, ${TAG_COLOR[c.tag]} 30%, transparent)`, background: `color-mix(in srgb, ${TAG_COLOR[c.tag]} 7%, transparent)` }}>
      <span className="mt-0.5 rounded px-1.5 py-0.5 font-mono text-[10px]" style={{ color: TAG_COLOR[c.tag], background: `color-mix(in srgb, ${TAG_COLOR[c.tag]} 14%, transparent)` }}>{c.tag}</span>
      <p className="min-w-0 flex-1 text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>{c.body}</p>
      {!locked && (
        <>
          <button onClick={() => setEditing(true)} className="shrink-0" style={{ color: "var(--color-ink-faint)" }} aria-label="編集">
            <IconEdit width={13} height={13} />
          </button>
          <button onClick={() => remove(c.id)} className="shrink-0" style={{ color: "var(--color-ink-faint)" }} aria-label="削除">
            <IconX width={13} height={13} />
          </button>
        </>
      )}
    </div>
  );
}

function Thread({ comments }: { comments: DraftComment[] }) {
  if (comments.length === 0) return null;
  return (
    <div className="mt-2 flex flex-col gap-1.5">
      {comments.map((c) => (
        <ThreadItem key={c.id} c={c} />
      ))}
    </div>
  );
}

export function Commentable({ anchor, label, children }: { anchor: string; label: string; children: ReactNode }) {
  const { forAnchor, locked } = useReview();
  const [open, setOpen] = useState(false);
  const comments = forAnchor(anchor);
  const has = comments.length > 0;

  return (
    <div className="group/c relative -mx-2 rounded-lg px-2 transition-colors hover:bg-[color-mix(in_srgb,var(--color-signal)_4%,transparent)]">
      <div className="flex items-start gap-1.5">
        <div className="min-w-0 flex-1">{children}</div>
        {!locked && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="mt-0.5 shrink-0 rounded-md border p-1 transition-opacity focus:opacity-100 lg:opacity-0 lg:group-hover/c:opacity-100"
            style={{ borderColor: "var(--color-line-2)", color: has ? "var(--color-signal)" : "var(--color-ink-dim)", background: "var(--color-panel)" }}
            aria-label="コメントを追加"
            title="コメントを追加"
          >
            {has ? (
              <span className="flex items-center gap-1 px-0.5 font-mono text-[10px]">
                <IconMessage width={11} height={11} />{comments.length}
              </span>
            ) : (
              <IconMessage width={12} height={12} />
            )}
          </button>
        )}
      </div>
      <Thread comments={comments} />
      {open && !locked && <Composer anchor={anchor} label={label} onClose={() => setOpen(false)} />}
    </div>
  );
}

/** 設計書 Markdown をブロック要素単位でコメント可能に描画 */
export function CommentableMarkdown({ children, prefix }: { children: string; prefix: string }) {
  const base = useId().replace(/[:]/g, "");
  let i = 0;
  const wrap = (tag: keyof HTMLElementTagNameMap, label: string) =>
    function Block({ node: _node, ...props }: { node?: unknown; children?: ReactNode }) {
      const id = `${prefix}-${base}-${i++}`;
      const El = tag as "p";
      return (
        <Commentable anchor={id} label={label}>
          <El {...props} />
        </Commentable>
      );
    };

  return (
    <div className="md text-[13.5px] leading-relaxed" style={{ color: "var(--color-ink-dim)" }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: wrap("p", "段落"),
          ul: wrap("ul", "リスト"),
          ol: wrap("ol", "リスト"),
          h2: wrap("h2", "見出し"),
          h3: wrap("h3", "見出し"),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

export { IconCheck };
