// 読み取り API クライアント + 型アダプタ (#86)。
//
// FastAPI の読み取り API (src/ai_agent_orchestrator/api/) が返す snake_case の
// レスポンスを、UI の型 (lib/types.ts 等) へ変換する純粋アダプタと、fetch ラッパ
// (apiGet) / SSE ヘルパをまとめる。接続先は next.config.ts の rewrites 経由で
// localhost の API プロセスへプロキシされる (ブラウザは相対パス /api/* を叩く)。

import type {
  IssueSummary,
  IssueDetail,
  IssueEvent,
  EventKind,
  IssueType,
  PhaseKey,
  RunStatus,
} from "@/lib/types";
import type { LogLine, LogLevel } from "@/lib/logs";
import type { HealthItem } from "@/lib/health";
import type { IssueCostRow } from "@/lib/costs";
import type { PrDiff } from "@/lib/diff";
import { parsePatch } from "@/lib/diff-parse";

// ── API ワイヤ型 (src/ai_agent_orchestrator/api/schemas.py と対応) ──

export interface ApiIssueSummary {
  number: number;
  repo: string;
  title: string | null;
  issue_type: string;
  phase: string;
  status: RunStatus;
  cost_usd: number;
  pr_number: number | null;
  design_pr_number: number | null;
  branch_head_sha: string | null;
  retry_count: number;
  created_at: string;
  updated_at: string;
}

export interface ApiIssueDetail extends ApiIssueSummary {
  plan_json: Record<string, unknown> | null;
  session_id: string | null;
  impl_iteration: number;
}

export interface ApiEventRecord {
  ts: string;
  issue: number | null;
  phase: string;
  event: string;
  data: Record<string, unknown> | null;
}

export interface ApiAgentLogRecord {
  ts: string;
  phase: string;
  type: string;
  [key: string]: unknown;
}

export interface ApiAgentLogPage {
  records: ApiAgentLogRecord[];
  next_offset: number;
  total: number;
}

export interface ApiIssueCost {
  repo: string;
  issue_number: number;
  cost_usd: number;
  phases: Record<string, number>;
}

export interface ApiCostsResponse {
  total_usd: number;
  issues: ApiIssueCost[];
}

export interface ApiHealth {
  running: boolean;
  stale: boolean;
  reason: string | null;
  ts: string | null;
  queue: Record<string, number> | null;
  repositories: string[];
  rate_limit: Record<string, number> | null;
  worktrees: number | null;
  last_poll: Record<string, string>;
  accounts: Record<string, boolean>;
}

export interface ApiDiffFile {
  filename: string;
  status: string;
  additions: number;
  deletions: number;
  patch: string | null;
}

export interface ApiDiffResponse {
  pr_number: number;
  files: ApiDiffFile[];
}

// ── fetch ラッパ ──

/** API 呼び出しの失敗。status=0 は接続不可 (ネットワーク/プロセス停止)。 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** orchestrator/API プロセスへ到達できない (停止中) か。 */
  get isUnreachable(): boolean {
    return this.status === 0;
  }
}

async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { headers: { Accept: "application/json" }, signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    // ネットワーク到達不可 (API プロセス停止・プロキシ失敗)。
    throw new ApiError(0, `API へ接続できません (${path})`);
  }
  if (!res.ok) {
    throw new ApiError(res.status, `API エラー ${res.status} (${path})`);
  }
  return (await res.json()) as T;
}

// ── 時刻フォーマット ──

