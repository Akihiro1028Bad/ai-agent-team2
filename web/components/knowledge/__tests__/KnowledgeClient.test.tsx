import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KnowledgeView } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, getKnowledge: vi.fn() },
  };
});

import { api } from "@/lib/api";
import { KnowledgeClient } from "@/components/knowledge/KnowledgeClient";

const EMPTY: KnowledgeView = {
  stats: { episodes: 0, successRate: 0, patterns: 0, skills: 0 },
  episodes: [],
  patterns: [],
  skills: [],
};

const POPULATED: KnowledgeView = {
  stats: { episodes: 4, successRate: 0.75, patterns: 1, skills: 1 },
  episodes: [
    {
      id: "ep-1",
      issue: 7,
      repo: "o/r",
      phase: "implement",
      outcome: "failure",
      summary: "CI 失敗",
      lesson: "固定クロックを使う",
      at: "1分前",
    },
  ],
  patterns: [
    {
      id: "pat-1",
      title: "固定クロックを使う",
      description: "3回観測",
      confidence: 1,
      occurrences: 3,
      status: "promoted",
    },
  ],
  skills: [{ id: "sk-1", name: "fixed-clock", fromPattern: "pat-1", usedCount: 0, successRate: 1, updated: "1分前" }],
};

beforeEach(() => {
  vi.clearAllMocks();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("KnowledgeClient", () => {
  it("読み込み中表示を出す", () => {
    vi.mocked(api.getKnowledge).mockReturnValue(new Promise(() => {}));
    render(<KnowledgeClient />);
    expect(screen.getByText("読み込み中…")).toBeDefined();
  });

  it("エピソード 0 件で空状態を表示する", async () => {
    vi.mocked(api.getKnowledge).mockResolvedValue(EMPTY);
    render(<KnowledgeClient />);
    expect(await screen.findByText(/まだエピソードがありません/)).toBeDefined();
  });

  it("統計・パターン・Skill・エピソードを表示する (#93)", async () => {
    vi.mocked(api.getKnowledge).mockResolvedValue(POPULATED);
    render(<KnowledgeClient />);
    // 成功率 75%
    expect(await screen.findByText("75%")).toBeDefined();
    expect(screen.getByText("固定クロックを使う")).toBeDefined();
    expect(screen.getByText("昇格済み")).toBeDefined();
    expect(screen.getByText("fixed-clock")).toBeDefined();
    expect(screen.getByText("CI 失敗")).toBeDefined();
    expect(screen.getByText(/教訓: 固定クロックを使う/)).toBeDefined();
  });

  it("取得失敗でエラーメッセージを出す", async () => {
    vi.mocked(api.getKnowledge).mockRejectedValue(new Error("fail"));
    render(<KnowledgeClient />);
    expect(await screen.findByText(/ナレッジの取得に失敗しました/)).toBeDefined();
  });
});
