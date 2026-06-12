// ── ドメイン型（オーケストレーターのモデルに対応） ──

export type IssueType = "bug" | "feature-m" | "feature-l";

export type RunStatus = "running" | "waiting" | "suspended" | "done" | "blocked";

/** 統一パイプラインのフェーズ（再設計後） */
export type PhaseKey =
  | "intake"
  | "clarify"
  | "split"
  | "plan"
  | "approve"
  | "implement"
  | "review"
  | "revise"
  | "done";

export interface PhaseMeta {
  key: PhaseKey;
  label: string;
  conditional?: boolean; // split / revise は条件付き
}

export type EventKind =
  | "phase"
  | "agent"
  | "commit"
  | "ci"
  | "comment"
  | "gate"
  | "error";

export interface IssueEvent {
  id: string;
  at: string; // 表示用の相対/絶対時刻
  kind: EventKind;
  title: string;
  detail?: string;
  cost?: number;
}

export interface IssueSummary {
  number: number;
  repo: string;
  title: string;
  type: IssueType;
  phase: PhaseKey;
  status: RunStatus;
  costUsd: number;
  prNumber?: number;
  branch?: string;
  updated: string;
  needsHuman?: string; // 人間アクションの要約（あれば）
}

export interface IssueDetail extends IssueSummary {
  body: string;
  designDoc?: string;
  subtasks?: { id: number; title: string; done: boolean }[];
  events: IssueEvent[];
}

export type GateKind = "approve-plan" | "hearing" | "review" | "approve-design";

export interface GateItem {
  id: string;
  kind: GateKind;
  issue: number;
  repo: string;
  title: string;
  prompt: string; // 人間に問うている内容
  age: string;
  type: IssueType;
}

export interface RepoConfig {
  owner: string;
  repo: string;
  account: string;
  label: string;
  baseBranch: string;
}

export interface OrchestratorState {
  running: boolean;
  pollingIntervalSec: number;
  account: string;
  maxConcurrent: number;
  rateRemaining: number;
  rateLimit: number;
}
