// api.ts の fetch ラッパ (apiGet / apiPost) と getDefaultActor / postControl / streamUrl
// のブランチを全て通すテスト。node project (*.test.ts) で動作する。

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  ApiError,
  adaptQueue,
  formatClock,
  getDefaultActor,
  postControl,
  postReply,
  getApprovals,
  streamUrl,
  api,
  type ApiIssueSummary,
  type ApiQueueResponse,
  type ApiApprovalEntry,
} from "@/lib/api";

// ── fetch モック ────────────────────────────────────────────────────

function mockFetch(ok: boolean, json: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    json: () => Promise.resolve(json),
  } as unknown as Response);
}

function mockFetchThrow(err: unknown) {
  return vi.fn().mockRejectedValue(err);
}

function makeSummary(overrides: Partial<ApiIssueSummary> = {}): ApiIssueSummary {
  return {
    number: 1,
    repo: "owner/repo",
    title: "Test",
    issue_type: "feature-m",
    phase: "implement",
    status: "running",
    cost_usd: 0,
    pr_number: null,
    design_pr_number: null,
    branch_head_sha: null,
    retry_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});
afterEach(() => {
  vi.restoreAllMocks();
});

// ── streamUrl ─────────────────────────────────────────────────────

describe("streamUrl", () => {
  it("issue 番号を URL に含む", () => {
    expect(streamUrl(42)).toBe("/api/stream?issue=42");
  });
});

// ── formatClock ───────────────────────────────────────────────────