/** ISO 文字列を "HH:MM:SS" にする (パース不能はそのまま返す)。 */
export function formatClock(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** ISO 文字列を "N秒前/N分前/N時間前/N日前" の相対表記にする。 */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const sec = Math.max(0, Math.floor((now - t) / 1000));
  if (sec < 60) return `${sec}秒前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}分前`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour}時間前`;
  return `${Math.floor(hour / 24)}日前`;
}

// ── 値の正規化 ──

const KNOWN_PHASES: ReadonlySet<string> = new Set<PhaseKey>([
  "intake",
  "clarify",
  "split",
  "plan",
  "approve",
  "implement",
  "review",
  "revise",
  "done",
]);

/**
 * API の phase 文字列を UI の PhaseKey へ正規化する。
 *
 * Phase enum は U5 で 9 フェーズへ刷新済みのため大半は素通し。表示用の
 * フェーズレールに無い値 (clarify-wait / blocked / suspended) は最寄りへ寄せる。
 * blocked/suspended は status 側で表示されるため、レール上は実装段で止まった
 * ものとして implement を既定にする (停止位置の正確な情報は state に残らない)。
 */
export function normalizePhase(phase: string): PhaseKey {
  if (KNOWN_PHASES.has(phase)) return phase as PhaseKey;
  if (phase === "clarify-wait") return "clarify";
  return "implement";
}

const KNOWN_TYPES: ReadonlySet<string> = new Set<IssueType>(["bug", "feature-m", "feature-l"]);

function normalizeIssueType(value: string): IssueType {
  return KNOWN_TYPES.has(value) ? (value as IssueType) : "feature-m";
}

// ── アダプタ ──

export function adaptIssueSummary(a: ApiIssueSummary): IssueSummary {
  return {
    number: a.number,
    repo: a.repo,
    title: a.title ?? `#${a.number}`,
    type: normalizeIssueType(a.issue_type),
    phase: normalizePhase(a.phase),
    status: a.status,
    costUsd: a.cost_usd,
    prNumber: a.pr_number ?? undefined,
    designPrNumber: a.design_pr_number ?? undefined,
    branch: a.branch_head_sha ? a.branch_head_sha.slice(0, 7) : undefined,
    updated: formatRelative(a.updated_at),
    needsHuman: a.status === "waiting" ? "承認・回答待ち" : undefined,
  };
}

const EVENT_KIND_RULES: ReadonlyArray<readonly [RegExp, EventKind]> = [
  [/error|fail|suspend|block/, "error"],
  [/approve|gate|reaction|lgtm|hearing|split/, "gate"],
  [/\bci\b|ci_|check/, "ci"],
  [/comment/, "comment"],
  [/commit|push|\bpr\b|pull_request|merge/, "commit"],
  [/phase/, "phase"],
  [/agent|tool|claude/, "agent"],
];

function eventKind(event: string): EventKind {
  const e = event.toLowerCase();
  for (const [re, kind] of EVENT_KIND_RULES) {
    if (re.test(e)) return kind;
  }
  return "phase";
}

