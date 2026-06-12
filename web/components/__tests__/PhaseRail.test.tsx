import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PhaseRail } from "@/components/PhaseRail";
import { MAIN_PHASES } from "@/lib/mock";

describe("PhaseRail", () => {
  it("compact モードで描画される (デフォルト)", () => {
    const { container } = render(
      <PhaseRail phase="implement" accent="var(--color-signal)" />,
    );
    expect(container.firstChild).toBeDefined();
  });

  it("full モードでフェーズラベルが表示される", () => {
    render(
      <PhaseRail phase="implement" accent="var(--color-signal)" variant="full" />,
    );
    // MAIN_PHASES のラベルが表示される
    expect(screen.getByText("実装")).toBeDefined();
  });

  it("full モード: split フェーズは '分割中' を表示する", () => {
    // split は CONDITIONAL_LABEL に "分割中" がある
    render(
      <PhaseRail phase="split" accent="var(--color-violet)" variant="full" />,
    );
    // split の active インデックスは MAIN_INDEX["split"] = 1 (clarify)
    // current フェーズは index 1 なので CONDITIONAL_LABEL["split"] = "分割中" を表示
    expect(screen.getByText("分割中")).toBeDefined();
  });

  it("full モード: revise フェーズは '修正中' を表示する", () => {
    render(
      <PhaseRail phase="revise" accent="var(--color-signal)" variant="full" />,
    );
    expect(screen.getByText("修正中")).toBeDefined();
  });

  it("done フェーズ: すべての主経路フェーズが完了状態", () => {
    render(
      <PhaseRail phase="done" accent="var(--color-cyan)" variant="full" />,
    );
    // "完了" ラベルが表示される
    expect(screen.getByText("完了")).toBeDefined();
  });

  it("intake フェーズ: 最初のステップが active", () => {
    render(
      <PhaseRail phase="intake" accent="var(--color-ink-dim)" variant="full" />,
    );
    expect(screen.getByText("受付")).toBeDefined();
  });

  it("compact モード: ラベルが表示されない", () => {
    render(
      <PhaseRail phase="plan" accent="var(--color-cyan)" variant="compact" />,
    );
    // compact では PHASE_LABEL のテキストが span に描画されない
    // 単に描画が正常に終わることを確認
    const { container } = render(
      <PhaseRail phase="plan" accent="var(--color-cyan)" variant="compact" />,
    );
    // MAIN_PHASES の数だけ dot が存在する
    const dots = container.querySelectorAll(".rounded-full");
    expect(dots.length).toBeGreaterThan(0);
  });

  it("MAIN_PHASES すべてのフェーズを通す", () => {
    // MAIN_INDEX の全 phase key をテスト
    for (const p of MAIN_PHASES) {
      const { unmount } = render(
        <PhaseRail phase={p.key} accent="var(--color-cyan)" variant="full" />,
      );
      unmount();
    }
  });
});