describe("formatClock", () => {
  it("ISO 文字列を HH:MM:SS 形式に変換する", () => {
    // タイムゾーン非依存: ローカル時間の形式チェックのみ
    const result = formatClock("2026-06-12T01:02:03Z");
    expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it("パース不能文字列はそのまま返す", () => {
    expect(formatClock("invalid-date")).toBe("invalid-date");
  });
});

// ── apiGet (fetch ラッパ) ─────────────────────────────────────────

describe("apiGet via api.getHealth", () => {
  it("ok レスポンスは JSON をパースして返す", async () => {
    const healthData = {
      running: true,
      stale: false,
      reason: null,
      ts: null,
      queue: null,
      repositories: [],
      rate_limit: null,
      worktrees: null,
      last_poll: {},
      accounts: {},
    };
    globalThis.fetch = mockFetch(true, healthData);

    const result = await api.getHealth();
    expect(result.running).toBe(true);
  });

  it("!res.ok なら ApiError を throw する", async () => {
    globalThis.fetch = mockFetch(false, {}, 503);

    await expect(api.getHealth()).rejects.toBeInstanceOf(ApiError);
    await expect(api.getHealth()).rejects.toMatchObject({ status: 503 });
  });

  it("ネットワーク例外は ApiError(0) に変換される", async () => {
    globalThis.fetch = mockFetchThrow(new TypeError("Failed to fetch"));

    await expect(api.getHealth()).rejects.toBeInstanceOf(ApiError);
    await expect(api.getHealth()).rejects.toMatchObject({ status: 0 });
  });

  it("AbortError はそのまま再 throw される", async () => {
    const abortErr = new DOMException("Aborted", "AbortError");
    globalThis.fetch = mockFetchThrow(abortErr);

    await expect(api.getHealth()).rejects.toBe(abortErr);
  });
});

// ── apiPost (fetch ラッパ) ────────────────────────────────────────

describe("postControl (apiPost)", () => {
  it("ok レスポンスは正常終了する", async () => {
    globalThis.fetch = mockFetch(true, { accepted: true }, 202);

    await expect(
      postControl({ action: "pause", issue: 1, actor: "owner" }),
    ).resolves.toBeUndefined();
  });

  it("!res.ok なら ApiError を throw する", async () => {
    globalThis.fetch = mockFetch(false, {}, 422);

    await expect(
      postControl({ action: "pause", issue: 1, actor: "owner" }),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("ネットワーク例外は ApiError(0) に変換される", async () => {
    globalThis.fetch = mockFetchThrow(new TypeError("Failed"));

    await expect(
      postControl({ action: "pause", issue: 1, actor: "owner" }),
    ).rejects.toMatchObject({ status: 0 });
  });

  it("AbortError はそのまま再 throw される", async () => {
    const abortErr = new DOMException("Aborted", "AbortError");
    globalThis.fetch = mockFetchThrow(abortErr);

    await expect(
      postControl({ action: "pause", issue: 1, actor: "owner" }),
    ).rejects.toBe(abortErr);
  });
});

// ── getDefaultActor ────────────────────────────────────────────────

describe("getDefaultActor", () => {
  it("issues API から最初の repo の owner を返す", async () => {
    globalThis.fetch = mockFetch(true, [makeSummary({ repo: "myorg/myrepo" })]);

    const actor = await getDefaultActor();
    expect(actor).toBe("myorg");
  });

  it("issues API が空配列なら空文字を返す", async () => {
    globalThis.fetch = mockFetch(true, []);

    const actor = await getDefaultActor();
    expect(actor).toBe("");
  });

  it("fetch がエラーになっても空文字を返す (catch)", async () => {
    globalThis.fetch = mockFetchThrow(new Error("network"));

    const actor = await getDefaultActor();
    expect(actor).toBe("");
  });
});

// ── postReply ─────────────────────────────────────────────────────

describe("postReply", () => {
  it("ok レスポンスは正常終了する", async () => {
    globalThis.fetch = mockFetch(true, { posted: true }, 201);
    await expect(postReply(42, "回答テキスト")).resolves.toBeUndefined();
  });
});

// ── getApprovals ──────────────────────────────────────────────────

describe("getApprovals", () => {
  it("rows を adaptApproval を通して返す", async () => {
    const entry: ApiApprovalEntry = {
      repo: "owner/repo",
      issue_number: 5,
      phase: "approve",
      pr_number: 10,
      updated_at: "2026-06-12T00:00:00Z",
    };
    globalThis.fetch = mockFetch(true, [entry]);

    const rows = await getApprovals();
    expect(rows).toHaveLength(1);
    expect(rows[0].issue).toBe(5);
    expect(rows[0].prNumber).toBe(10);
  });
});

// ── api.listIssues ────────────────────────────────────────────────

describe("api.listIssues", () => {
  it("ApiIssueSummary[] を IssueSummary[] に変換して返す", async () => {
    globalThis.fetch = mockFetch(true, [makeSummary({ title: "My Issue" })]);

    const issues = await api.listIssues();
    expect(issues).toHaveLength(1);
    expect(issues[0].title).toBe("My Issue");
  });
});

// ── api.getIssue ──────────────────────────────────────────────────

describe("api.getIssue", () => {
  it("detail と events を組み合わせた IssueDetail を返す", async () => {
    const detail = { ...makeSummary(), plan_json: null, session_id: null, impl_iteration: 0 };
    let callCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(detail) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
    }) as unknown as typeof fetch;

    const issue = await api.getIssue(1);
    expect(issue.number).toBe(1);
    expect(issue.events).toEqual([]);
  });
});

// ── api.getActivity ───────────────────────────────────────────────

describe("api.getActivity", () => {
  it("イベントリストを adaptEvent で変換して返す", async () => {
    const eventRecord = {
      ts: "2026-06-12T00:00:00Z",
      issue: 1,
      phase: "implement",
      event: "phase_started",
      data: null,
    };
    globalThis.fetch = mockFetch(true, [eventRecord]);

    const activity = await api.getActivity();
    expect(activity).toHaveLength(1);
  });
});

// ── api.getCosts ──────────────────────────────────────────────────

describe("api.getCosts", () => {
  it("ApiCostsResponse をそのまま返す", async () => {
    const costs = { total_usd: 5, issues: [] };
    globalThis.fetch = mockFetch(true, costs);

    const result = await api.getCosts();
    expect(result.total_usd).toBe(5);
  });
});

// ── api.getDiff ───────────────────────────────────────────────────

describe("api.getDiff", () => {
  it("ApiDiffResponse を PrDiff に変換して返す", async () => {
    const diffResp = { pr_number: 7, files: [] };
    globalThis.fetch = mockFetch(true, diffResp);

    const diff = await api.getDiff(42);
    expect(diff.pr).toBe(7);
  });
});

// ── api.getQueue ──────────────────────────────────────────────────

describe("api.getQueue", () => {
  it("ApiQueueResponse を QueueView に変換して返す", async () => {
    const q: ApiQueueResponse = {
      running: true,
      ts: null,
      reason: null,
      queued: [],
      active: [],
      paused: [],
      max_total: 4,
      max_per_repo: 2,
    };
    globalThis.fetch = mockFetch(true, q);

    const view = await api.getQueue();
    expect(view.running).toBe(true);
    expect(view.maxTotal).toBe(4);
  });
});

// ── api.getApprovals (api wrapper) ───────────────────────────────

describe("api.getApprovals", () => {
  it("approval rows を返す", async () => {
    globalThis.fetch = mockFetch(true, []);
    const rows = await api.getApprovals();
    expect(rows).toEqual([]);
  });
});

// ── api.postControl (api wrapper) ────────────────────────────────

describe("api.postControl", () => {
  it("postControl を呼び出せる", async () => {
    globalThis.fetch = mockFetch(true, { accepted: true }, 202);
    await expect(
      api.postControl({ action: "resume", issue: 1, actor: "owner" }),
    ).resolves.toBeUndefined();
  });
});

// ── api.postReply (api wrapper) ───────────────────────────────────

describe("api.postReply", () => {
  it("postReply を呼び出せる", async () => {
    globalThis.fetch = mockFetch(true, { posted: true }, 201);
    await expect(api.postReply(1, "text")).resolves.toBeUndefined();
  });
});

// ── api.getDefaultActor (api wrapper) ────────────────────────────

describe("api.getDefaultActor", () => {
  it("getDefaultActor を呼び出せる", async () => {
    globalThis.fetch = mockFetch(true, [makeSummary({ repo: "org/repo" })]);
    const actor = await api.getDefaultActor();
    expect(actor).toBe("org");
  });
});

// ── adaptQueue: priorityLabel フォールバック ───────────────────────

describe("adaptQueue: priorityLabel フォールバック", () => {
  it("PRIORITY_LABEL に無い優先度は p{n} を使う", () => {
    const q: ApiQueueResponse = {
      running: true,
      ts: null,
      reason: null,
      queued: [
        {
          repo: "owner/repo",
          issue_number: 1,
          phase: "implement",
          priority: 7, // PRIORITY_LABEL にない
          enqueued_at: "2026-06-12T00:00:00Z",
          wait_reason: "待機",
        },
      ],
      active: [],
      paused: [],
      max_total: 2,
      max_per_repo: 1,
    };
    const view = adaptQueue(q);
    expect(view.queued[0].priorityLabel).toBe("p7");
  });

  it("enqueued_at が空文字のとき enqueued は空文字", () => {
    const q: ApiQueueResponse = {
      running: true,
      ts: null,
      reason: "停止",
      queued: [
        {
          repo: "owner/repo",
          issue_number: 2,
          phase: "plan",
          priority: 5,
          enqueued_at: "", // falsy
          wait_reason: "",
        },
      ],
      active: [],
      paused: [
        {
          repo: "owner/repo",
          issue_number: 3,
          phase: "review",
          priority: 2,
          enqueued_at: "2026-06-12T00:00:00Z",
          wait_reason: "paused",
        },
      ],
      max_total: 4,
      max_per_repo: 2,
    };
    const view = adaptQueue(q);
    expect(view.queued[0].enqueued).toBe("");
    expect(view.pausedCount).toBe(1);
  });
});

// ── ApiError.isUnreachable ────────────────────────────────────────

describe("ApiError.isUnreachable", () => {
  it("status=0 のとき true", () => {
    expect(new ApiError(0, "x").isUnreachable).toBe(true);
  });

  it("status!=0 のとき false", () => {
    expect(new ApiError(500, "x").isUnreachable).toBe(false);
  });
});

// ── adaptHealth: last_poll あり ────────────────────────────────────

describe("adaptHealth: running=true かつ last_poll あり", () => {
  it("poller の detail が最終ポーリング を含む", async () => {
    const { adaptHealth } = await import("@/lib/api");
    const items = adaptHealth({
      running: true,
      stale: false,
      reason: null,
      ts: null,
      queue: null,
      repositories: [],
      rate_limit: null,
      worktrees: null,
      last_poll: { "owner/repo": "2026-06-12T00:00:00Z" },
      accounts: {},
    });
    const poller = items.find((i) => i.key === "poller");
    expect(poller?.status).toBe("ok");
    expect(poller?.detail).toMatch(/最終ポーリング/);
  });

  it("running=false かつ last_poll なし → reason を detail に使う", async () => {
    const { adaptHealth } = await import("@/lib/api");
    const items = adaptHealth({
      running: false,
      stale: false,
      reason: "強制停止",
      ts: null,
      queue: null,
      repositories: [],
      rate_limit: null,
      worktrees: null,
      last_poll: {},
      accounts: {},
    });
    const poller = items.find((i) => i.key === "poller");
    expect(poller?.detail).toBe("強制停止");
  });

  it("rate_limit.remaining / limit < 0.1 で warn", async () => {
    const { adaptHealth } = await import("@/lib/api");
    const items = adaptHealth({
      running: true,
      stale: false,
      reason: null,
      ts: null,
      queue: null,
      repositories: [],
      rate_limit: { remaining: 1, limit: 100 }, // 1% < 10%
      worktrees: null,
      last_poll: {},
      accounts: {},
    });
    const rate = items.find((i) => i.key === "rate");
    expect(rate?.status).toBe("warn");
  });

  it("rate_limit.limit=0 のとき ok (ゼロ除算回避)", async () => {
    const { adaptHealth } = await import("@/lib/api");
    const items = adaptHealth({
      running: true,
      stale: false,
      reason: null,
      ts: null,
      queue: null,
      repositories: [],
      rate_limit: { remaining: 0, limit: 0 },
      worktrees: null,
      last_poll: {},
      accounts: {},
    });
    const rate = items.find((i) => i.key === "rate");
    expect(rate?.status).toBe("ok");
  });

  it("queue.active < max_total なら agents は ok", async () => {
    const { adaptHealth } = await import("@/lib/api");
    const items = adaptHealth({
      running: true,
      stale: false,
      reason: null,
      ts: null,
      queue: { active: 1, queued: 0, max_total: 4 },
      repositories: [],
      rate_limit: null,
      worktrees: null,
      last_poll: {},
      accounts: {},
    });
    const agents = items.find((i) => i.key === "agents");
    expect(agents?.status).toBe("ok");
  });
});

// ── adaptAgentLog: edge cases ─────────────────────────────────────

describe("adaptAgentLog: edge cases", () => {
  it("tool_use で input が object でないとき summary は空文字", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "implement",
      type: "tool_use",
      tool: "Read",
      input: null, // not an object
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.text).toBe("");
  });

  it("tool_use で input に file_path があれば使う", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "implement",
      type: "tool_use",
      input: { file_path: "/tmp/test.ts" },
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.text).toBe("/tmp/test.ts");
  });

  it("tool_use で input に path があれば使う", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "implement",
      type: "tool_use",
      input: { path: "/tmp/dir" },
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.text).toBe("/tmp/dir");
  });

  it("tool_use で input に description があれば使う", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "implement",
      type: "tool_use",
      input: { description: "test desc" },
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.text).toBe("test desc");
  });

  it("result に cost/duration があれば parts に追加する", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "implement",
      type: "result",
      is_error: false,
      cost_usd: 0.1234,
      duration_ms: 1500,
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.text).toContain("完了");
    expect(log.text).toContain("$0.1234");
    expect(log.text).toContain("1500ms");
  });

  it("preset type は info レベル", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "implement",
      type: "preset",
      text: "preset text",
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.level).toBe("info");
  });

  it("不明な type は humanize される", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "implement",
      type: "unknown_type",
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.text).toBe("unknown type");
  });

  it("ts が空のとき t は空文字", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "",
      phase: "implement",
      type: "text",
      text: "hello",
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.t).toBe("");
  });

  it("tool_use: source は tool 名、tool が未指定なら 'tool'", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "implement",
      type: "tool_use",
      input: {},
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.source).toBe("tool");
  });

  it("type=text で text が空/未定義のとき text は空文字", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "implement",
      type: "text",
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.text).toBe("");
  });

  it("phase が空のとき source は 'agent'", async () => {
    const { adaptAgentLog } = await import("@/lib/api");
    const log = adaptAgentLog({
      ts: "2026-06-12T01:02:03Z",
      phase: "",
      type: "text",
      text: "hi",
    } as unknown as import("@/lib/api").ApiAgentLogRecord);
    expect(log.source).toBe("agent");
  });
});

