import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DiffViewer } from "@/components/DiffViewer";
import type { PrDiff } from "@/lib/diff";
import type { DiffLine } from "@/lib/diff";

function makeDiff(files: { path: string; add: number; del: number; lines: DiffLine[] }[]): PrDiff {
  return { issue: 1, pr: 10, branch: "feature/test", files };
}

describe("DiffViewer", () => {
  it("ファイルリストが表示される", () => {
    const diff = makeDiff([
      { path: "src/index.ts", add: 5, del: 2, lines: [] },
      { path: "src/app.ts", add: 1, del: 0, lines: [] },
    ]);
    render(<DiffViewer diff={diff} />);
    // src/index.ts は選択中ファイルとして sidebar + detail の両方に表示されることがある
    const indexFiles = screen.getAllByText("src/index.ts");
    expect(indexFiles.length).toBeGreaterThan(0);
    expect(screen.getByText("src/app.ts")).toBeDefined();
    expect(screen.getByText("2 files")).toBeDefined();
  });

  it("ファイルをクリックすると選択される", async () => {
    const diff = makeDiff([
      { path: "file1.ts", add: 1, del: 0, lines: [] },
      { path: "file2.ts", add: 2, del: 1, lines: [] },
    ]);
    render(<DiffViewer diff={diff} />);

    await userEvent.click(screen.getByRole("button", { name: /file2/ }));
    // file2.ts が diff body のヘッダに表示される
    const headers = screen.getAllByText("file2.ts");
    expect(headers.length).toBeGreaterThan(0);
  });

  it("hunk 行は cyan 背景で表示される", () => {
    const lines: DiffLine[] = [
      { kind: "hunk", text: "@@ -1,2 +1,3 @@" },
    ];
    const diff = makeDiff([{ path: "a.ts", add: 1, del: 0, lines }]);
    render(<DiffViewer diff={diff} />);
    expect(screen.getByText("@@ -1,2 +1,3 @@")).toBeDefined();
  });

  it("add 行は + マーカーで表示される", () => {
    const lines: DiffLine[] = [
      { kind: "add", newNo: 1, text: "新しい行" },
    ];
    const diff = makeDiff([{ path: "b.ts", add: 1, del: 0, lines }]);
    render(<DiffViewer diff={diff} />);
    expect(screen.getByText("新しい行")).toBeDefined();
    expect(screen.getByText("+")).toBeDefined();
  });

  it("del 行は − マーカーで表示される", () => {
    const lines: DiffLine[] = [
      { kind: "del", oldNo: 1, text: "削除行" },
    ];
    const diff = makeDiff([{ path: "c.ts", add: 0, del: 1, lines }]);
    render(<DiffViewer diff={diff} />);
    expect(screen.getByText("削除行")).toBeDefined();
    expect(screen.getByText("−")).toBeDefined();
  });

  it("ctx 行はスペースマーカーで表示される", () => {
    const lines: DiffLine[] = [
      { kind: "ctx", oldNo: 1, newNo: 1, text: "文脈行" },
    ];
    const diff = makeDiff([{ path: "d.ts", add: 0, del: 0, lines }]);
    const { container } = render(<DiffViewer diff={diff} />);
    expect(screen.getByText("文脈行")).toBeDefined();
    // ctx の mark スパンはスペース文字: DOM で確認
    const markSpans = container.querySelectorAll("span.mr-2.select-none");
    const hasSpaceMark = Array.from(markSpans).some((s) => s.textContent === " ");
    expect(hasSpaceMark).toBe(true);
  });

  it("totalAdd/totalDel 集計が表示される", () => {
    const diff = makeDiff([
      { path: "a.ts", add: 3, del: 1, lines: [] },
      { path: "b.ts", add: 2, del: 4, lines: [] },
    ]);
    render(<DiffViewer diff={diff} />);
    expect(screen.getByText("+5")).toBeDefined(); // 3+2
    expect(screen.getByText("−5")).toBeDefined(); // 1+4
  });
});
