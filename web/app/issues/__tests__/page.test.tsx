import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import type { IssueDetail, IssueEvent } from "@/lib/types";

// next/navigation
vi.mock("next/navigation", () => ({
  useParams: vi.fn().mockReturnValue({ id: "42" }),
}));

// next/link
vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

// Stub heavy components
vi.mock("@/components/LogViewer", () => ({
  LogViewer: ({ issueNumber }: { issueNumber: number }) => (
    <div data-testid={`log-viewer-${issueNumber}`} />
  ),
}));

vi.mock("@/components/IssueControls", () => ({
  IssueControls: () => <div data-testid="issue-controls" />,
}));

vi.mock("@/components/ConnectionBanner", async () => {
  const actual = await vi.importActual<typeof import("@/components/ConnectionBanner")>("@/components/ConnectionBanner");
  return actual;
});

vi.mock("@/lib/hooks", () => ({
  usePolling: vi.fn(),
}));

// api モック
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      postReply: vi.fn().mockResolvedValue(undefined),
    },
  };
});

import { usePolling } from "@/lib/hooks";
import { useParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import IssueDetailPage from "@/app/issues/[id]/page";

function makeIssue(overrides: Partial<IssueDetail> = {}): IssueDetail {
  return {
    number: 42,
    repo: "owner/repo",
    title: "テスト Issue",
    type: "feature-m",
    phase: "implement",
    status: "running",
    costUsd: 1.5,
    updated: "2分前",
    body: "",
    events: [],
    ...overrides,
  };
}

function makeEvent(id: string, kind: IssueEvent["kind"] = "phase"): IssueEvent {
  return { id, at: "1分前", kind, title: `イベント ${id}`, detail: undefined };
}

beforeEach(() => {
  vi.mocked(usePolling).mockReturnValue({ data: undefined, error: undefined, loading: true });
  vi.mocked(useParams).mockReturnValue({ id: "42" });
  vi.mocked(api.postReply).mockResolvedValue(undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("IssueDetailPage", () => {
  it("loading=true かつ issue=undefined → 読み込み中を表示", () => {
    vi.mocked(usePolling).mockReturnValue({ data: undefined, error: undefined, loading: true });
    render(<IssueDetailPage />);
    expect(screen.getByText("読み込み中…")).toBeDefined();
  });

  it("status=404 → 'Issue が見つかりません' を表示", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: undefined,
      error: new ApiError(404, "Not Found"),
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText("Issue が見つかりません")).toBeDefined());
  });

  it("issue=undefined かつ loading=false → 'Issue が見つかりません' を表示", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: undefined,
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText("Issue が見つかりません")).toBeDefined());
  });

  it("issue がある場合、タイトルとリポジトリ情報を表示する", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({ title: "テスト Issue タイトル" }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText("テスト Issue タイトル")).toBeDefined());
    expect(screen.getByText(/owner\/repo#42/)).toBeDefined();
  });

  it("prNumber がある場合は PR リンクが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({ prNumber: 100 }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText(/PR #100 の差分を見る/)).toBeDefined());
  });

  it("designPrNumber がある場合は設計レビューリンクが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({ designPrNumber: 50 }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText(/設計レビューを開く/)).toBeDefined());
  });

  it("needsHuman がある場合は承認画面へのリンクが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({ needsHuman: "承認・回答待ち" }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText("承認画面へ")).toBeDefined());
  });

  it("error イベントがある場合は ErrorPanel が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({
        events: [makeEvent("e1", "error")],
      }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText("エラー詳細")).toBeDefined());
  });

  it("events があるとタイムラインが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({
        events: [{ id: "e1", at: "1分前", kind: "phase", title: "受付完了", detail: "詳細テキスト" }],
      }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText("受付完了")).toBeDefined());
    expect(screen.getByText("詳細テキスト")).toBeDefined();
  });

  it("events が空のとき 'イベントはまだありません' を表示", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({ events: [] }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText("イベントはまだありません。")).toBeDefined());
  });

  it("subtasks がある場合はサブタスクリストが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({
        subtasks: [
          { id: 1, title: "サブタスク1", done: false },
          { id: 2, title: "サブタスク2", done: true },
        ],
      }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("サブタスク1")).toBeDefined();
      expect(screen.getByText("サブタスク2")).toBeDefined();
    });
  });

  it("phase=clarify かつ status=waiting のとき回答ボックスが表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({ phase: "clarify", status: "waiting" }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByText("エージェントが回答を待っています")).toBeDefined());
  });

  it("回答を送信すると postReply が呼ばれ成功メッセージが出る", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
      vi.mocked(usePolling).mockReturnValue({
        data: makeIssue({ phase: "clarify", status: "waiting" }),
        error: undefined,
        loading: false,
      });
      render(<IssueDetailPage />);

      await waitFor(() => expect(screen.getByText("エージェントが回答を待っています")).toBeDefined());

      const textarea = screen.getByPlaceholderText(/回答を入力/);
      await user.type(textarea, "これが回答です");
      await user.click(screen.getByRole("button", { name: /回答を送信/ }));

      await waitFor(() => {
        expect(api.postReply).toHaveBeenCalledWith(42, "これが回答です");
      });

      await waitFor(() => {
        expect(screen.getByText(/回答を送信しました/)).toBeDefined();
      });

      await act(async () => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.queryByText(/回答を送信しました/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("回答送信が失敗するとエラーメッセージが出る", async () => {
    vi.mocked(api.postReply).mockRejectedValue(new Error("fail"));
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({ phase: "clarify", status: "waiting" }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);

    await waitFor(() => expect(screen.getByText("エージェントが回答を待っています")).toBeDefined());

    const textarea = screen.getByPlaceholderText(/回答を入力/);
    await userEvent.type(textarea, "回答");
    await userEvent.click(screen.getByRole("button", { name: /回答を送信/ }));

    await waitFor(() => {
      expect(screen.getByText(/送信に失敗しました/)).toBeDefined();
    });
  });

  it("LogViewer に issueNumber が渡される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({ number: 42 }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByTestId("log-viewer-42")).toBeDefined());
  });

  it("API エラー時に ConnectionBanner が表示される", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: undefined,
      error: new ApiError(0, "接続不可"),
      loading: true,
    });
    render(<IssueDetailPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
  });

  it("回答ボックスで空文字の送信はボタンが disabled", async () => {
    vi.mocked(usePolling).mockReturnValue({
      data: makeIssue({ phase: "clarify", status: "waiting" }),
      error: undefined,
      loading: false,
    });
    render(<IssueDetailPage />);

    await waitFor(() => expect(screen.getByText("エージェントが回答を待っています")).toBeDefined());

    const submitBtn = screen.getByRole("button", { name: /回答を送信/ });
    expect(submitBtn).toHaveAttribute("disabled");
  });
});
