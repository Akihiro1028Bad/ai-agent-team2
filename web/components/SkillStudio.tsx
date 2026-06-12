"use client";

import { useState } from "react";
import { skills as initialSkills, type GeneratedSkill } from "@/lib/knowledge";
import { IconBolt, IconCheck, IconEdit, IconX } from "./icons";

interface SkillDraft {
  name: string;
  trigger: string;
  content: string;
}

const EMPTY: SkillDraft = { name: "", trigger: "", content: "" };

const TEMPLATE = `# Skill: <名前>

## いつ使うか
<トリガー条件>

## 手順
1. ...
2. ...

## チェックリスト
- [ ] ...`;

function SkillForm({ initial, onSave, onCancel }: { initial: SkillDraft; onSave: (d: SkillDraft) => void; onCancel: () => void }) {
  const [draft, setDraft] = useState(initial);
  const valid = draft.name.trim() && draft.content.trim();

  return (
    <div className="rounded-xl border p-4" style={{ borderColor: "var(--color-line-2)", background: "var(--color-panel-2)" }}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5">
          <span className="eyebrow">skill 名（kebab-case）</span>
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            placeholder="例: api-error-handling"
            className="rounded-lg border bg-transparent px-3 py-2 font-mono text-[12.5px] outline-none focus:border-[var(--color-line-2)]"
            style={{ borderColor: "var(--color-line)" }}
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="eyebrow">トリガー（いつ使うか）</span>
          <input
            value={draft.trigger}
            onChange={(e) => setDraft({ ...draft, trigger: e.target.value })}
            placeholder="例: 外部 API を呼ぶ実装をするとき"
            className="rounded-lg border bg-transparent px-3 py-2 text-[12.5px] outline-none focus:border-[var(--color-line-2)]"
            style={{ borderColor: "var(--color-line)" }}
          />
        </label>
      </div>
      <label className="mt-3 flex flex-col gap-1.5">
        <span className="eyebrow">内容（Markdown — エージェントのプロンプトに注入されます）</span>
        <textarea
          value={draft.content}
          onChange={(e) => setDraft({ ...draft, content: e.target.value })}
          rows={9}
          placeholder={TEMPLATE}
          className="w-full resize-y rounded-lg border bg-transparent px-3 py-2.5 font-mono text-[12px] leading-relaxed outline-none focus:border-[var(--color-line-2)]"
          style={{ borderColor: "var(--color-line)" }}
        />
      </label>
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={() => setDraft({ ...draft, content: draft.content || TEMPLATE })}
          className="rounded-lg border px-3 py-1.5 text-[11.5px]"
          style={{ borderColor: "var(--color-line-2)", color: "var(--color-ink-dim)" }}
        >
          テンプレート挿入
        </button>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => valid && onSave({ ...draft, name: draft.name.trim() })}
            disabled={!valid}
            className="rounded-lg px-4 py-1.5 text-[12.5px] font-semibold disabled:opacity-40"
            style={{ color: "#0b0d10", background: "var(--color-signal)" }}
          >
            保存
          </button>
          <button onClick={onCancel} className="text-[12.5px]" style={{ color: "var(--color-ink-dim)" }}>キャンセル</button>
        </div>
      </div>
    </div>
  );
}

/** Skill の一覧・新規作成・編集（モック: ローカル state のみ） */
export function SkillStudio() {
  const [items, setItems] = useState<(GeneratedSkill & { trigger?: string; content?: string; manual?: boolean })[]>(initialSkills);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const notify = (msg: string) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), 2800);
  };

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[13px] font-semibold">Skill</h2>
        <button
          onClick={() => {
            setCreating((v) => !v);
            setEditingId(null);
          }}
          className="rounded-lg border px-3 py-1.5 text-[12px] font-medium"
          style={{ borderColor: "color-mix(in srgb, var(--color-signal) 45%, transparent)", color: "var(--color-signal)" }}
        >
          {creating ? "閉じる" : "+ 新規作成"}
        </button>
      </div>

      {flash && (
        <div className="mb-3 flex items-center gap-2 rounded-lg px-3 py-2 text-[12.5px]" style={{ color: "var(--color-cyan)", background: "color-mix(in srgb, var(--color-cyan) 10%, transparent)" }}>
          <IconCheck width={13} height={13} /> {flash}
        </div>
      )}

      {creating && (
        <div className="mb-3">
          <SkillForm
            initial={EMPTY}
            onCancel={() => setCreating(false)}
            onSave={(d) => {
              setItems((prev) => [
                { id: `sk-m${prev.length}`, name: d.name, fromPattern: "手動作成", usedCount: 0, successRate: 0, updated: "たった今", trigger: d.trigger, content: d.content, manual: true },
                ...prev,
              ]);
              setCreating(false);
              notify(`skill「${d.name}」を作成しました → 次回の該当フェーズから自動で使用されます`);
            }}
          />
        </div>
      )}

      <div className="panel p-2">
        {items.map((s) => (
          <div key={s.id}>
            <div className="flex items-center gap-2.5 rounded-lg px-3 py-2.5">
              <IconBolt width={13} height={13} style={{ color: s.manual ? "var(--color-amber)" : "var(--color-signal)" }} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-mono text-[12px]">{s.name}</span>
                  {s.manual && (
                    <span className="rounded px-1.5 py-0.5 font-mono text-[9px] uppercase" style={{ color: "var(--color-amber)", background: "color-mix(in srgb, var(--color-amber) 12%, transparent)" }}>manual</span>
                  )}
                </div>
                <div className="font-mono text-[10px]" style={{ color: "var(--color-ink-faint)" }}>
                  {s.usedCount > 0 ? `使用 ${s.usedCount} 回 · 成功率 ${(s.successRate * 100).toFixed(0)}% · ` : "未使用 · "}
                  {s.updated}
                </div>
              </div>
              <button
                onClick={() => {
                  setEditingId(editingId === s.id ? null : s.id);
                  setCreating(false);
                }}
                className="shrink-0"
                style={{ color: "var(--color-ink-faint)" }}
                aria-label={`${s.name} を編集`}
              >
                <IconEdit width={13} height={13} />
              </button>
              <button
                onClick={() => {
                  setItems((prev) => prev.filter((x) => x.id !== s.id));
                  notify(`skill「${s.name}」を削除しました`);
                }}
                className="shrink-0"
                style={{ color: "var(--color-ink-faint)" }}
                aria-label={`${s.name} を削除`}
              >
                <IconX width={13} height={13} />
              </button>
            </div>
            {editingId === s.id && (
              <div className="px-2 pb-2">
                <SkillForm
                  initial={{ name: s.name, trigger: s.trigger ?? "", content: s.content ?? TEMPLATE.replace("<名前>", s.name) }}
                  onCancel={() => setEditingId(null)}
                  onSave={(d) => {
                    setItems((prev) => prev.map((x) => (x.id === s.id ? { ...x, name: d.name, trigger: d.trigger, content: d.content, updated: "たった今" } : x)));
                    setEditingId(null);
                    notify(`skill「${d.name}」を更新しました`);
                  }}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