// ── adaptIssueDetail: plan_json with subtasks ──────────────────────

describe("adaptIssueDetail: plan_json subtasks", () => {
  it("plan_json.subtasks から subtasks を抽出する", async () => {
    const { adaptIssueDetail } = await import("@/lib/api");
    const detail = {
      ...makeSummary(),
      plan_json: {
        subtasks: [
          { id: 1, title: "タスク1", done: false },
          { id: 2, title: "タスク2", done: true },
        ],
      },
      session_id: null,
      impl_iteration: 0,
    };
    const issue = adaptIssueDetail(detail, []);
    expect(issue.subtasks).toHaveLength(2);
    expect(issue.subtasks![0].title).toBe("タスク1");
    expect(issue.subtasks![1].done).toBe(true);
  });

  it("plan_json.subtasks が空配列のとき subtasks は undefined", async () => {
    const { adaptIssueDetail } = await import("@/lib/api");
    const detail = {
      ...makeSummary(),
      plan_json: { subtasks: [] },
      session_id: null,
      impl_iteration: 0,
    };
    const issue = adaptIssueDetail(detail, []);
    expect(issue.subtasks).toBeUndefined();
  });

  it("subtask の id が数値でないとき index+1 を使う、title がないとき 'subtask N'", async () => {
    const { adaptIssueDetail } = await import("@/lib/api");
    const detail = {
      ...makeSummary(),
      plan_json: {
        subtasks: [
          {}, // id も title もない
        ],
      },
      session_id: null,
      impl_iteration: 0,
    };
    const issue = adaptIssueDetail(detail, []);
    expect(issue.subtasks![0].id).toBe(1);
    expect(issue.subtasks![0].title).toBe("subtask 1");
  });

  it("plan_json.subtasks に非 object が混在しても無視される", async () => {
    const { adaptIssueDetail } = await import("@/lib/api");
    const detail = {
      ...makeSummary(),
      plan_json: {
        subtasks: [null, { id: 1, title: "valid", done: false }, undefined],
      },
      session_id: null,
      impl_iteration: 0,
    };
    const issue = adaptIssueDetail(detail, []);
    expect(issue.subtasks).toHaveLength(1);
  });
});

