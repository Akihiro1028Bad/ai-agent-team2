import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { ApiError } from "@/lib/api";

describe("ConnectionBanner", () => {
  it("error が無ければ何も描画しない", () => {
    const { container } = render(<ConnectionBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("status 0 (到達不可) は停止中の文言を出す", () => {
    render(<ConnectionBanner error={new ApiError(0, "x")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("接続できません");
  });

  it("その他のエラーは status を含む文言を出す", () => {
    render(<ConnectionBanner error={new ApiError(502, "x")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("API エラー (502)");
  });
});
