"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";

// クライアントマウント検出 (SSR では false、ハイドレーション後 true)。
// effect 内 setState を避けるため useSyncExternalStore を使う。
const subscribe = () => () => {};
const getClientSnapshot = () => true;
const getServerSnapshot = () => false;

/**
 * body 直下へポータルする。
 * .rise の transform や header の backdrop-filter が fixed 要素の
 * containing block になってしまう問題を回避するため、
 * オーバーレイ（モーダル・トースト）は必ずこれを経由する。
 */
export function Portal({ children }: { children: ReactNode }) {
  const mounted = useSyncExternalStore(subscribe, getClientSnapshot, getServerSnapshot);
  if (!mounted) return null;
  return createPortal(children, document.body);
}