// ── adaptEvent: detail/cost フォールバック ─────────────────────────

describe("adaptEvent: detail/cost フォールバック", () => {
  it("data.message を detail に使う (detail が無い場合)", async () => {
    const { adaptEvent } = await import("@/lib/api");
    const ev = adaptEvent({
      ts: "2026-06-12T00:00:00Z",
      issue: 1,
      phase: "implement",
      event: "phase_started",
      data: { message: "メッセージ" },
    });
    expect(ev.detail).toBe("メッセージ");
  });

  it("issue が null のとき id は ':ts:event' 形式", async () => {
    const { adaptEvent } = await import("@/lib/api");
    const ev = adaptEvent({
      ts: "2026-06-12T00:00:00Z",
      issue: null,
      phase: "implement",
      event: "phase_started",
      data: null,
    });
    expect(ev.id).toMatch(/^:2026-06-12/);
  });
});

// ── adaptCostRows: titleByIssue デフォルト引数 ─────────────────────

describe("adaptCostRows: titleByIssue デフォルト引数", () => {
  it("titleByIssue を省略すると Map() が使われる", async () => {
    const { adaptCostRows } = await import("@/lib/api");
    const rows = adaptCostRows({
      total_usd: 1,
      issues: [{ repo: "r", issue_number: 1, cost_usd: 1, phases: {} }],
    });
    expect(rows[0].title).toBe("#1");
  });
});

