import { vi } from "vitest";

/**
 * jsdom に存在しない EventSource を差し替えるための最小 Fake。
 *
 * テスト側で `installFakeEventSource()` を呼び、返り値の `instances` から
 * 生成済みインスタンスを取得して `emit()` / `open()` / `fail()` を駆動する。
 * `restore()`（afterEach 等）で元に戻す。
 */
export class FakeEventSource {
  static instances: FakeEventSource[] = [];

  url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  private listeners = new Map<string, ((ev: MessageEvent) => void)[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: (ev: MessageEvent) => void): void {
    const list = this.listeners.get(type) ?? [];
    list.push(fn);
    this.listeners.set(type, list);
  }

  close(): void {
    this.closed = true;
  }

  /** named イベント (例: "agent") を発火する。 */
  emit(type: string, data: string): void {
    for (const fn of this.listeners.get(type) ?? []) {
      fn(new MessageEvent(type, { data }));
    }
  }

  /** 接続確立を模す。 */
  open(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  /** 接続エラーを模す。 */
  fail(): void {
    this.onerror?.();
  }
}

/** globalThis.EventSource を Fake に差し替え、復元関数を返す。 */
export function installFakeEventSource(): () => void {
  FakeEventSource.instances = [];
  const original = (globalThis as { EventSource?: unknown }).EventSource;
  vi.stubGlobal("EventSource", FakeEventSource);
  return () => {
    vi.stubGlobal("EventSource", original);
    FakeEventSource.instances = [];
  };
}
