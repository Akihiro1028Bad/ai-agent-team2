# #120 実装仕様: web/ フロントのユニットテスト構築

参照: #86（vitest 導入・純関数テスト）/ #88（操作系 UI）

## スコープ

コンポーネント・フックのテスト基盤を整え、主要 UI ロジックをカバーし、web を CI に乗せる。

- Testing Library 導入 + vitest の jsdom 環境（純関数は node のまま）
- フック（usePolling / useLogStream）とコンポーネントのテスト
- web CI ジョブ追加（vitest / tsc / eslint / next build）
- カバレッジ計測

## 設計判断

### 1. vitest の環境分離（projects）
純関数テスト（`lib/**/*.test.ts`）は DOM 不要で高速な **node 環境**のまま、コンポーネント/フック
テスト（`**/*.test.tsx`）は **jsdom 環境**で動かす。vitest 4 の `test.projects` で 2 プロジェクトに
分割する（`environmentMatchGlobs` は deprecated のため不使用）。

- project "node": environment=node, include=`lib/**/*.test.ts`
- project "jsdom": environment=jsdom, include=`{components,app,lib}/**/*.test.tsx`,
  setupFiles=`vitest.setup.ts`
- `@` エイリアスは両 project で共有

### 2. setup（vitest.setup.ts）
- `@testing-library/jest-dom/vitest` を import（toBeInTheDocument 等のマッチャ）
- `afterEach(cleanup)` で DOM をリセット
- jsdom に無い API（EventSource）はテスト側でスタブ注入する方針（global を汚さない最小限）

### 3. fetch / EventSource モック
- フック（usePolling）は fetcher を引数で受けるため、**fetcher 自体をモック**すればよい
  （global fetch を触らない。api をモックするのは app/page のテスト）
- useLogStream は `new EventSource` を使うため、**FakeEventSource** クラスを
  `lib/__tests__/_fakes.ts`（または test 内）で用意し `globalThis.EventSource` に差し込む
  （afterEach で復元）
- app/page・Shell・NotificationBell は `@/lib/api` を `vi.mock` でスタブ

### 4. 依存追加（devDependencies）
- `@testing-library/react` / `@testing-library/jest-dom` / `@testing-library/user-event` / `jsdom`
- lockfile（package-lock.json）をコミット（CI は `npm ci`）

### 5. web CI（.github/workflows/ci.yml に web ジョブ追加）
```
web:
  runs-on: ubuntu-latest
  defaults: { run: { working-directory: web } }
  steps:
    - checkout
    - setup-node (node 22, cache=npm, cache-dependency-path=web/package-lock.json)
    - npm ci
    - npx vitest run --coverage
    - npx tsc --noEmit
    - npx eslint .
    - npm run build
```

## テスト対象

### フック（lib/hooks.ts）
- `usePolling`: 初回 loading→data / interval 更新 / エラー時に last data 保持・error セット /
  アンマウントで abort（fake timers + AbortController）
- `useLogStream`: EventSource の "agent" 受信で行追加 / issue 変更で lines リセット /
  onopen→connected true・onerror→false / アンマウントで close

### コンポーネント
- `ConnectionBanner`: error 無しは非表示 / status 0 は OFFLINE 文言 / その他は接続不可
- `ComingSoon`: title / note 描画
- `LogViewer`: FakeEventSource で行が流れる・接続インジケータ
- `NotificationBell`: activity から gate/error/done 抽出・未読バッジ・localStorage 既読
- `Shell`: health から RUNNING/STOPPED/OFFLINE・サイドバー概況
- `app/page.tsx`（ダッシュボード）: loading / empty / error / data 各状態（api をモック）

## テスト方針
- ふるまいベース（role/text で取得、実装詳細に依存しない）
- 非同期は `findBy*` / `waitFor`。タイマーは `vi.useFakeTimers()` を必要箇所のみ
- `user-event` でクリック等（必要時）

## 受け入れ条件
- [ ] コンポーネント/フックのテストが CI（web ジョブ）で実行され緑
- [ ] 主要コンポーネント（上記）と両フックをカバー
- [ ] `vitest run --coverage` でカバレッジ計測（lib/components/hooks）
- [ ] 既存の純関数テスト（node project）が引き続き緑

## 非スコープ
- Playwright E2E（別 issue）／フィクスチャ駆動 UI スモークの自動化（手動検証は継続）
- ビジュアルリグレッション