// ── adaptHealth: rate_limit/queue フィールド欠落時の ?? 0 フォールバック ──────

describe("adaptHealth: 欠落フィールドの ?? 0 フォールバック", () => {
  it("rate_limit の remaining/limit が undefined のとき 0 を使う", async () => {
    const { adaptHealth } = await import("@/lib/api");
    const items = adaptHealth({
      running: true,
      stale: false,
      reason: null,
      ts: null,
      queue: null,
      repositories: [],
      rate_limit: {} as unknown as Record<string, number>, // missing remaining/limit
      worktrees: null,
      last_poll: {},
      accounts: {},
    });
    const rate = items.find((i) => i.key === "rate");
    expect(rate).toBeDefined();
    // remaining=0, limit=0 → ok (limit=0 prevents division)
    expect(rate?.status).toBe("ok");
    expect(rate?.value).toBe("0 / 0");
  });

  it("queue の active/max_total/queued が undefined のとき 0 を使う", async () => {
    const { adaptHealth } = await import("@/lib/api");
    const items = adaptHealth({
      running: true,
      stale: false,
      reason: null,
      ts: null,
      queue: {} as unknown as Record<string, number>, // missing active/max_total/queued
      repositories: [],
      rate_limit: null,
      worktrees: null,
      last_poll: {},
      accounts: {},
    });
    const agents = items.find((i) => i.key === "agents");
    expect(agents).toBeDefined();
    // active=0, maxTotal=0 → ok (maxTotal=0 prevents >= check)
    expect(agents?.status).toBe("ok");
    expect(agents?.detail).toBe("待機 0 件");
  });
});

