import { describe, expect, it } from "vitest";
import { parsePatch } from "@/lib/diff-parse";

describe("parsePatch", () => {
  it("null/空 patch は空配列", () => {
    expect(parsePatch(null)).toEqual([]);
    expect(parsePatch(undefined)).toEqual([]);
    expect(parsePatch("")).toEqual([]);
  });

  it("hunk ヘッダから行番号を初期化し add/del/ctx を採番する", () => {
    const patch = ["@@ -1,3 +1,4 @@", " context", "-removed", "+added1", "+added2", " tail"].join("\n");
    const lines = parsePatch(patch);

    expect(lines[0]).toEqual({ kind: "hunk", text: "@@ -1,3 +1,4 @@" });
    expect(lines[1]).toEqual({ kind: "ctx", oldNo: 1, newNo: 1, text: "context" });
    expect(lines[2]).toEqual({ kind: "del", oldNo: 2, text: "removed" });
    expect(lines[3]).toEqual({ kind: "add", newNo: 2, text: "added1" });
    expect(lines[4]).toEqual({ kind: "add", newNo: 3, text: "added2" });
    expect(lines[5]).toEqual({ kind: "ctx", oldNo: 3, newNo: 4, text: "tail" });
  });

  it("'No newline at end of file' メタ行は表示しない", () => {
    const patch = ["@@ -1,1 +1,1 @@", "-a", "+b", "\\ No newline at end of file"].join("\n");
    const lines = parsePatch(patch);
    expect(lines.some((l) => l.text.includes("No newline"))).toBe(false);
    expect(lines).toHaveLength(3); // hunk + del + add
  });

  it("複数 hunk で行番号がリセットされる", () => {
    const patch = ["@@ -1,1 +1,1 @@", " a", "@@ -10,1 +20,1 @@", " b"].join("\n");
    const lines = parsePatch(patch);
    expect(lines[1]).toMatchObject({ kind: "ctx", oldNo: 1, newNo: 1 });
    expect(lines[3]).toMatchObject({ kind: "ctx", oldNo: 10, newNo: 20 });
  });
});
