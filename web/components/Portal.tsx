"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * body 直下へポータルする。
 * .rise の transform や header の backdrop-filter が fixed 要素の
 * containing block になってしまう問題を回避するため、
 * オーバーレイ（モーダル・トースト）は必ずこれを経由する。
 */
export function Portal({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;
  return createPortal(children, document.body);
}
