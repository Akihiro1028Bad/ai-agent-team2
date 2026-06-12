// フェーズ別モデル設定のモック

export type ModelId = "opus-4.8" | "sonnet-4.6" | "haiku-4.5";

export const MODEL_META: Record<ModelId, { label: string; color: string; costNote: string }> = {
  "opus-4.8": { label: "Opus 4.8", color: "var(--color-violet)", costNote: "最高性能 / 高コスト" },
  "sonnet-4.6": { label: "Sonnet 4.6", color: "var(--color-cyan)", costNote: "バランス" },
  "haiku-4.5": { label: "Haiku 4.5", color: "var(--color-signal)", costNote: "高速 / 低コスト" },
};

export interface PhaseModelConfig {
  phase: string;
  label: string;
  model: ModelId;
  thinking: boolean;
  maxTurns: number;
  hint: string;
}

export const defaultPhaseModels: PhaseModelConfig[] = [
  { phase: "intake", label: "受付", model: "haiku-4.5", thinking: false, maxTurns: 3, hint: "タイプ判定のみ。軽量モデルで十分" },
  { phase: "clarify", label: "ヒアリング", model: "sonnet-4.6", thinking: false, maxTurns: 6, hint: "要件の聞き出し。質問品質が重要" },
  { phase: "split", label: "分割", model: "opus-4.8", thinking: true, maxTurns: 10, hint: "大規模 Issue の分解。設計判断を含む" },
  { phase: "plan", label: "計画", model: "opus-4.8", thinking: true, maxTurns: 20, hint: "設計書生成。最も品質が効く工程" },
  { phase: "implement", label: "実装", model: "sonnet-4.6", thinking: false, maxTurns: 60, hint: "コーディング主体。コスパ重視" },
  { phase: "review", label: "レビュー対応", model: "sonnet-4.6", thinking: false, maxTurns: 20, hint: "CI 修正・指摘対応" },
  { phase: "revise", label: "修正", model: "sonnet-4.6", thinking: true, maxTurns: 30, hint: "差し戻し時の再設計を含む" },
];
