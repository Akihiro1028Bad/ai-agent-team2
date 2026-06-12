// diff-parse.ts の未カバーブランチ: HUNK_RE がマッチしない @@ 行
import { describe, expect, it } from "vitest";
import { parsePatch } from "@/lib/diff-parse";

describe("parsePatch: HUNK_RE マッチなし", () => {
  it("@@ で始まるが正規表現にマッチしない行でも hunk として追加される", () => {
    // HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/
    // "@@ INVALID" は @@ で始まるが数字がないのでマッチしない → m が null
    const patch = "@@ INVALID @@\n+added";
    const lines = parsePatch(patch);
    // hunk 行自体は push される (HUNK_RE にマッチしなくても lines.push は実行される)
    expect(lines[0]).toEqual({ kind: "hunk", text: "@@ INVALID @@" });
    // 次の行は add として処理される (oldNo/newNo は初期値 0 のまま)
    expect(lines[1]).toEqual({ kind: "add", newNo: 0, text: "added" });
  });
});
