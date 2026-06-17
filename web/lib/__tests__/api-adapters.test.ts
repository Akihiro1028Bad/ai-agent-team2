import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  adaptAgentLog,
  adaptCostRows,
  adaptDiff,
  adaptEvent,
  adaptHealth,
  adaptIssueDetail,
  adaptIssueSummary,
  formatRelative,
  normalizePhase,
  getPhaseModels,
  putPhaseModels,
  ApiError,
  api,
  type ApiAgentLogRecord,
  type ApiCostsResponse,
  type ApiDiffResponse,
  type ApiEventRecord,
  type ApiHealth,
  type ApiIssueDetail,
  type ApiIssueSummary,
  type ApiPhaseModelsResponse,
} from "@/lib/api";

function summary(overrides: Partial<ApiIssueSummary> = {}): ApiIssueSummary {
  return {
    number: 42,
    repo: "owner/repo",
    title: "テスト Issue",
    issue_type: "feature-m",
    phase: "implement",
    status: "running",
    cost_usd: 1.23,
    pr_number: 100,
    design_pr_number: null,
    branch_head_sha: "abcdef1234567890",
    retry_count: 0,
    created_at: "2026-06-12T00:00:00+00:00",
    updated_at: "2026-06-12T00:00:00+00:00",
    ...overrides,
  };
}

describe("adaptIssueSummary", () => {
  it("snake_case → camelCase へ名前変換し SHA を短縮する", () => {
    const s = adaptIssueSummary(summary());
    expect(s.costUsd).toBe(1.23);
    expect(s.prNumber).toBe(100);
    expect(s.branch).toBe("abcdef1"); // 先頭 7 桁
    expect(s.type).toBe("feature-m");
    expect(s.phase).toBe("implement");
  });

  it("title が null なら #番号 で補完する", () => {
    expect(adaptIssueSummary(summary({ title: null })).title).toBe("#42");
  });

  it("未知の issue_type は feature-m に倒す", () => {
    expect(adaptIssueSummary(summary({ issue_type: "weird" })).type).toBe("feature-m");
  });

  it("status=waiting なら needsHuman を立てる", () => {
    expect(adaptIssueSummary(summary({ status: "waiting" })).needsHuman).toBeTruthy();
    expect(adaptIssueSummary(summary({ status: "running" })).needsHuman).toBeUndefined();
  });

  it("pr_number/branch_head_sha が null なら undefined", () => {
    const s = adaptIssueSummary(summary({ pr_number: null, branch_head_sha: null }));
    expect(s.prNumber).toBeUndefined();
    expect(s.branch).toBeUndefined();
  });

  it("body_excerpt を bodyExcerpt へ写し、null/未指定なら undefined (#142)", () => {
    expect(adaptIssueSummary(summary({ body_excerpt: "本文の抜粋" })).bodyExcerpt).toBe("本文の抜粋");
    expect(adaptIssueSummary(summary({ body_excerpt: null })).bodyExcerpt).toBeUndefined();
    expect(adaptIssueSummary(summary()).bodyExcerpt).toBeUndefined();
  });
});

describe("normalizePhase", () => {
  it("既知 9 フェーズは素通し", () => {
    expect(normalizePhase("plan")).toBe("plan");
    expect(normalizePhase("done")).toBe("done");
  });
  it("clarify-wait は clarify に寄せる", () => {
    expect(normalizePhase("clarify-wait")).toBe("clarify");
  });
  it("blocked/suspended/未知は implement に倒す", () => {
    expect(normalizePhase("suspended")).toBe("implement");
    expect(normalizePhase("blocked")).toBe("implement");
    expect(normalizePhase("???")).toBe("implement");
  });
});

describe("adaptEvent", () => {
  const ev = (event: string, data: Record<string, unknown> | null = null): ApiEventRecord => ({
    ts: "2026-06-12T00:00:00+00:00",
    issue: 1,
    phase: "implement",
    event,
    data,
  });

  it("event 文字列から kind を判定する", () => {
    expect(adaptEvent(ev("ci_result")).kind).toBe("ci");
    expect(adaptEvent(ev("phase_completed")).kind).toBe("phase");
    expect(adaptEvent(ev("plan_comment_added")).kind).toBe("comment");
    expect(adaptEvent(ev("impl_pr_approved")).kind).toBe("gate");
    expect(adaptEvent(ev("ci_failure")).kind).toBe("error");
  });

  it("data.title 優先・無ければ event を日本語ラベル化、cost を拾う (#143)", () => {
    expect(adaptEvent(ev("phase_completed", { title: "実装完了" })).title).toBe("実装完了");
    // 既知イベントは日本語ラベルへ
    expect(adaptEvent(ev("phase_completed")).title).toBe("フェーズ完了");
    expect(adaptEvent(ev("phase_start")).title).toBe("フェーズ開始");
    expect(adaptEvent(ev("phase_transition")).title).toBe("フェーズ遷移");
    expect(adaptEvent(ev("split_approved")).title).toBe("分割を承認");
    expect(adaptEvent(ev("new_issue")).title).toBe("新規 Issue を受付");
    expect(adaptEvent(ev("phase_completed", { cost_usd: 0.5 })).cost).toBe(0.5);
  });

  it("未知イベントは underscore→space で素通しする (#143)", () => {
    expect(adaptEvent(ev("some_unknown_event")).title).toBe("some unknown event");
  });
});

