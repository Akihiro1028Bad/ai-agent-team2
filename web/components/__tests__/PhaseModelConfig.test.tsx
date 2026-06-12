import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError, type ApiPhaseModelsResponse } from "@/lib/api";

// api モジュールをモック
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getPhaseModels: vi.fn(),
      putPhaseModels: vi.fn(),
    },
  };
});

import { api } from "@/lib/api";
import { PhaseModelConfig } from "@/components/PhaseModelConfig";

const MOCK_RESPONSE: ApiPhaseModelsResponse = {
  phases: [
    { phase: "intake", model: "haiku", thinking: false, max_turns: null },
    { phase: "clarify", model: "sonnet", thinking: false, max_turns: null },
    { phase: "plan", model: "opus", thinking: true, max_turns: 20 },
    { phase: "split", model: "sonnet", thinking: false, max_turns: null },
    { phase: "implement", model: "sonnet", thinking: false, max_turns: null },
    { phase: "revise", model: "sonnet", thinking: false, max_turns: null },
  ],
  allowed_models: ["haiku", "sonnet", "opus"],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PhaseModelConfig", () => {
  it("初回ロード中は「読み込み中…」を表示する", () => {
    vi.mocked(api.getPhaseModels).mockReturnValue(new Promise(() => {}));
    render(<PhaseModelConfig />);
    expect(screen.getByText("読み込み中…")).toBeDefined();
  });

  it("ロード成功後にフェーズ行を描画する", async () => {
    vi.mocked(api.getPhaseModels).mockResolvedValue(MOCK_RESPONSE);
    render(<PhaseModelConfig />);
    await waitFor(() => {
      expect(screen.getByText("計画")).toBeDefined();
    });
    expect(screen.getByText("受付")).toBeDefined();
    expect(screen.getByText("実装")).toBeDefined();
  });

  it("取得失敗時は ConnectionBanner を表示する", async () => {
    vi.mocked(api.getPhaseModels).mockRejectedValue(new ApiError(0, "接続不可"));
    render(<PhaseModelConfig />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
    });
  });

  it("モデル変更後「保存」押下で putPhaseModels が正しい body で呼ばれる", async () => {
    vi.mocked(api.getPhaseModels).mockResolvedValue(MOCK_RESPONSE);
    vi.mocked(api.putPhaseModels).mockResolvedValue(MOCK_RESPONSE);
    render(<PhaseModelConfig />);
    await waitFor(() => {
      expect(screen.getByText("計画")).toBeDefined();
    });

    // intake 行の Sonnet ボタンをクリック (intake は haiku → sonnet に変更)
    const sonnetButtons = screen.getAllByText("Sonnet 4.6");
    fireEvent.click(sonnetButtons[0]!);

    // 保存ボタンをクリック
    const saveBtn = screen.getByText("保存");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(vi.mocked(api.putPhaseModels)).toHaveBeenCalledOnce();
    });

    const [rows] = vi.mocked(api.putPhaseModels).mock.calls[0]!;
    // intake が sonnet に変わっていることを確認
    const intake = rows.find((r) => r.phase === "intake");
    expect(intake?.model).toBe("sonnet");
  });

  it("保存失敗時にエラー表示し、「保存しました」は出ない", async () => {
    vi.mocked(api.getPhaseModels).mockResolvedValue(MOCK_RESPONSE);
    vi.mocked(api.putPhaseModels).mockRejectedValue(new ApiError(500, "サーバーエラー"));
    render(<PhaseModelConfig />);
    await waitFor(() => {
      expect(screen.getByText("計画")).toBeDefined();
    });

    // 変更を入れて dirty にする
    const sonnetButtons = screen.getAllByText("Sonnet 4.6");
    fireEvent.click(sonnetButtons[0]!);

    const saveBtn = screen.getByText("保存");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText("API エラー (500)")).toBeDefined();
    });
    expect(screen.queryByText("保存しました")).toBeNull();
  });
});
