import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorPanel } from "@/components/ErrorPanel";
import type { IssueEvent } from "@/lib/types";

function makeErrorEvent(overrides: Partial<IssueEvent> = {}): IssueEvent {
  return {
    id: "e1",
    at: "1分前",
    kind: "error",
    title: "エラータイトル",
    detail: undefined,
    ...overrides,
  };
}

describe("ErrorPanel", () => {
  it("events が空のとき ComingSoon を表示する", () => {
    render(<ErrorPanel events={[]} />);
    expect(screen.getByText("coming soon")).toBeDefined();
  });

  it("events があるとき各イベントのタイトルと時刻を表示する", () => {
    const events = [
      makeErrorEvent({ id: "e1", title: "エラー1", at: "2分前" }),
      makeErrorEvent({ id: "e2", title: "エラー2", at: "5分前" }),
    ];
    render(<ErrorPanel events={events} />);
    expect(screen.getByText("エラー1")).toBeDefined();
    expect(screen.getByText("エラー2")).toBeDefined();
    expect(screen.getByText("2分前")).toBeDefined();
  });

  it("detail がある場合は detail テキストを表示する", () => {
    const events = [makeErrorEvent({ detail: "詳細情報" })];
    render(<ErrorPanel events={events} />);
    expect(screen.getByText("詳細情報")).toBeDefined();
  });

  it("detail が null の場合は detail テキストを表示しない", () => {
    const events = [makeErrorEvent({ detail: undefined })];
    render(<ErrorPanel events={events} />);
    expect(screen.queryByText("詳細情報")).toBeNull();
  });

  it("フッターの説明テキストが表示される", () => {
    const events = [makeErrorEvent()];
    render(<ErrorPanel events={events} />);
    expect(screen.getByText(/CI ログ・原因分析/)).toBeDefined();
  });
});
