import { describe, expect, it } from "vitest";
import { actorForRepo, adaptApproval, type ApiApprovalEntry } from "@/lib/api";

describe("actorForRepo", () => {
  it("owner/repo から owner を返す", () => {
    expect(actorForRepo("owner/repo")).toBe("owner");
  });

  it("スラッシュなしの場合はそのまま返す", () => {
    expect(actorForRepo("owner")).toBe("owner");
  });

  it("空文字列の場合は空文字を返す", () => {
    expect(actorForRepo("")).toBe("");
  });

  it("スラッシュで始まる場合は空文字を返す", () => {
    expect(actorForRepo("/repo")).toBe("");
  });
});

describe("adaptApproval", () => {
  const base: ApiApprovalEntry = {
    repo: "owner/repo",
    issue_number: 42,
    phase: "approve",
    pr_number: null,
    updated_at: "2026-06-12T00:00:00+00:00",
  };

  it("フィールドを正しくマッピングする", () => {
    const result = adaptApproval(base);
    expect(result.repo).toBe("owner/repo");
    expect(result.issue).toBe(42);
    expect(result.phase).toBe("approve");
    expect(result.prNumber).toBeNull();
  });

  it("pr_number を prNumber に変換する", () => {
    const result = adaptApproval({ ...base, pr_number: 100 });
    expect(result.prNumber).toBe(100);
  });

  it("updated_at を相対表記に変換する", () => {
    const result = adaptApproval(base);
    // 相対表記が文字列として返る (実際の値は実行時刻依存)
    expect(typeof result.updatedAt).toBe("string");
    expect(result.updatedAt.length).toBeGreaterThan(0);
  });
});