// ── adaptHealth: eventKind default path ──────────────────────────

describe("eventKind: マッチしないイベント名はデフォルト 'phase'", () => {
  it("どのルールにもマッチしない event 名は 'phase' を返す", async () => {
    const { adaptEvent } = await import("@/lib/api");
    // "something_happened" はどのルールにも該当しない
    const ev = adaptEvent({
      ts: "2026-06-12T00:00:00Z",
      issue: 1,
      phase: "implement",
      event: "something_happened",
      data: null,
    });
    expect(ev.kind).toBe("phase");
  });
});

// ── adaptIssueSummary: design_pr_number あり ─────────────────────

describe("adaptIssueSummary: design_pr_number あり", () => {
  it("design_pr_number が非 null なら designPrNumber にセットされる", async () => {
    const { adaptIssueSummary } = await import("@/lib/api");
    const s = adaptIssueSummary({
      ...makeSummary(),
      design_pr_number: 55,
    });
    expect(s.designPrNumber).toBe(55);
  });
});

// ── eventKind: 全ルール ───────────────────────────────────────────

describe("eventKind 全ルール", () => {
  it("commit/push/pull_request → commit", async () => {
    const { adaptEvent } = await import("@/lib/api");
    expect(adaptEvent({ ts: "t", issue: 1, phase: "p", event: "push_commit", data: null }).kind).toBe("commit");
    expect(adaptEvent({ ts: "t", issue: 1, phase: "p", event: "pull_request_opened", data: null }).kind).toBe("commit");
    expect(adaptEvent({ ts: "t", issue: 1, phase: "p", event: "merge_completed", data: null }).kind).toBe("commit");
  });

  it("agent/tool/claude → agent", async () => {
    const { adaptEvent } = await import("@/lib/api");
    expect(adaptEvent({ ts: "t", issue: 1, phase: "p", event: "agent_started", data: null }).kind).toBe("agent");
    expect(adaptEvent({ ts: "t", issue: 1, phase: "p", event: "tool_call", data: null }).kind).toBe("agent");
    expect(adaptEvent({ ts: "t", issue: 1, phase: "p", event: "claude_response", data: null }).kind).toBe("agent");
  });
});