function humanizeEvent(event: string): string {
  return event.replace(/_/g, " ");
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function adaptEvent(a: ApiEventRecord): IssueEvent {
  const data = a.data ?? {};
  return {
    // ポーリングごとに安定する内容由来の id (既読状態の保持に必要)。
    // index 由来だと新着で順序がずれて id が変わってしまう。
    id: `${a.issue ?? ""}:${a.ts}:${a.event}`,
    at: formatRelative(a.ts),
    kind: eventKind(a.event),
    title: asString(data.title) ?? humanizeEvent(a.event),
    detail: asString(data.detail) ?? asString(data.message),
    cost: asNumber(data.cost_usd),
  };
}

/**
 * 同一 (issue,ts,event) で id が重複した場合に決定的な接尾辞で一意化する。
 * 入力リストの順序はポーリング間で安定なので、付与する接尾辞も安定し、
 * React の key 衝突と通知既読の取り違えを防ぐ (adaptEvent の id は内容由来)。
 */
function ensureUniqueIds(events: IssueEvent[]): IssueEvent[] {
  const seen = new Map<string, number>();
  return events.map((e) => {
    const n = seen.get(e.id) ?? 0;
    seen.set(e.id, n + 1);
    return n === 0 ? e : { ...e, id: `${e.id}#${n}` };
  });
}

export function adaptIssueDetail(a: ApiIssueDetail, events: ApiEventRecord[]): IssueDetail {
  const summary = adaptIssueSummary(a);
  const planSubtasks = extractSubtasks(a.plan_json);
  return {
    ...summary,
    // GitHub Issue 本文は読み取り API に含まれない (準備中 / スコープ外)。
    body: "",
    designDoc: undefined,
    subtasks: planSubtasks,
    events: ensureUniqueIds(events.map(adaptEvent)),
  };
}

function extractSubtasks(
  plan: Record<string, unknown> | null,
): { id: number; title: string; done: boolean }[] | undefined {
  if (!plan || !Array.isArray(plan.subtasks)) return undefined;
  const out: { id: number; title: string; done: boolean }[] = [];
  plan.subtasks.forEach((raw, i) => {
    if (raw && typeof raw === "object") {
      const obj = raw as Record<string, unknown>;
      out.push({
        id: asNumber(obj.id) ?? i + 1,
        title: asString(obj.title) ?? `subtask ${i + 1}`,
        done: obj.done === true,
      });
    }
  });
  return out.length > 0 ? out : undefined;
}

const LOG_LEVEL_BY_TYPE: Record<string, LogLevel> = {
  text: "agent",
  tool_use: "tool",
  preset: "info",
};

export function adaptAgentLog(rec: ApiAgentLogRecord): LogLine {
  const level = adaptLogLevel(rec);
  return {
    t: rec.ts ? formatClock(rec.ts) : "",
    level,
    source: adaptLogSource(rec),
    text: adaptLogText(rec),
  };
}

function adaptLogLevel(rec: ApiAgentLogRecord): LogLevel {
  if (rec.type === "result") return rec.is_error === true ? "error" : "ok";
  return LOG_LEVEL_BY_TYPE[rec.type] ?? "info";
}

function adaptLogSource(rec: ApiAgentLogRecord): string {
  if (rec.type === "tool_use") return asString(rec.tool) ?? "tool";
  if (rec.type === "result") return "result";
  return rec.phase || "agent";
}

function adaptLogText(rec: ApiAgentLogRecord): string {
  if (rec.type === "text") return asString(rec.text) ?? "";
  if (rec.type === "tool_use") {
    const input = rec.input && typeof rec.input === "object" ? (rec.input as Record<string, unknown>) : {};
    const summary = asString(input.command) ?? asString(input.file_path) ?? asString(input.path) ?? asString(input.description);
    return summary ?? "";
  }
  if (rec.type === "result") {
    const cost = asNumber(rec.cost_usd);
    const dur = asNumber(rec.duration_ms);
    const parts = ["完了"];
    if (cost !== undefined) parts.push(`$${cost.toFixed(4)}`);
    if (dur !== undefined) parts.push(`${dur}ms`);
    return parts.join(" · ");
  }
  return asString(rec.text) ?? humanizeEvent(rec.type);
}

/** 健全性レスポンスを UI のヘルス項目へ変換する (API が持つ項目のみ)。 */
export function adaptHealth(h: ApiHealth): HealthItem[] {
  const items: HealthItem[] = [];

  const lastPoll = Object.values(h.last_poll)[0];
  items.push({
    key: "poller",
    label: "GitHub ポーラー",
    status: h.running ? "ok" : "error",
    value: h.running ? "稼働中" : "停止中",
    detail: lastPoll ? `最終ポーリング ${formatRelative(lastPoll)}` : h.reason ?? "ポーリング履歴なし",
  });

  if (h.rate_limit) {
    const remaining = h.rate_limit.remaining ?? 0;
    const limit = h.rate_limit.limit ?? 0;
    items.push({
      key: "rate",
      label: "API レート制限",
      status: limit > 0 && remaining / limit < 0.1 ? "warn" : "ok",
      value: `${remaining.toLocaleString()} / ${limit.toLocaleString()}`,
      detail: "GitHub REST レート",
    });
  }

  if (h.queue) {
    const active = h.queue.active ?? 0;
    const maxTotal = h.queue.max_total ?? 0;
    items.push({
      key: "agents",
      label: "エージェント実行枠",
      status: maxTotal > 0 && active >= maxTotal ? "warn" : "ok",
      value: `${active} / ${maxTotal} 使用中`,
      detail: `待機 ${h.queue.queued ?? 0} 件`,
    });
  }

  if (h.worktrees !== null) {
    items.push({
      key: "worktrees",
      label: "git worktree",
      status: "ok",
      value: `${h.worktrees} 個`,
      detail: "並行 Issue の作業ツリー",
    });
  }

  return items;
}

/** コスト集計を Issue 別コスト行へ変換する (タイトルは別途 JOIN)。 */
export function adaptCostRows(c: ApiCostsResponse, titleByIssue: Map<number, string> = new Map()): IssueCostRow[] {
  return c.issues
    .map((i) => ({
      issue: i.issue_number,
      repo: i.repo,
      title: titleByIssue.get(i.issue_number) ?? `#${i.issue_number}`,
      usd: i.cost_usd,
      // トークン/ターン数は読み取り API に含まれない (準備中)。
      inTokensK: 0,
      outTokensK: 0,
      turns: 0,
    }))
    .sort((a, b) => b.usd - a.usd);
}

export function adaptDiff(d: ApiDiffResponse): PrDiff {
  return {
    issue: 0,
    pr: d.pr_number,
    branch: "",
    files: d.files.map((f) => ({
      path: f.filename,
      add: f.additions,
      del: f.deletions,
      lines: parsePatch(f.patch),
    })),
  };
}

// ── キュー (#96) ──

export interface ApiQueueEntry {
  repo: string;
  issue_number: number;
  phase: string;
  priority: number;
  enqueued_at: string;
  wait_reason: string;
}

export interface ApiQueueResponse {
  running: boolean;
  ts: string | null;
  reason: string | null;
  queued: ApiQueueEntry[];
  active: ApiQueueEntry[];
  paused: ApiQueueEntry[];
  max_total: number;
  max_per_repo: number;
}

export interface QueueRow {
  repo: string;
  issue: number;
  phase: string;
  priority: number;
  priorityLabel: string;
  enqueued: string;
  reason: string;
}

export interface QueueView {
  running: boolean;
  reason: string | null;
  queued: QueueRow[];
  activeCount: number;
  pausedCount: number;
  maxTotal: number;
}

const PRIORITY_LABEL: Record<number, string> = { 1: "critical", 2: "high", 5: "normal", 10: "low" };

function priorityLabel(priority: number): string {
  return PRIORITY_LABEL[priority] ?? `p${priority}`;
}

function adaptQueueRow(entry: ApiQueueEntry): QueueRow {
  return {
    repo: entry.repo,
    issue: entry.issue_number,
    phase: entry.phase,
    priority: entry.priority,
    priorityLabel: priorityLabel(entry.priority),
    enqueued: entry.enqueued_at ? formatRelative(entry.enqueued_at) : "",
    reason: entry.wait_reason,
  };
}

export function adaptQueue(q: ApiQueueResponse): QueueView {
  return {
    running: q.running,
    reason: q.reason,
    queued: q.queued.map(adaptQueueRow),
    activeCount: q.active.length,
    pausedCount: q.paused.length,
    maxTotal: q.max_total,
  };
}

// ── フェーズ別モデル設定 (#90) ──

export interface ApiPhaseModelRow {
  phase: string;
  model: string;
  thinking: boolean;
  max_turns: number | null;
}

export interface ApiPhaseModelsResponse {
  phases: ApiPhaseModelRow[];
  allowed_models: string[];
}

export interface PhaseModelInput {
  phase: string;
  model: string;
  thinking: boolean;
  max_turns: number | null;
}

// ── 書き込み API (#88) ──

/**
 * actor 導出ヘルパ。
 * "owner/repo" 形式から owner を返す。
 * #115 で実認証導入までの暫定実装。
 */
export function actorForRepo(repo: string): string {
  /* v8 ignore next -- split always returns at least one element; ?? "" is a defensive fallback that can never be reached */
  return repo.split("/")[0] ?? "";
}

// control action の型定義 (POST /api/control)
export type ControlAction =
  | { action: "pause" | "resume" | "abort" | "retry_with_analysis"; issue: number; actor: string }
  | { action: "enqueue_issue"; issue: number; actor: string }
  | { action: "shutdown" | "poll_now" | "worktree_gc"; actor: string }
  | { action: "set_priority"; issue: number; phase: string; priority: number; actor: string }
  | {
      action: "rewind";
      issue: number;
      target:
        | "intake"
        | "clarify"
        | "clarify-wait"
        | "split"
        | "plan"
        | "approve"
        | "implement"
        | "review"
        | "revise";
      actor: string;
    }
  | { action: "reorder"; order: { issue: number; phase: string }[]; actor: string };

export type ControlRequest = ControlAction;

async function apiSend<T>(method: string, path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, `API へ接続できません (${path})`);
  }
  if (!res.ok) {
    throw new ApiError(res.status, `API エラー ${res.status} (${path})`);
  }
  return (await res.json()) as T;
}

