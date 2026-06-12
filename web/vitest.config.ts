import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// lib/ の純粋ロジック (アダプタ / diff パーサ) の単体テスト用。
// React コンポーネントは対象外 (node 環境)。@ エイリアスは tsconfig と合わせる。
export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
});
