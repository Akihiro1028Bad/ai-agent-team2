import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Prototype } from "@/lib/api";

vi.mock("@/components/Portal", () => ({
  Portal: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import { PrototypeGallery } from "@/components/review/PrototypeGallery";

function proto(overrides: Partial<Prototype> = {}): Prototype {
  return { id: "prototype", title: "UI プロトタイプ", url: "/api/issues/145/prototypes/index.html", ...overrides };
}

describe("PrototypeGallery", () => {
  it("プロトタイプが無いときは note を表示する (#145)", () => {
    render(<PrototypeGallery items={[]} notes={["プロトタイプ HTML が生成されませんでした。"]} />);
    expect(screen.getByText("プロトタイプ HTML が生成されませんでした。")).toBeDefined();
  });

  it("items を sandbox iframe で描画する (#145)", () => {
    render(<PrototypeGallery items={[proto()]} notes={[]} />);
    const frame = screen.getByTitle("UI プロトタイプ") as HTMLIFrameElement;
    expect(frame.tagName).toBe("IFRAME");
    expect(frame.getAttribute("src")).toBe("/api/issues/145/prototypes/index.html");
    // allow-same-origin は付けない（不透明オリジン隔離）
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
  });

  it("新しいタブで開くリンクに noopener を付ける", () => {
    render(<PrototypeGallery items={[proto()]} notes={[]} />);
    const link = screen.getByText("新しいタブで開く").closest("a") as HTMLAnchorElement;
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.getAttribute("target")).toBe("_blank");
  });
});
