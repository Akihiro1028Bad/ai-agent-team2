"use client";

import { useState } from "react";
import { repos } from "@/lib/mock";
import { Portal } from "./Portal";
import { IconCheck, IconX } from "./icons";

type Mode = "url" | "new";

/** Issue を手動で監視対象に投入する（URL 取り込み or 新規起票） */
export function AddIssueButton() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("url");
  const [url, setUrl] = useState("");
  const [repo, setRepo] = useState(repos[0].repo);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [done, setDone] = useState<string | null>(null);

  const valid = mode === "url" ? /github\.com\/.+\/issues\/\d+/.test(url) : title.trim().length > 0;

  const reset = () => {
    setOpen(false);
    setDone(null);
    setUrl("");
    setTitle("");
    setBody("");
  };

  const submit = () => {
    if (mode === "url") {
      const num = url.match(/issues\/(\d+)/)?.[1];
      setDone(`#${num} に ai-agent ラベルを付与し、受付キューに追加しました。次回ポーリングで intake から処理開始します。`);
    } else {
      setDone(`${repo} に Issue を起票し、受付キューに追加しました（#132・モック）。`);
    }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded-lg px-3.5 py-2 text-[12.5px] font-semibold"
        style={{ color: "#0b0d10", background: "var(--color-signal)" }}
      >
        + Issue を投入
      </button>

      {open && (
        <Portal>
        <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={reset} />
          <div className="absolute left-1/2 top-[16vh] w-[min(540px,92vw)] -translate-x-1/2">
            <div className="panel overflow-hidden">
              <div className="flex items-center gap-2.5 border-b px-5 py-3.5" style={{ borderColor: "var(--color-line)" }}>
                <span className="text-[13.5px] font-semibold">Issue を投入</span>
                <button onClick={reset} className="ml-auto" style={{ color: "var(--color-ink-dim)" }} aria-label="閉じる">
                  <IconX width={15} height={15} />
                </button>
              </div>

              {done ? (
                <div className="flex items-start gap-2.5 px-5 py-6">
                  <IconCheck width={16} height={16} className="mt-0.5 shrink-0" style={{ color: "var(--color-cyan)" }} />
                  <p className="text-[13.5px] leading-relaxed" style={{ color: "var(--color-cyan)" }}>{done}</p>
                </div>
              ) : (
                <div className="p-5">
                  <div className="mb-4 inline-flex overflow-hidden rounded-lg border" style={{ borderColor: "var(--color-line)" }}>
                    {(
                      [
                        ["url", "既存 Issue の URL"],
                        ["new", "新規に起票"],
                      ] as const
                    ).map(([m, label]) => (
                      <button
                        key={m}
                        onClick={() => setMode(m)}
                        className="px-3.5 py-1.5 text-[12px] font-medium"
                        style={{ color: mode === m ? "#0b0d10" : "var(--color-ink-dim)", background: mode === m ? "var(--color-cyan)" : "transparent" }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  {mode === "url" ? (
                    <label className="flex flex-col gap-1.5">
                      <span className="eyebrow">github issue url</span>
                      <input
                        autoFocus
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
                        placeholder="https://github.com/owner/repo/issues/123"
                        className="rounded-lg border bg-transparent px-3.5 py-2.5 font-mono text-[12.5px] outline-none focus:border-[var(--color-line-2)]"
                        style={{ borderColor: "var(--color-line)" }}
                      />
                      <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                        ai-agent ラベルを付与して監視対象に追加します
                      </span>
                    </label>
                  ) : (
                    <div className="flex flex-col gap-3">
                      <label className="flex flex-col gap-1.5">
                        <span className="eyebrow">リポジトリ</span>
                        <div className="flex flex-wrap gap-1.5">
                          {repos.map((r) => (
                            <button
                              key={r.repo}
                              onClick={() => setRepo(r.repo)}
                              className="rounded-md border px-2.5 py-1.5 font-mono text-[11px]"
                              style={{
                                borderColor: repo === r.repo ? "var(--color-cyan)" : "var(--color-line)",
                                color: repo === r.repo ? "var(--color-cyan)" : "var(--color-ink-dim)",
                              }}
                            >
                              {r.repo}
                            </button>
                          ))}
                        </div>
                      </label>
                      <label className="flex flex-col gap-1.5">
                        <span className="eyebrow">タイトル</span>
                        <input
                          value={title}
                          onChange={(e) => setTitle(e.target.value)}
                          placeholder="例: 検索結果にページネーションを追加"
                          className="rounded-lg border bg-transparent px-3.5 py-2.5 text-[13px] outline-none focus:border-[var(--color-line-2)]"
                          style={{ borderColor: "var(--color-line)" }}
                        />
                      </label>
                      <label className="flex flex-col gap-1.5">
                        <span className="eyebrow">本文（任意 — 詳しいほどヒアリングが短くなります）</span>
                        <textarea
                          value={body}
                          onChange={(e) => setBody(e.target.value)}
                          rows={4}
                          placeholder="背景・やりたいこと・受け入れ条件など"
                          className="resize-none rounded-lg border bg-transparent px-3.5 py-2.5 text-[13px] outline-none focus:border-[var(--color-line-2)]"
                          style={{ borderColor: "var(--color-line)" }}
                        />
                      </label>
                    </div>
                  )}

                  <div className="mt-5 flex gap-2.5">
                    <button
                      onClick={submit}
                      disabled={!valid}
                      className="rounded-lg px-4 py-2 text-[13px] font-semibold disabled:opacity-40"
                      style={{ color: "#0b0d10", background: "var(--color-signal)" }}
                    >
                      受付キューに追加
                    </button>
                    <button onClick={reset} className="text-[13px]" style={{ color: "var(--color-ink-dim)" }}>
                      キャンセル
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
        </Portal>
      )}
    </>
  );
}