function apiPost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return apiSend<T>("POST", path, body, signal);
}

function apiPut<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return apiSend<T>("PUT", path, body, signal);
}

/** POST /api/control → 202 {accepted: true} */
export async function postControl(req: ControlRequest, signal?: AbortSignal): Promise<void> {
  await apiPost<{ accepted: boolean }>("/api/control", req, signal);
}

/**
 * グローバルコマンド (poll_now / worktree_gc 等) 用の actor を実データから導出する。
 * 監視中 Issue の repo owner = 既定の承認者を使う。取れなければ空文字
 * (orchestrator 側の認可で無視される)。#115 で実認証導入までの暫定。
 */
export async function getDefaultActor(signal?: AbortSignal): Promise<string> {
  try {
    const rows = await apiGet<ApiIssueSummary[]>("/api/issues", signal);
    return actorForRepo(rows[0]?.repo ?? "");
  } catch {
    return "";
  }
}

// ── 承認待ち (#88) ──

export interface ApiApprovalEntry {
  repo: string;
  issue_number: number;
  phase: "approve" | "review";
  pr_number: number | null;
  updated_at: string;
}

export interface ApprovalRow {
  repo: string;
  issue: number;
  phase: "approve" | "review";
  prNumber: number | null;
  updatedAt: string;
}

