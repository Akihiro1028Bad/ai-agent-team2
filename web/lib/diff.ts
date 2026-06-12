// PR 差分ビューア用モック（#129 → PR #130）

export type DiffLineKind = "add" | "del" | "ctx" | "hunk";

export interface DiffLine {
  kind: DiffLineKind;
  oldNo?: number;
  newNo?: number;
  text: string;
}

export interface DiffFile {
  path: string;
  add: number;
  del: number;
  lines: DiffLine[];
}

export interface PrDiff {
  issue: number;
  pr: number;
  branch: string;
  files: DiffFile[];
}

const routeTs: DiffLine[] = [
  { kind: "hunk", text: "@@ -0,0 +1,38 @@ app/api/users/[id]/profile/route.ts" },
  { kind: "add", newNo: 1, text: 'import { NextResponse } from "next/server";' },
  { kind: "add", newNo: 2, text: 'import { profileStore } from "@/lib/mock-store";' },
  { kind: "add", newNo: 3, text: "" },
  { kind: "add", newNo: 4, text: 'const EDITABLE = ["name", "bio", "location", "website"] as const;' },
  { kind: "add", newNo: 5, text: "" },
  { kind: "add", newNo: 6, text: "export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {" },
  { kind: "add", newNo: 7, text: "  const { id } = await params;" },
  { kind: "add", newNo: 8, text: "  const profile = profileStore.get(id);" },
  { kind: "add", newNo: 9, text: '  if (!profile) return NextResponse.json({ error: "not found" }, { status: 404 });' },
  { kind: "add", newNo: 10, text: "  return NextResponse.json(profile);" },
  { kind: "add", newNo: 11, text: "}" },
  { kind: "add", newNo: 12, text: "" },
  { kind: "add", newNo: 13, text: "export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {" },
  { kind: "add", newNo: 14, text: "  const { id } = await params;" },
  { kind: "add", newNo: 15, text: "  const body = await req.json();" },
  { kind: "add", newNo: 16, text: "  const invalid = validateProfile(body);" },
  { kind: "add", newNo: 17, text: "  if (invalid) return NextResponse.json({ error: invalid }, { status: 400 });" },
  { kind: "add", newNo: 18, text: "  const next = profileStore.update(id, pick(body, EDITABLE));" },
  { kind: "add", newNo: 19, text: "  return NextResponse.json(next);" },
  { kind: "add", newNo: 20, text: "}" },
];

const headerTsx: DiffLine[] = [
  { kind: "hunk", text: "@@ -12,6 +12,7 @@ components/Header.tsx" },
  { kind: "ctx", oldNo: 12, newNo: 12, text: '      <nav className="nav">' },
  { kind: "ctx", oldNo: 13, newNo: 13, text: '        <NavLink href="/">Home</NavLink>' },
  { kind: "del", oldNo: 14, text: '        <NavLink href="/settings">Settings</NavLink>' },
  { kind: "add", newNo: 14, text: '        <NavLink href="/profile">Profile</NavLink>' },
  { kind: "add", newNo: 15, text: '        <NavLink href="/settings">Settings</NavLink>' },
  { kind: "ctx", oldNo: 15, newNo: 16, text: "      </nav>" },
];

const pageTsx: DiffLine[] = [
  { kind: "hunk", text: "@@ -1,61 +1,24 @@ app/profile/page.tsx" },
  { kind: "del", oldNo: 1, text: '"use client";' },
  { kind: "del", oldNo: 2, text: "" },
  { kind: "del", oldNo: 3, text: 'import { useState, useEffect } from "react";' },
  { kind: "add", newNo: 1, text: 'import { ProfileClient } from "./ProfileClient";' },
  { kind: "add", newNo: 2, text: 'import { resolveUserId } from "@/lib/auth";' },
  { kind: "ctx", oldNo: 4, newNo: 3, text: "" },
  { kind: "del", oldNo: 5, text: "export default function ProfilePage() {" },
  { kind: "del", oldNo: 6, text: "  const [profile, setProfile] = useState(null);" },
  { kind: "del", oldNo: 7, text: "  // TODO: fetch profile" },
  { kind: "add", newNo: 4, text: "export default async function ProfilePage() {" },
  { kind: "add", newNo: 5, text: "  const userId = await resolveUserId(); // TODO: 認証連携（今回スコープ外）" },
  { kind: "add", newNo: 6, text: "  return <ProfileClient userId={userId} />;" },
  { kind: "ctx", oldNo: 8, newNo: 7, text: "}" },
];

export const prDiffs: Record<number, PrDiff> = {
  129: {
    issue: 129,
    pr: 130,
    branch: "feature/issue-129",
    files: [
      { path: "app/api/users/[id]/profile/route.ts", add: 38, del: 0, lines: routeTs },
      { path: "app/api/users/[id]/profile/route.test.ts", add: 96, del: 0, lines: [{ kind: "hunk", text: "@@ -0,0 +1,96 @@ （テスト 8 ケース）" }] },
      { path: "components/Header.tsx", add: 2, del: 1, lines: headerTsx },
      { path: "app/profile/page.tsx", add: 24, del: 61, lines: pageTsx },
      { path: "app/profile/ProfileClient.tsx", add: 118, del: 0, lines: [{ kind: "hunk", text: "@@ -0,0 +1,118 @@ （新規 Client Component）" }] },
    ],
  },
};

export function getPrDiff(n: number): PrDiff | null {
  return prDiffs[n] ?? null;
}

// 設計書 v1 → v2 の差分（差し戻し後の再設計）
export interface DesignRevisionChange {
  kind: "add" | "del" | "mod";
  section: string;
  text: string;
}

export interface DesignRevision {
  issue: number;
  version: number;
  reason: string; // 差し戻しの指摘
  changes: DesignRevisionChange[];
}

export const designRevisions: Record<number, DesignRevision> = {
  129: {
    issue: 129,
    version: 2,
    reason: "指摘: 「PATCH のバリデーションをフロントにも持たせると二重管理になる。スキーマを共有してほしい」",
    changes: [
      { kind: "add", section: "アーキテクチャ", text: "lib/schemas/profile.ts に zod スキーマを新設し、Route Handler と ProfileClient で共有" },
      { kind: "mod", section: "subtask-1", text: "Route Handler のバリデーションを手書き → zod スキーマ参照に変更" },
      { kind: "add", section: "テスト", text: "TC-09: スキーマ共有（フロント/バックで同一エラーメッセージ）を追加" },
      { kind: "del", section: "subtask-3", text: "ProfileClient 内の独自バリデーション関数を削除" },
    ],
  },
};

export function getDesignRevision(n: number): DesignRevision | null {
  return designRevisions[n] ?? null;
}
