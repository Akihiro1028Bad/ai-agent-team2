import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// 各テスト後に jsdom の DOM を破棄し、テスト間の状態リークを防ぐ。
afterEach(() => {
  cleanup();
});
