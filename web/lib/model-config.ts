// フェーズ別モデル設定のプレゼンテーション層 (#90)。
// API ワイヤ型 (ApiPhaseModelsResponse / PhaseModelInput) は lib/api.ts で定義。
// このファイルはモックデータを持たず、変換関数と表示メタのみを持つ。

import type { ApiPhaseModelsResponse, PhaseModelInput } from "@/lib/api";

// ── モデル識別子 ──

export type ModelId = "haiku" | "sonnet" | "opus";

// ── 表示メタ ──

export const MODEL_META: Record<ModelId, { label: string; color: string; costNote: string }> = {
  haiku: { label: "Haiku 4.5", color: "var(--color-signal)", costNote: "高速 / 低コスト" },
  sonnet: { label: "Sonnet 4.6", color: "var(--color-cyan)", costNote: "バランス" },
  opus: { label: "Opus 4.8", color: "var(--color-violet)", costNote: "最高性能 / 高コスト" },
};

// モデル表示順 (haiku → sonnet → opus)
export const MODEL_ORDER: ModelId[] = ["haiku", "sonnet", "opus"];

// ── フェーズ プレゼンテーションメタ ──

export interface PhaseMeta {
  label: string;
  hint: string;
  defaultMaxTurns: number;
}

export const PHASE_META: Record<string, PhaseMeta> = {
  intake: { label: "受付", hint: "タイプ判定のみ。軽量モデルで十分", defaultMaxTurns: 3 },
  clarify: { label: "ヒアリング", hint: "要件の聞き出し。質問品質が重要", defaultMaxTurns: 6 },
  plan: { label: "計画", hint: "設計書生成。最も品質が効く工程", defaultMaxTurns: 20 },
  split: { label: "分割", hint: "大規模 Issue の分解。設計判断を含む", defaultMaxTurns: 10 },
  implement: { label: "実装", hint: "コーディング主体。コスパ重視", defaultMaxTurns: 60 },
  revise: { label: "修正", hint: "差し戻し対応・CI 修正・再設計を含む", defaultMaxTurns: 30 },
};

// ── UI 行型 ──

export interface PhaseModelRow {
  phase: string;
  label: string;
  model: ModelId;
  thinking: boolean;
  maxTurns: number;
  hint: string;
}

// ── 変換関数 ──

/** API レスポンス → UI 行。未知 phase (PHASE_META に無い) はスキップ。max_turns が null の場合は PHASE_META.defaultMaxTurns を使う。 */
export function toRows(api: ApiPhaseModelsResponse): PhaseModelRow[] {
  return api.phases
    .filter((p) => p.phase in PHASE_META)
    .map((p) => {
      const meta = PHASE_META[p.phase]!;
      return {
        phase: p.phase,
        label: meta.label,
        model: normalizeModelId(p.model),
        thinking: p.thinking,
        maxTurns: p.max_turns ?? meta.defaultMaxTurns,
        hint: meta.hint,
      };
    });
}

/** UI 行 → PUT 入力。 */
export function toInputs(rows: PhaseModelRow[]): PhaseModelInput[] {
  return rows.map((r) => ({
    phase: r.phase,
    model: r.model,
    thinking: r.thinking,
    max_turns: r.maxTurns,
  }));
}

/** API の model 文字列を ModelId へ正規化する。未知値は "sonnet" に倒す。 */
function normalizeModelId(value: string): ModelId {
  if (value === "haiku" || value === "sonnet" || value === "opus") return value;
  return "sonnet";
}
