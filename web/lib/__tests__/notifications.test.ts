import { describe, expect, it } from "vitest";
import { addReadIds } from "@/lib/notifications";

describe("addReadIds", () => {
  it("空の current に ids を追加する", () => {
    const result = addReadIds(new Set(), ["a", "b"]);
    expect([...result]).toEqual(["a", "b"]);
  });

  it("current に ids を加算的にマージする", () => {
    const current = new Set(["a"]);
    const result = addReadIds(current, ["b", "c"]);
    expect([...result]).toEqual(["a", "b", "c"]);
  });

  it("重複した id は Set 化で除去される", () => {
    const current = new Set(["a", "b"]);
    const result = addReadIds(current, ["b", "c"]);
    // "b" は重複するが Set なので 1 件
    expect([...result]).toEqual(["a", "b", "c"]);
    expect(result.size).toBe(3);
  });

  it("cap 超過時は末尾 cap 件を保持（新しい id を優先）", () => {
    const current = new Set(["old1", "old2", "old3"]);
    const result = addReadIds(current, ["new1", "new2"], 4);
    // merged = ["old1","old2","old3","new1","new2"] → 末尾 4 件
    expect([...result]).toEqual(["old2", "old3", "new1", "new2"]);
    expect(result.size).toBe(4);
  });

  it("最終 Set サイズが cap 以下であることを保証する", () => {
    const current = new Set(Array.from({ length: 150 }, (_, i) => `id-${i}`));
    const ids = Array.from({ length: 100 }, (_, i) => `new-${i}`);
    const result = addReadIds(current, ids, 200);
    expect(result.size).toBeLessThanOrEqual(200);
  });

  it("ちょうど cap 件のとき全件保持する", () => {
    const current = new Set(["a", "b"]);
    const result = addReadIds(current, ["c"], 3);
    expect(result.size).toBe(3);
    expect([...result]).toEqual(["a", "b", "c"]);
  });

  it("ids が空のとき current をそのまま返す", () => {
    const current = new Set(["a", "b"]);
    const result = addReadIds(current, []);
    expect([...result]).toEqual(["a", "b"]);
  });

  it("cap=1 のとき最後の 1 件だけ保持する", () => {
    const current = new Set(["a"]);
    const result = addReadIds(current, ["b"], 1);
    expect([...result]).toEqual(["b"]);
  });
});
