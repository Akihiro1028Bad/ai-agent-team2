import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ComingSoon } from "@/components/ComingSoon";

describe("ComingSoon", () => {
  it("デフォルト title '準備中' が描画される", () => {
    render(<ComingSoon />);
    expect(screen.getByText("準備中")).toBeDefined();
  });

  it("title prop が描画される", () => {
    render(<ComingSoon title="開発中" />);
    expect(screen.getByText("開発中")).toBeDefined();
  });

  it("note prop が描画される", () => {
    render(<ComingSoon note="近日公開予定" />);
    expect(screen.getByText("近日公開予定")).toBeDefined();
  });

  it("note が未指定のとき note テキストは描画されない", () => {
    render(<ComingSoon title="テスト" />);
    expect(screen.queryByText("近日公開予定")).toBeNull();
  });
});
