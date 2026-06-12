import type { ApiError } from "@/lib/api";

interface ConnectionBannerProps {
  error?: ApiError | null;
}

/**
 * API への接続不可 / エラーを画面上部に表示するバナー (#86)。
 * orchestrator/API プロセスが停止していても UI がクラッシュせず、
 * 「接続できない」事実を伝える (受け入れ条件)。error が無ければ何も描画しない。
 */
export function ConnectionBanner({ error }: ConnectionBannerProps) {
  if (!error) return null;

  const message = error.isUnreachable
    ? "オーケストレーター API に接続できません（プロセス停止中の可能性）。表示は最後に取得できた内容です。"
    : `API エラー (${error.status})。データを取得できませんでした。`;

  return (
    <div
      role="alert"
      className="mb-4 flex items-center gap-2.5 rounded-xl border px-4 py-2.5 text-[13px]"
      style={{
        borderColor: "var(--color-rose)",
        background: "color-mix(in srgb, var(--color-rose) 12%, transparent)",
        color: "var(--color-rose)",
      }}
    >
      <span
        aria-hidden
        className="block h-2 w-2 shrink-0 rounded-full"
        style={{ background: "var(--color-rose)" }}
      />
      <span>{message}</span>
    </div>
  );
}