// ── 設計レビュー: getDesign / adaptDesign / postReview (#89) ──────────

describe("getDesign / adaptDesign", () => {
  it("snake_case の DesignResponse を camelCase の DesignView へ写す", async () => {
    const { getDesign } = await import("@/lib/api");
    const payload = {
      present: true,
      plan_depth: "full",
      ui_impact: true,
      summary: { anchor: "sum-1", text: "概要" },
      test_cases: [{ anchor: "tc-01", text: "T1" }],
      architecture: [{ anchor: "arch-1", text: "A1" }],
      subtasks: [{ anchor: "st-1", id: 5, title: "ST" }],
      reason: null,
    };
    vi.stubGlobal("fetch", mockFetch(true, payload));
    const view = await getDesign(7);
    expect(view.present).toBe(true);
    expect(view.planDepth).toBe("full");
    expect(view.uiImpact).toBe(true);
    expect(view.summary).toEqual({ anchor: "sum-1", text: "概要" });
    expect(view.testCases).toEqual([{ anchor: "tc-01", text: "T1" }]);
    expect(view.architecture).toEqual([{ anchor: "arch-1", text: "A1" }]);
    expect(view.subtasks).toEqual([{ anchor: "st-1", id: 5, title: "ST" }]);
    expect(view.reason).toBeNull();
  });

  it("present=false (reason 付き) も写す", async () => {
    const { adaptDesign } = await import("@/lib/api");
    const view = adaptDesign({
      present: false,
      plan_depth: null,
      ui_impact: null,
      summary: null,
      test_cases: [],
      architecture: [],
      subtasks: [],
      reason: "未生成",
    });
    expect(view.present).toBe(false);
    expect(view.reason).toBe("未生成");
    expect(view.summary).toBeNull();
  });
});

describe("postReview", () => {
  it("DraftComment を snake_case の payload へ写して送り、outcome を返す", async () => {
    const { postReview } = await import("@/lib/api");
    const fetchMock = mockFetch(true, { outcome: "changes_requested", accepted: true });
    vi.stubGlobal("fetch", fetchMock);

    const outcome = await postReview(
      7,
      [{ anchor: "tc-01", anchorLabel: "ケース", tag: "指摘", body: "誤り" }],
      "alice",
    );
    expect(outcome).toBe("changes_requested");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/issues/7/review");
    const sent = JSON.parse((init as RequestInit).body as string);
    expect(sent.actor).toBe("alice");
    expect(sent.comments).toEqual([{ anchor: "tc-01", anchor_label: "ケース", tag: "指摘", body: "誤り" }]);
  });

  it("空コメントの承認提出で approved を返す", async () => {
    const { postReview } = await import("@/lib/api");
    vi.stubGlobal("fetch", mockFetch(true, { outcome: "approved", accepted: true }));
    expect(await postReview(7, [], "alice")).toBe("approved");
  });

  it("API エラーは ApiError を投げる", async () => {
    const { postReview } = await import("@/lib/api");
    vi.stubGlobal("fetch", mockFetch(false, null, 404));
    await expect(postReview(99, [], "a")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("api.getDesign / api.postReview デリゲート", () => {
  it("api.getDesign は getDesign に委譲する", async () => {
    vi.stubGlobal("fetch", mockFetch(true, {
      present: true, plan_depth: "light", ui_impact: null,
      summary: null, test_cases: [], architecture: [], subtasks: [], reason: null,
    }));
    const view = await api.getDesign(3);
    expect(view.present).toBe(true);
    expect(view.planDepth).toBe("light");
  });

  it("api.postReview は postReview に委譲する", async () => {
    vi.stubGlobal("fetch", mockFetch(true, { outcome: "questions", accepted: true }));
    const outcome = await api.postReview(3, [{ anchor: "sum-1", anchorLabel: "", tag: "質問", body: "?" }], "a");
    expect(outcome).toBe("questions");
  });
});
