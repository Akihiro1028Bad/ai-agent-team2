# Issue #115 — 読み取り API のハードニング

> 認証プロファイル / ファイル権限 / read サイズ上限 / rate_limit.reset

#97（PR #114）のセキュリティレビューで挙がった、読み取り API（#84/#85/#97）
横断のハードニング項目を集約する。いずれも **localhost バインド・単一ユーザー
前提**という現行設計に依存しており、#97 固有の退行ではない。

## スコープ分割

| Unit | 項目 | 重要度 | 本セッション |
|------|------|--------|------|
| **C1** | 2. ファイル権限 0o600 / 3. read サイズ上限 / 4. rate_limit.reset 除外 | LOW + 情報量 | ✅ 実装 |
| **C2** | 1. 認証プロファイルの分離 | MEDIUM | ⏸ 方針確定後に別途 |

Unit C1（本書）は判断が明確で手戻りの小さい 3 項目。Unit C2（認証）は
公開/認証プロファイル分離 or localhost 強制の設計判断を要するため分離する。

---

## Unit C1: 実装方針

### 共通基盤: `io_safety.py`（新規）

ローカルファイル I/O のハードニングを 1 モジュールに集約する。

```python
MAX_STATUS_FILE_BYTES = 5 * 1024 * 1024   # health/queue/state（小さい想定）
MAX_LOG_FILE_BYTES    = 64 * 1024 * 1024  # events/agent（追記で増えるため余裕）

class FileTooLargeError(OSError): ...      # OSError 継承 → 既存 except で安全側に倒せる

def atomic_write_text(path, text, *, encoding="utf-8") -> None
    # 親 dir 作成 → tmp に書き込み → chmod 0o600 → replace（rename は perms 継承）

def ensure_private_file(path) -> None
    # 追記ログ用。未作成なら 0o600 で作成（umask 非依存に chmod）

def read_text_capped(path, max_bytes, *, encoding="utf-8") -> str
    # st_size > max_bytes なら FileTooLargeError、それ以外は read_text
```

### 項目 2: 永続化ファイルの権限 0o600

`tmp + replace` 系（**所有者のみ rw**、他ローカルユーザー不可読）に統一:

- `StatePersistence.save` → `atomic_write_text`（state.json）
- `Orchestrator._write_queue_json_sync` → `atomic_write_text`（queue.json）
- `Orchestrator._write_health_json_sync` → `atomic_write_text`（health.json）

追記ログ系（`open("a")`）は初回作成時に `ensure_private_file` で 0o600:

- `EventLogger.log_event`（events.jsonl）
- `AgentLog.write`（agent.jsonl）

### 項目 3: read サイズ上限

全 read 経路で `read_text_capped` を経由し、上限超過は **安全側に倒す**
（`FileTooLargeError` は `OSError` 継承なので既存の except が捕捉）:

| 読み取り | 上限 | 上限超過時 |
|----------|------|-----------|
| `read_health` | STATUS | running=False（専用 reason） |
| `read_queue` | STATUS | running=False（corrupt 相当） |
| `load_states`（`StatePersistence.load`） | STATUS | 空 dict（backup は作らない） |
| `read_agent_logs` | LOG | 空ページ |
| `_iter_event_lines` | LOG | 空リスト |

状態/ヘルス系（health/queue/state）は 5MiB、追記ログ系（events/agent）は
64MiB。ログは正常運用で増えるため上限を分け、巨大ファイルでの OOM のみ防ぐ
（完全なストリーミング読みは将来課題。agent は SSE tail で別途部分読み対応済み）。

### 項目 4: rate_limit.reset 除外

`Orchestrator._collect_rate_limit` の戻りから `reset`（Unix 秒）を除外する。
Web UI は `remaining` / `limit` のみ参照（`web/lib/api.ts`）しており `reset` は
未使用。トークン消費タイミングのフィンガープリント面を減らす。

---

## 判断記録（受け入れ条件）

- **項目 1（認証）**: Unit C2 へ繰り延べ。現状 localhost バインド前提で許容、
  公開/認証プロファイル分離の設計を別途行う。
- **項目 2**: 対応（0o600 を永続化層・追記ログで一貫適用）。
- **項目 3**: 対応（read API 全体に size cap。status=5MiB / log=64MiB）。
- **項目 4**: 対応（`reset` を snapshot から除外）。

## テスト

- `tests/unit/test_io_safety.py`: atomic_write_text/ensure_private_file の
  0o600、read_text_capped の上限判定。
- 既存リーダー/オーケストレータ/永続化テストに oversize → 安全側、
  書き出しファイル 0o600、rate_limit に reset 無しを追加。