export function adaptApproval(a: ApiApprovalEntry): ApprovalRow {
  return {
    repo: a.repo,
    issue: a.issue_number,
    phase: a.phase,
    prNumber: a.pr_number,
    updatedAt: formatRelative(a.updated_at),
  };
}

/** GET /api/approvals */
export async function getApprovals(signal?: AbortSignal): Promise<ApprovalRow[]> {
  const rows = await apiGet<ApiApprovalEntry[]>("/api/approvals", signal);
  return rows.map(adaptApproval);
}

/** POST /api/issues/{n}/reply → 201 {posted: true} */
export async function postReply(issue: number, text: string, signal?: AbortSignal): Promise<void> {
  await apiPost<{ posted: boolean }>(`/api/issues/${issue}/reply`, { text }, signal);
}

// ── 設計レビュー (#89) ──

export interface ApiDesignAnchor {
  anchor: string;
  text: string;
}

export interface ApiDesignSubtask {
  anchor: string;
  id: number | null;
  title: string;
}

export interface ApiDesignResponse {
  present: boolean;
  plan_depth: string | null;
  ui_impact: boolean | null;
  summary: ApiDesignAnchor | null;
  test_cases: ApiDesignAnchor[];
  architecture: ApiDesignAnchor[];
  subtasks: ApiDesignSubtask[];
  reason: string | null;
}

export interface DesignView {
  present: boolean;
  planDepth: string | null;
  uiImpact: boolean | null;
  summary: ApiDesignAnchor | null;
  testCases: ApiDesignAnchor[];
  architecture: ApiDesignAnchor[];
  subtasks: ApiDesignSubtask[];
  reason: string | null;
}

export function adaptDesign(d: ApiDesignResponse): DesignView {
  return {
    present: d.present,
    planDepth: d.plan_depth,
    uiImpact: d.ui_impact,
    summary: d.summary,
    testCases: d.test_cases,
    architecture: d.architecture,
    subtasks: d.subtasks,
    reason: d.reason,
  };
}

