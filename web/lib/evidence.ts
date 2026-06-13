// レビュー用エビデンス（スクリーンショット・動作録画・テスト結果）の型 (#91)。
//
// backend (GET /api/issues/{n}/evidence) が返す manifest を UI 型へ写したもの。
// 各 item の url はファイル配信エンドポイント (/api/issues/{n}/evidence/{file}) への
// 相対パスで、screenshot/video はそのまま <img>/<video> の src に、terminal は
// テキストを fetch して表示する。

export type EvidenceKind = "screenshot" | "video" | "terminal";

export interface Evidence {
  id: string;
  kind: EvidenceKind;
  title: string;
  /** ファイル配信 URL（相対パス）。screenshot=png / video=webm / terminal=txt */
  url: string;
  /** screenshot のビューポート（mobile=390px） */
  viewport?: "desktop" | "mobile";
  /** 生成時刻 (ISO8601)。未設定なら undefined */
  createdAt?: string;
}

/** GET /api/issues/{n}/evidence のビュー表現。 */
export interface EvidenceView {
  /** manifest の生成時刻 (ISO8601)。未生成なら null */
  generatedAt: string | null;
  items: Evidence[];
  /** スキップ理由・フォールバック注記（items が空のとき UI に表示） */
  notes: string[];
}
