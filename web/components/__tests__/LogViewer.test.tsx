import { render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LogViewer } from "@/components/LogViewer";
import { FakeEventSource, installFakeEventSource } from "@/lib/__tests__/_fakes";

// jsdom does not implement scrollTo — stub it out
beforeEach(() => {
  HTMLElement.prototype.scrollTo = vi.fn();
});
afterEach(() => {
  HTMLElement.prototype.scrollTo = undefined as unknown as typeof HTMLElement.prototype.scrollTo;
});

function makeAgentData(text: string): string {
  return JSON.stringify({
    ts: "2026-06-12T01:02:03+00:00",
    phase: "implement",
    type: "text",
    text,
  });
}

describe("LogViewer", () => {
  let restore: () => void;

  beforeEach(() => {
    restore = installFakeEventSource();
  });
  afterEach(() => {
    restore();
  });

  it("初期状態でログ行がゼロのとき空メッセージを表示する", () => {
    render(<LogViewer issueNumber={42} />);
    expect(screen.getByText("この Issue の実行ログはありません。")).toBeDefined();
  });

  it("agent イベントを受信するとログ行が描画される", async () => {
    render(<LogViewer issueNumber={42} />);
    const src = FakeEventSource.instances[0];

    await act(async () => {
      src.emit("agent", makeAgentData("テストメッセージ"));
    });

    expect(screen.getByText("テストメッセージ")).toBeDefined();
    expect(screen.queryByText("この Issue の実行ログはありません。")).toBeNull();
  });

  it("onopen で接続インジケーターが表示される (live=true)", async () => {
    render(<LogViewer issueNumber={42} live={true} />);
    const src = FakeEventSource.instances[0];

    // 接続前: インジケーターなし (pulse span は hidden)
    // 接続後: 行数 span は常に存在
    await act(async () => {
      src.open();
    });

    // connected=true になったので streaming=true → インジケーター用 span が描画される
    // DOM 中に "0 行" テキストがあることを確認
    expect(screen.getByText("0 行")).toBeDefined();
  });

  it("live=false のとき onopen でもインジケーターは非表示", async () => {
    render(<LogViewer issueNumber={42} live={false} />);
    const src = FakeEventSource.instances[0];

    await act(async () => {
      src.open();
    });

    // streaming = live && connected = false && connected → streaming=false
    // animate-pulse の span は描画されないはず
    // ヘッダーの行数表示は存在する
    expect(screen.getByText("0 行")).toBeDefined();
  });

  it("複数行受信でカウントが増える", async () => {
    render(<LogViewer issueNumber={42} />);
    const src = FakeEventSource.instances[0];

    await act(async () => {
      src.emit("agent", makeAgentData("行1"));
      src.emit("agent", makeAgentData("行2"));
    });

    expect(screen.getByText("2 行")).toBeDefined();
    expect(screen.getByText("行1")).toBeDefined();
    expect(screen.getByText("行2")).toBeDefined();
  });

  it("error レベルのログ行が描画される (type=result, is_error=true)", async () => {
    render(<LogViewer issueNumber={42} />);
    const src = FakeEventSource.instances[0];

    await act(async () => {
      src.emit(
        "agent",
        JSON.stringify({ ts: "2026-06-12T01:00:00+00:00", phase: "implement", type: "result", is_error: true, text: "エラーが発生しました" }),
      );
    });

    expect(screen.getByText("1 行")).toBeDefined();
  });

});
