interface ComingSoonProps {
  title?: string;
  note?: string;
}

/**
 * 実 API がまだ提供しないデータの「準備中 / 未接続」プレースホルダ (#86)。
 * queue (#96)・knowledge (stub)・日次コスト・レイテンシ履歴など、現行の
 * 読み取り API に存在しない領域で使う。
 */
export function ComingSoon({ title = "準備中", note }: ComingSoonProps) {
  return (
    <div
      className="grid place-items-center rounded-xl border border-dashed px-6 py-10 text-center"
      style={{ borderColor: "var(--color-line-2)" }}
    >
      <div>
        <div className="font-mono text-[11px] uppercase tracking-wide" style={{ color: "var(--color-ink-faint)" }}>
          coming soon
        </div>
        <div className="mt-1.5 text-[13px] font-semibold" style={{ color: "var(--color-ink-dim)" }}>
          {title}
        </div>
        {note && (
          <p className="mt-1 text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            {note}
          </p>
        )}
      </div>
    </div>
  );
}