describe("adaptIssueDetail", () => {
  it("同一 (issue,ts,event) のイベントでも id を一意化する", () => {
    const detail: ApiIssueDetail = { ...summary(), plan_json: null, session_id: null, impl_iteration: 0 };
    const dup: ApiEventRecord = { ts: "2026-06-12T00:00:00+00:00", issue: 42, phase: "implement", event: "phase_completed", data: null };
    const result = adaptIssueDetail(detail, [dup, dup, dup]);
    const ids = result.events.map((e) => e.id);
    expect(new Set(ids).size).toBe(3); // 重複なし
    expect(ids[0]).not.toContain("#"); // 先頭は素の id（既読の安定性を維持）
  });
});

describe("adaptAgentLog", () => {
  const base = { ts: "2026-06-12T01:02:03+00:00", phase: "implement" };

  it("text → agent レベル / 本文", () => {
    const l = adaptAgentLog({ ...base, type: "text", text: "やります" } as ApiAgentLogRecord);
    expect(l.level).toBe("agent");
    expect(l.text).toBe("やります");
    // ローカル時刻表示のため tz 非依存に形だけ検証する。
    expect(l.t).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it("tool_use → tool レベル / tool 名 / input 要約", () => {
    const l = adaptAgentLog({ ...base, type: "tool_use", tool: "Bash", input: { command: "pytest" } } as ApiAgentLogRecord);
    expect(l.level).toBe("tool");
    expect(l.source).toBe("Bash");
    expect(l.text).toBe("pytest");
  });

  it("result → is_error で ok/error を切替える", () => {
    expect(adaptAgentLog({ ...base, type: "result", is_error: false, cost_usd: 0.1 } as ApiAgentLogRecord).level).toBe("ok");
    expect(adaptAgentLog({ ...base, type: "result", is_error: true } as ApiAgentLogRecord).level).toBe("error");
  });
});

describe("adaptHealth", () => {
  it("API が持つ項目だけを返し、停止中は poller を error にする", () => {
    const h: ApiHealth = {
      running: false,
      stale: true,
      reason: "health.json が古い",
      ts: null,
      queue: { active: 2, queued: 1, max_total: 2 },
      repositories: ["owner/repo"],
      rate_limit: { remaining: 100, limit: 5000, reset: 0 },
      worktrees: 3,
      last_poll: {},
      accounts: {},
    };
    const items = adaptHealth(h);
    const keys = items.map((i) => i.key);
    expect(keys).toContain("poller");
    expect(keys).toContain("rate");
    expect(keys).toContain("agents");
    expect(keys).toContain("worktrees");
    expect(items.find((i) => i.key === "poller")?.status).toBe("error");
    // 実行枠が満杯 → warn
    expect(items.find((i) => i.key === "agents")?.status).toBe("warn");
  });

  it("rate_limit/worktrees が無ければ該当項目を出さない", () => {
    const h: ApiHealth = {
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
    const keys = adaptHealth(h).map((i) => i.key);
    expect(keys).toEqual(["poller"]);
  });
});

describe("adaptCostRows", () => {
  it("コスト降順に並べ、タイトルを JOIN する", () => {
    const c: ApiCostsResponse = {
      total_usd: 3,
      issues: [
        { repo: "r", issue_number: 1, cost_usd: 1, phases: {} },
        { repo: "r", issue_number: 2, cost_usd: 2, phases: {} },
      ],
    };
    const rows = adaptCostRows(c, new Map([[2, "二番"]]));
    expect(rows[0].issue).toBe(2);
    expect(rows[0].title).toBe("二番");
    expect(rows[1].title).toBe("#1"); // タイトル未知は #番号
  });
});

describe("adaptDiff", () => {
  it("patch をパースして DiffFile.lines に展開する", () => {
    const d: ApiDiffResponse = {
      pr_number: 7,
      files: [{ filename: "a.ts", status: "modified", additions: 1, deletions: 0, patch: "@@ -0,0 +1,1 @@\n+x" }],
    };
    const pr = adaptDiff(d);
    expect(pr.pr).toBe(7);
    expect(pr.files[0].path).toBe("a.ts");
    expect(pr.files[0].lines.some((l) => l.kind === "add" && l.text === "x")).toBe(true);
  });
});

describe("formatRelative", () => {
  it("秒/分/時間/日 を切り替える", () => {
    const now = new Date("2026-06-12T12:00:00Z").getTime();
    expect(formatRelative("2026-06-12T11:59:30Z", now)).toBe("30秒前");
    expect(formatRelative("2026-06-12T11:30:00Z", now)).toBe("30分前");
    expect(formatRelative("2026-06-12T09:00:00Z", now)).toBe("3時間前");
    expect(formatRelative("2026-06-10T12:00:00Z", now)).toBe("2日前");
  });
});

// ── フェーズ別モデル設定 API (#90) ──

const PHASE_MODELS_RESPONSE: ApiPhaseModelsResponse = {
  phases: [
    { phase: "intake", model: "haiku", thinking: false, max_turns: null },
    { phase: "clarify", model: "sonnet", thinking: false, max_turns: null },
    { phase: "plan", model: "sonnet", thinking: false, max_turns: null },
    { phase: "split", model: "sonnet", thinking: false, max_turns: null },
    { phase: "implement", model: "sonnet", thinking: false, max_turns: null },
    { phase: "revise", model: "sonnet", thinking: false, max_turns: null },
  ],
  allowed_models: ["haiku", "sonnet", "opus"],
};

describe("getPhaseModels", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時にレスポンスを返す", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(PHASE_MODELS_RESPONSE), { status: 200 }),
    );
    const result = await getPhaseModels();
    expect(result.phases).toHaveLength(6);
    expect(result.allowed_models).toContain("haiku");
    const called = vi.mocked(fetch).mock.calls[0];
    expect(called?.[0]).toBe("/api/config/phase-models");
  });

  it("非 200 は ApiError を throw する", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("bad", { status: 400 }),
    );
    await expect(getPhaseModels()).rejects.toBeInstanceOf(ApiError);
    await expect(getPhaseModels()).rejects.toMatchObject({ status: 400 });
  });

  it("ネットワーク到達不可は ApiError(0) を throw する", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("network"));
    await expect(getPhaseModels()).rejects.toMatchObject({ status: 0 });
  });

  it("AbortError は素通しで throw される", async () => {
    const abort = new DOMException("aborted", "AbortError");
    vi.mocked(fetch).mockRejectedValue(abort);
    await expect(getPhaseModels()).rejects.toBeInstanceOf(DOMException);
  });
});

