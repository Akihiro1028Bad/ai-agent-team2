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
      include: ["lib/**/*.{ts,tsx}", "components/**/*.tsx", "app/**/*.tsx"],
      exclude: ["**/*.test.{ts,tsx}", "**/__tests__/**", "lib/mock.ts"],
    },
  },
});