/** GET /api/issues/{n}/design */
export async function getDesign(issue: number, signal?: AbortSignal): Promise<DesignView> {
  return adaptDesign(await apiGet<ApiDesignResponse>(`/api/issues/${issue}/design`, signal));
}

/** レビュー提出コメント (UI の DraftComment を API 形へ写したもの)。 */
export interface ReviewCommentInput {
  anchor: string;
  anchorLabel: string;
  tag: "指摘" | "質問";
  body: string;
}

export type ReviewOutcome = "approved" | "changes_requested" | "questions";

/** GET /api/config/phase-models */
export async function getPhaseModels(signal?: AbortSignal): Promise<ApiPhaseModelsResponse> {
  return apiGet<ApiPhaseModelsResponse>("/api/config/phase-models", signal);
}

/** PUT /api/config/phase-models */
export async function putPhaseModels(rows: PhaseModelInput[], signal?: AbortSignal): Promise<ApiPhaseModelsResponse> {
  return apiPut<ApiPhaseModelsResponse>("/api/config/phase-models", { phases: rows }, signal);
}

/** POST /api/issues/{n}/review → {outcome, accepted} */
export async function postReview(
  issue: number,
  comments: ReviewCommentInput[],
  actor: string,
  signal?: AbortSignal,
): Promise<ReviewOutcome> {
  const res = await apiPost<{ outcome: ReviewOutcome; accepted: boolean }>(
    `/api/issues/${issue}/review`,
    {
      comments: comments.map((c) => ({
        anchor: c.anchor,
        anchor_label: c.anchorLabel,
        tag: c.tag,
        body: c.body,
      })),
      actor,
    },
    signal,
  );
  return res.outcome;
}

// ── エンドポイント ──

export const api = {
  listIssues: (signal?: AbortSignal) =>
    apiGet<ApiIssueSummary[]>("/api/issues", signal).then((rows) => rows.map(adaptIssueSummary)),

  getIssue: async (n: number, signal?: AbortSignal): Promise<IssueDetail> => {
    const [detail, events] = await Promise.all([
      apiGet<ApiIssueDetail>(`/api/issues/${n}`, signal),
      apiGet<ApiEventRecord[]>(`/api/issues/${n}/events?limit=200`, signal),
    ]);
    return adaptIssueDetail(detail, events);
  },

  getActivity: (limit = 100, signal?: AbortSignal) =>
    apiGet<ApiEventRecord[]>(`/api/activity?limit=${limit}`, signal).then((rows) => ensureUniqueIds(rows.map(adaptEvent))),

  getHealth: (signal?: AbortSignal) => apiGet<ApiHealth>("/api/health", signal),

  getCosts: (signal?: AbortSignal) => apiGet<ApiCostsResponse>("/api/costs", signal),

  getDiff: (n: number, signal?: AbortSignal) =>
    apiGet<ApiDiffResponse>(`/api/issues/${n}/diff`, signal).then(adaptDiff),

  getQueue: (signal?: AbortSignal) => apiGet<ApiQueueResponse>("/api/queue", signal).then(adaptQueue),

  getApprovals: (signal?: AbortSignal) => getApprovals(signal),

  getDefaultActor: (signal?: AbortSignal) => getDefaultActor(signal),

  postControl: (req: ControlRequest, signal?: AbortSignal) => postControl(req, signal),

  postReply: (issue: number, text: string, signal?: AbortSignal) => postReply(issue, text, signal),

  getDesign: (issue: number, signal?: AbortSignal) => getDesign(issue, signal),

  postReview: (issue: number, comments: ReviewCommentInput[], actor: string, signal?: AbortSignal) =>
    postReview(issue, comments, actor, signal),

  getPhaseModels: (signal?: AbortSignal) => getPhaseModels(signal),

  putPhaseModels: (rows: PhaseModelInput[], signal?: AbortSignal) => putPhaseModels(rows, signal),
};

/** SSE ストリームの URL を組み立てる (EventSource 用、相対パス)。 */
export function streamUrl(issue: number): string {
  return `/api/stream?issue=${issue}`;
}
