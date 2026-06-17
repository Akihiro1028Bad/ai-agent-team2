import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { HearingTurn } from "@/lib/api";
import { HearingThread } from "@/components/review/HearingThread";

const turns: HearingTurn[] = [
  { role: "question", author: "bot", body: "仕様を教えて" },
  { role: "answer", author: "alice", body: "これです" },
];

describe("HearingThread (#139)", () => {
  it("Q&A を質問/回答ラベル付きで表示する", () => {
    render(<HearingThread state="waiting" rounds={1} turns={turns} />);
    expect(screen.getByText("仕様を教えて")).toBeDefined();
    expect(screen.getByText("これです")).toBeDefined();
    expect(screen.getByText("質問")).toBeDefined();
    expect(screen.getByText("回答")).toBeDefined();
    expect(screen.getByText("回答待ち")).toBeDefined();
    expect(screen.getByText("1 ラウンド")).toBeDefined();
  });

  it("turns が空のとき『ヒアリングは行われていません』を出す", () => {
    render(<HearingThread state="none" rounds={0} turns={[]} />);
    expect(screen.getByText(/ヒアリングは行われていません/)).toBeDefined();
  });

  it("検討中の状態ラベルを出す", () => {
    render(<HearingThread state="in_progress" rounds={2} turns={turns} />);
    expect(screen.getByText("エージェント検討中")).toBeDefined();
  });
});
