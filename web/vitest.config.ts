import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const alias = {
  "@": fileURLToPath(new URL("./", import.meta.url)),
};

// 2 プロジェクト構成:
//  - node:  lib/ の純粋ロジック (アダプタ / diff パーサ)。DOM 不要・高速。
//  - jsdom: コンポーネント / フックのテスト (.test.tsx)。Testing Library。
export default defineConfig({
  test: {
    projects: [
      {
        resolve: { alias },
        test: {
          name: "node",
          environment: "node",
          include: ["lib/**/*.test.ts"],
        },
      },
      {
        resolve: { alias },
        test: {
          name: "jsdom",
          environment: "jsdom",
          include: ["{components,app,lib}/**/*.test.tsx"],
          setupFiles: ["./vitest.setup.ts"],
        },
      },
    ],
    coverage: {
      provider: "v8",
      // 計測対象は「実 API データ経路の実ロジック」に限定する (#120)。
      // モックのままのページ (costs/health/timeline/settings/knowledge/review/*) や
      // サードパーティ薄ラッパ (Mermaid)・Portal 等は対象外 (#89/#90/#118 で書き換え予定)。
      // ここに挙げたファイルは per-file 100% を CI で強制する。
      include: [
        "lib/api.ts",
        "lib/model-config.ts",
        "lib/hooks.ts",
        "lib/diff-parse.ts",
        "lib/notifications.ts",
        "lib/activity-context.tsx",
        "components/ConnectionBanner.tsx",
        "components/ComingSoon.tsx",
        "components/ErrorPanel.tsx",
        "components/LogViewer.tsx",
        "components/NotificationBell.tsx",
        "components/Shell.tsx",
        "components/PhaseRail.tsx",
        "components/IssueControls.tsx",
        "components/AddIssueButton.tsx",
        "components/CommandPalette.tsx",
        "components/DiffViewer.tsx",
        "app/page.tsx",
        "app/queue/page.tsx",
        "app/approvals/page.tsx",
        "app/issues/[id]/page.tsx",
      ],
      exclude: ["**/*.test.{ts,tsx}", "**/__tests__/**"],
      thresholds: {
        perFile: true,
        statements: 100,
        branches: 100,
        functions: 100,
        lines: 100,
      },
    },
  },
});
