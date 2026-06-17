import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Prototype } from "@/lib/api";

vi.mock("@/components/Portal", () => ({
  Portal: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, sendPrototypeFeedback: vi.fn().mockResolvedValue(true) },
  };
});

import { api } from "@/lib/api";
import { PrototypeGallery } from "@/components/review/PrototypeGallery";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.sendPrototypeFeedback).mockResolvedValue(true);
});
afterEach(() => {
  vi.restoreAllMocks();
});

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

  // ── #145 Phase2: 修正依頼の反復ループ ──
  it("issue 未指定なら修正依頼フォームを出さない", () => {
    render(<PrototypeGallery items={[proto()]} notes={[]} />);
    expect(screen.queryByText("このUIを修正依頼")).toBeNull();
  });

  it("iteration が 2 以上なら更新済みバッジを出す (#145 Phase2)", () => {
    render(<PrototypeGallery items={[proto()]} notes={[]} issue={145} iteration={2} />);
    expect(screen.getByText(/更新済み（2 回目）/)).toBeDefined();
  });

  it("iteration が 1 のときはバッジを出さない", () => {
    render(<PrototypeGallery items={[proto()]} notes={[]} issue={145} iteration={1} />);
    expect(screen.queryByText(/更新済み/)).toBeNull();
  });

  it("修正依頼を送信すると sendPrototypeFeedback を呼ぶ (#145 Phase2)", async () => {
    render(<PrototypeGallery items={[proto()]} notes={[]} issue={145} repo="o/r" />);
    const textarea = screen.getByPlaceholderText(/直してほしい点/);
    await userEvent.type(textarea, "色を変えて");
    await userEvent.click(screen.getByRole("button", { name: "修正を依頼" }));

    await waitFor(() => expect(api.sendPrototypeFeedback).toHaveBeenCalled());
    expect(vi.mocked(api.sendPrototypeFeedback).mock.calls[0][0]).toBe(145);
    expect(vi.mocked(api.sendPrototypeFeedback).mock.calls[0][1]).toBe("色を変えて");
    // actor は repo owner 由来 (o/r → o)
    expect(vi.mocked(api.sendPrototypeFeedback).mock.calls[0][2]).toBe("o");
    expect(await screen.findByText(/修正依頼を送信しました/)).toBeDefined();
  });

  it("空入力では送信ボタンが無効", () => {
    render(<PrototypeGallery items={[proto()]} notes={[]} issue={145} repo="o/r" />);
    expect(screen.getByRole("button", { name: "修正を依頼" })).toHaveProperty("disabled", true);
  });

  it("送信失敗でエラーメッセージを出す", async () => {
    vi.mocked(api.sendPrototypeFeedback).mockRejectedValue(new Error("fail"));
    render(<PrototypeGallery items={[proto()]} notes={[]} issue={145} repo="o/r" />);
    await userEvent.type(screen.getByPlaceholderText(/直してほしい点/), "x");
    await userEvent.click(screen.getByRole("button", { name: "修正を依頼" }));
    await waitFor(() => expect(screen.getByText(/送信に失敗しました/)).toBeDefined());
  });
});
