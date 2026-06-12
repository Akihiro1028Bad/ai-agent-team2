import { describe, expect, it } from "vitest";
import { toRows, toInputs, PHASE_META, type PhaseModelRow } from "@/lib/model-config";
import type { ApiPhaseModelsResponse } from "@/lib/api";

function makeApiResponse(overrides: Partial<ApiPhaseModelsResponse> = {}): ApiPhaseModelsResponse {
  return {
    phases: [
      { phase: "intake", model: "haiku", thinking: false, max_turns: null },
      { phase: "clarify", model: "sonnet", thinking: false, max_turns: null },
      { phase: "plan", model: "opus", thinking: true, max_turns: 20 },
      { phase: "split", model: "sonnet", thinking: false, max_turns: null },
      { phase: "implement", model: "sonnet", thinking: false, max_turns: null },
      { phase: "revise", model: "sonnet", thinking: false, max_turns: null },
    ],
    allowed_models: ["haiku", "sonnet", "opus"],
    ...overrides,
  };
}

describe("toRows", () => {
  it("API フェーズを UI 行に変換する", () => {
    const rows = toRows(makeApiResponse());
    expect(rows).toHaveLength(6);
    const plan = rows.find((r) => r.phase === "plan")!;
    expect(plan.model).toBe("opus");
    expect(plan.thinking).toBe(true);
    expect(plan.maxTurns).toBe(20);
    expect(plan.label).toBe(PHASE_META.plan!.label);
    expect(plan.hint).toBe(PHASE_META.plan!.hint);
  });

  it("max_turns が null の場合は PHASE_META.defaultMaxTurns を使う", () => {
    const rows = toRows(makeApiResponse());
    const intake = rows.find((r) => r.phase === "intake")!;
    expect(intake.maxTurns).toBe(PHASE_META.intake!.defaultMaxTurns);
    const clarify = rows.find((r) => r.phase === "clarify")!;
    expect(clarify.maxTurns).toBe(PHASE_META.clarify!.defaultMaxTurns);
  });

  it("max_turns が null でない場合はそのまま使う", () => {
    const rows = toRows(makeApiResponse());
    const plan = rows.find((r) => r.phase === "plan")!;
    expect(plan.maxTurns).toBe(20);
  });

  it("PHASE_META に存在しない未知フェーズはスキップする", () => {
    const res = makeApiResponse({
      phases: [
        { phase: "intake", model: "haiku", thinking: false, max_turns: null },
        { phase: "unknown_phase", model: "sonnet", thinking: false, max_turns: null },
      ],
    });
    const rows = toRows(res);
    expect(rows).toHaveLength(1);
    expect(rows[0]!.phase).toBe("intake");
  });

  it("全フェーズが未知の場合は空配列を返す", () => {
    const res = makeApiResponse({ phases: [{ phase: "xxx", model: "sonnet", thinking: false, max_turns: null }] });
    expect(toRows(res)).toHaveLength(0);
  });

  it("未知の model 値は sonnet に倒す", () => {
    const res = makeApiResponse({
      phases: [{ phase: "intake", model: "gpt-4", thinking: false, max_turns: null }],
    });
    const rows = toRows(res);
    expect(rows[0]!.model).toBe("sonnet");
  });
});

describe("toInputs", () => {
  it("UI 行を PUT 入力に変換する", () => {
    const rows: PhaseModelRow[] = [
      { phase: "plan", label: "計画", model: "opus", thinking: true, maxTurns: 20, hint: "hint" },
      { phase: "intake", label: "受付", model: "haiku", thinking: false, maxTurns: 3, hint: "hint2" },
    ];
    const inputs = toInputs(rows);
    expect(inputs).toHaveLength(2);
    expect(inputs[0]).toEqual({ phase: "plan", model: "opus", thinking: true, max_turns: 20 });
    expect(inputs[1]).toEqual({ phase: "intake", model: "haiku", thinking: false, max_turns: 3 });
  });

  it("空配列は空配列を返す", () => {
    expect(toInputs([])).toEqual([]);
  });
});

describe("toRows → toInputs ラウンドトリップ", () => {
  it("変換後に再変換すると元の値が保持される", () => {
    const api = makeApiResponse();
    const rows = toRows(api);
    const inputs = toInputs(rows);
    // plan の max_turns=20 は保持される
    const plan = inputs.find((i) => i.phase === "plan")!;
    expect(plan.max_turns).toBe(20);
    // intake の max_turns は defaultMaxTurns (3) になる
    const intake = inputs.find((i) => i.phase === "intake")!;
    expect(intake.max_turns).toBe(PHASE_META.intake!.defaultMaxTurns);
  });
});
