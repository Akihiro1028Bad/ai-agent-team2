// GitHub の unified diff (`patch` 文字列) を UI の DiffLine[] へ変換する純関数。
// API (GET /api/issues/{n}/diff) の DiffFile.patch は生の unified diff のため、
// 行種別 (add/del/ctx/hunk) と行番号を復元してビューアが描画できる形にする。

import type { DiffLine } from "@/lib/diff";

const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

/**
 * unified diff の patch 文字列を DiffLine[] にパースする。
 *
 * - `@@ -a,b +c,d @@` … hunk ヘッダ。行番号カウンタを再初期化する。
 * - 先頭 `+` … 追加行 (newNo を採番)。
 * - 先頭 `-` … 削除行 (oldNo を採番)。
 * - 先頭スペース / 空行 … 文脈行 (old/new 両方を採番)。
 * - `\ No newline at end of file` … メタ行のため表示しない。
 *
 * patch が null/空 (バイナリファイル等) の場合は空配列を返す。
 */
export function parsePatch(patch: string | null | undefined): DiffLine[] {
  if (!patch) return [];

  const lines: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;

  for (const raw of patch.split("\n")) {
    if (raw.startsWith("@@")) {
      const m = HUNK_RE.exec(raw);
      if (m) {
        oldNo = Number.parseInt(m[1], 10);
        newNo = Number.parseInt(m[2], 10);
      }
      lines.push({ kind: "hunk", text: raw });
      continue;
    }

    // "\ No newline at end of file" 等のメタ行は表示対象外。
    if (raw.startsWith("\\")) continue;

    const marker = raw[0];
    const text = raw.slice(1);

    if (marker === "+") {
      lines.push({ kind: "add", newNo, text });
      newNo += 1;
    } else if (marker === "-") {
      lines.push({ kind: "del", oldNo, text });
      oldNo += 1;
    } else {
      // 先頭スペースの文脈行、または hunk 末尾の空行。
      lines.push({ kind: "ctx", oldNo, newNo, text });
      oldNo += 1;
      newNo += 1;
    }
  }

  return lines;
}
