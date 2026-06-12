import { describe, expect, it } from "vitest";
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
  type ApiAgentLogRecord,
  type ApiCostsResponse,
  type ApiDiffResponse,
  type ApiEventRecord,
  type ApiHealth,
  type ApiIssueDetail,
  type ApiIssueSummary,
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

  it("data.title 優先・無ければ event を人間表記化、cost を拾う", () => {
    expect(adaptEvent(ev("phase_completed", { title: "実装完了" })).title).toBe("実装完了");
    expect(adaptEvent(ev("phase_completed")).title).toBe("phase completed");
    expect(adaptEvent(ev("phase_completed", { cost_usd: 0.5 })).cost).toBe(0.5);
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