describe("putPhaseModels", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("PUT メソッドで body を { phases: rows } に包んで送る", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(PHASE_MODELS_RESPONSE), { status: 200 }),
    );
    const rows = [{ phase: "plan", model: "opus", thinking: true, max_turns: 20 }];
    await putPhaseModels(rows);
    const [url, init] = vi.mocked(fetch).mock.calls[0]!;
    expect(url).toBe("/api/config/phase-models");
    expect((init as RequestInit).method).toBe("PUT");
    const sent = JSON.parse((init as RequestInit).body as string) as unknown;
    expect(sent).toEqual({ phases: rows });
  });

  it("非 200 は ApiError を throw する", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("bad", { status: 422 }),
    );
    await expect(putPhaseModels([])).rejects.toBeInstanceOf(ApiError);
    await expect(putPhaseModels([])).rejects.toMatchObject({ status: 422 });
  });

  it("ネットワーク到達不可は ApiError(0) を throw する", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("network"));
    await expect(putPhaseModels([])).rejects.toMatchObject({ status: 0 });
  });

  it("AbortError は素通しで throw される", async () => {
    const abort = new DOMException("aborted", "AbortError");
    vi.mocked(fetch).mockRejectedValue(abort);
    await expect(putPhaseModels([])).rejects.toBeInstanceOf(DOMException);
  });

  it("成功時にレスポンスを返す", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(PHASE_MODELS_RESPONSE), { status: 200 }),
    );
    const result = await putPhaseModels([{ phase: "plan", model: "opus", thinking: true, max_turns: 20 }]);
    expect(result.phases).toHaveLength(6);
  });
});

describe("api オブジェクト経由 (カバレッジ補完)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("api.getPhaseModels は getPhaseModels に委譲する", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(PHASE_MODELS_RESPONSE), { status: 200 }),
    );
    const result = await api.getPhaseModels();
    expect(result.phases).toHaveLength(6);
  });

  it("api.putPhaseModels は putPhaseModels に委譲する", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(PHASE_MODELS_RESPONSE), { status: 200 }),
    );
    const result = await api.putPhaseModels([{ phase: "plan", model: "opus", thinking: true, max_turns: 20 }]);
    expect(result.phases).toHaveLength(6);
  });
});

// ── マルチリポ ?repo= 引き回し (#118) ──

describe("withRepo (?repo= 引き回し)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const okDiff = () =>
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ pr_number: 1, files: [] } satisfies ApiDiffResponse), { status: 200 }),
    );

  it("repo 指定時は URL に encode した ?repo= を付与する", async () => {
    okDiff();
    await api.getDiff(7, "owner/repo");
    const [url] = vi.mocked(fetch).mock.calls[0]!;
    expect(url).toBe("/api/issues/7/diff?repo=owner%2Frepo");
  });

  it("repo 未指定時は素のパス (?repo= なし)", async () => {
    okDiff();
    await api.getDiff(7);
    const [url] = vi.mocked(fetch).mock.calls[0]!;
    expect(url).toBe("/api/issues/7/diff");
  });

  it("postReview も repo を付与する", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ outcome: "approved", accepted: true }), { status: 200 }),
    );
    await api.postReview(9, [], "owner", "o/r");
    const [url] = vi.mocked(fetch).mock.calls[0]!;
    expect(url).toBe("/api/issues/9/review?repo=o%2Fr");
  });
});
