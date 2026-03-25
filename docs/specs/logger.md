# 実装仕様書: EventLogger

## 概要

構造化イベントログの記録クラス。`Tracker` Protocol を実装し、Issue単位の `events.jsonl` ファイルにイベントを追記する。センシティブ情報のマスク処理、フェーズログの書き出し機能を持つ。

**モジュール**: `src/ai_agent_orchestrator/event_logger.py`
**テストファイル**: `tests/unit/test_event_logger.py`

> **Note**: 配置パスは `src/ai_agent_orchestrator/event_logger.py`。API Reference の `logger/` 配下パスは旧定義。

---

## 依存パッケージ

```python
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
```

---

## Protocol適合

`ai_agent_orchestrator.protocols.Tracker` Protocol に適合する。

```python
@runtime_checkable
class Tracker(Protocol):
    async def track(
        self,
        event: str,
        *,
        issue_number: int,
        phase: str,
        data: dict | None = None,
    ) -> None: ...
```

---

## クラス定義

```python
class EventLogger:
    """構造化イベントログの記録.

    Issue単位で events.jsonl ファイルにイベントを追記する。
    Tracker Protocol に適合し、プラグインとして差し替え可能。

    ログ出力先:
        {log_dir}/issue-{issue_number}/events.jsonl

    フェーズログ出力先:
        {log_dir}/issue-{issue_number}/{timestamp}_{phase}.log

    Attributes:
        _log_dir: ログの基底ディレクトリ。
        _lock: 並行書き込みを防ぐための asyncio.Lock。
        SENSITIVE_KEYS: マスク対象のキー名パターン。
        TOKEN_PATTERN: トークン文字列にマッチする正規表現。
    """

    SENSITIVE_KEYS: frozenset[str] = frozenset({
        "token", "password", "secret", "authorization", "cookie", "credential",
    })

    TOKEN_PATTERN: re.Pattern = re.compile(
        r"(ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})"
    )

    URL_TOKEN_PATTERN: re.Pattern = re.compile(
        r"([?&])(access_token|token|key|secret|password|credential)=([^&\s]+)"
    )

    def __init__(self, log_dir: Path) -> None:
        """初期化.

        Args:
            log_dir: ログの基底ディレクトリ。存在しない場合は自動作成。
        """
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
```

---

## メソッド仕様

### `async track(event: str, *, issue_number: int, phase: str, data: dict | None = None) -> None`

**説明**: イベントを `events.jsonl` ファイルに1行のJSONとして追記する。`data` が指定された場合、`_sanitize_for_log()` でセンシティブ情報をマスクしてから記録する。

**パラメータ**:

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `event` | `str` | (必須) | イベント名（`phase_start`, `phase_transition`, `tool_use_start`, `tool_use_end`, `question_posted`, `pr_created` 等） |
| `issue_number` | `int` | (必須) | 対象Issue番号 |
| `phase` | `str` | (必須) | 現在のフェーズ名 |
| `data` | `dict \| None` | `None` | イベント固有のデータ |

**戻り値**: `None`

**出力レコード形式**:

```json
{"ts": "2026-03-24T10:00:00+00:00", "issue": 42, "phase": "hearing", "event": "phase_start", "data": {...}}
```

**実装**:

```python
async def track(
    self,
    event: str,
    *,
    issue_number: int,
    phase: str,
    data: dict | None = None,
) -> None:
    """イベントをJSONLファイルに記録."""
    record: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "issue": issue_number,
        "phase": phase,
        "event": event,
    }
    if data:
        record["data"] = self._sanitize_for_log(data)

    events_file = self._log_dir / f"issue-{issue_number}" / "events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(record, ensure_ascii=False) + "\n"

    def _write() -> None:
        with events_file.open("a", encoding="utf-8") as f:
            f.write(line)

    async with self._lock:
        await asyncio.to_thread(_write)
```

**補足**: `asyncio.Lock` により、複数の並行タスクからの同時書き込みを直列化する。

---

### `async write_phase_log(issue_number: int, phase: str, content: str) -> None`

**説明**: フェーズログをファイルに書き出す。ファイル名にタイムスタンプとフェーズ名を含む。内容は `_sanitize_for_log()` を通さず、そのまま保存する（文字列内のトークンパターンのみマスク）。

**パラメータ**:

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `issue_number` | `int` | Issue番号 |
| `phase` | `str` | フェーズ名 |
| `content` | `str` | ログ内容 |

**戻り値**: `None`

**出力先**: `{log_dir}/issue-{issue_number}/{timestamp}_{phase}.log`

**実装**:

```python
async def write_phase_log(
    self,
    issue_number: int,
    phase: str,
    content: str,
) -> None:
    """フェーズログをファイルに書き出す."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    log_file = (
        self._log_dir
        / f"issue-{issue_number}"
        / f"{ts}_{phase}.log"
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # 文字列内のトークンパターンをマスク
    sanitized_content = self.TOKEN_PATTERN.sub("***REDACTED***", content)
    async with self._lock:
        log_file.write_text(sanitized_content, encoding="utf-8")
```

---

### `_sanitize_for_log(data: dict) -> dict`

**説明**: ログ出力前にセンシティブ情報をマスクする内部メソッド。`track()` 内部で自動呼び出しされる。再帰的にネストされた辞書も処理する。

**パラメータ**:

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `data` | `dict` | マスク対象のデータ辞書 |

**戻り値**: `dict` — マスク済みの辞書（元の辞書は変更しない）

**マスクルール**:

1. **キー名マッチ**: キー名（小文字化）が `SENSITIVE_KEYS` のいずれかを含む場合、値を `"***REDACTED***"` に置換
2. **ネスト辞書**: 値が `dict` の場合、再帰的にサニタイズ
3. **文字列値のトークンパターン**: 値が `str` の場合、`TOKEN_PATTERN` にマッチする部分を `"***REDACTED***"` に置換
4. **リスト値**: 値が `list` の場合、各要素に対して同様の処理を適用

**実装**:

```python
def _sanitize_for_log(self, data: dict) -> dict:
    """ログ出力前にセンシティブ情報をマスク."""
    sanitized: dict = {}
    for key, value in data.items():
        if any(s in key.lower() for s in self.SENSITIVE_KEYS):
            sanitized[key] = "***REDACTED***"
        elif isinstance(value, dict):
            sanitized[key] = self._sanitize_for_log(value)
        elif isinstance(value, str):
            masked = self.TOKEN_PATTERN.sub("***REDACTED***", value)
            masked = self.URL_TOKEN_PATTERN.sub(r"\1\2=***REDACTED***", masked)
            sanitized[key] = masked
        elif isinstance(value, list):
            sanitized[key] = [
                self._sanitize_for_log(item) if isinstance(item, dict)
                else (
                    self.URL_TOKEN_PATTERN.sub(
                        r"\1\2=***REDACTED***",
                        self.TOKEN_PATTERN.sub("***REDACTED***", item),
                    )
                    if isinstance(item, str) else item
                )
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized
```

---

## テストケース

テストファイル: `tests/unit/test_event_logger.py`

使用ライブラリ: `pytest`, `pytest-asyncio`, `tmp_path` (pytest組み込み)

### 共通フィクスチャ

```python
import asyncio
import json
import pytest
from pathlib import Path

from ai_agent_orchestrator.event_logger import EventLogger


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def logger(log_dir: Path) -> EventLogger:
    return EventLogger(log_dir)
```

---

### テスト1: イベントがJSONL形式で記録される

```python
@pytest.mark.asyncio
async def test_track_writes_jsonl(logger: EventLogger, log_dir: Path) -> None:
    """track()がevents.jsonlに1行のJSONレコードを書き込むこと."""
    await logger.track(
        "phase_start",
        issue_number=42,
        phase="hearing",
        data={"comment_id": 123},
    )

    events_file = log_dir / "issue-42" / "events.jsonl"
    assert events_file.exists()

    lines = events_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["issue"] == 42
    assert record["phase"] == "hearing"
    assert record["event"] == "phase_start"
    assert record["data"]["comment_id"] == 123
    assert "ts" in record  # タイムスタンプが存在
```

**検証ポイント**: JSONLフォーマット（1行1レコード）、全フィールドの存在。

---

### テスト2: センシティブキーがマスクされる

```python
@pytest.mark.asyncio
async def test_sanitize_sensitive_keys(logger: EventLogger, log_dir: Path) -> None:
    """token, password, secret 等のキーの値がマスクされること."""
    await logger.track(
        "api_call",
        issue_number=42,
        phase="implement",
        data={
            "url": "https://api.github.com/repos",
            "auth_token": "ghp_secret123456789",
            "password": "mysecretpass",
            "api_secret": "very_secret_value",
            "authorization": "Bearer ghp_xxxxx",
            "cookie": "session=abc123",
            "normal_field": "safe_value",
        },
    )

    events_file = log_dir / "issue-42" / "events.jsonl"
    record = json.loads(events_file.read_text().strip())

    assert record["data"]["auth_token"] == "***REDACTED***"
    assert record["data"]["password"] == "***REDACTED***"
    assert record["data"]["api_secret"] == "***REDACTED***"
    assert record["data"]["authorization"] == "***REDACTED***"
    assert record["data"]["cookie"] == "***REDACTED***"
    assert record["data"]["normal_field"] == "safe_value"
    assert record["data"]["url"] == "https://api.github.com/repos"
```

**検証ポイント**: SENSITIVE_KEYS に含まれるキーのみマスクされ、通常のキーは影響なし。

---

### テスト3: ネストされた辞書のサニタイズ

```python
def test_sanitize_nested_dict(logger: EventLogger) -> None:
    """ネストされた辞書内のセンシティブキーもマスクされること."""
    data = {
        "headers": {
            "Authorization": "Bearer ghp_xxx",
            "Content-Type": "application/json",
        },
        "body": {
            "nested": {
                "secret_key": "should_be_masked",
            },
        },
    }

    result = logger._sanitize_for_log(data)

    assert result["headers"]["Authorization"] == "***REDACTED***"
    assert result["headers"]["Content-Type"] == "application/json"
    assert result["body"]["nested"]["secret_key"] == "***REDACTED***"
```

**検証ポイント**: 再帰的にネストされた辞書もサニタイズされる。

---

### テスト4: 文字列値内のトークンパターンのマスク

```python
def test_sanitize_token_pattern_in_string(logger: EventLogger) -> None:
    """文字列値内のGitHubトークンパターンがマスクされること."""
    data = {
        "message": "Using token ghp_abcdefghijklmnopqrstuvwxyz1234567890 for auth",
        "url": "https://github.com?access_token=ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "safe": "no tokens here",
    }

    result = logger._sanitize_for_log(data)

    assert "ghp_" not in result["message"]
    assert "***REDACTED***" in result["message"]
    assert "ghp_" not in result["url"]
    assert result["safe"] == "no tokens here"
```

**検証ポイント**: `ghp_`, `gho_`, `github_pat_` パターンが値の中にあっても検出・マスクされる。

---

### テスト5: 並行書き込みの安全性

```python
@pytest.mark.asyncio
async def test_concurrent_writes(logger: EventLogger, log_dir: Path) -> None:
    """複数の並行タスクからの同時書き込みでデータが欠損しないこと."""
    async def write_event(i: int) -> None:
        await logger.track(
            f"event_{i}",
            issue_number=42,
            phase="implement",
            data={"index": i},
        )

    # 20件を並行書き込み
    tasks = [write_event(i) for i in range(20)]
    await asyncio.gather(*tasks)

    events_file = log_dir / "issue-42" / "events.jsonl"
    lines = events_file.read_text(encoding="utf-8").strip().split("\n")

    assert len(lines) == 20

    # 全てのレコードがvalid JSONであること
    events = set()
    for line in lines:
        record = json.loads(line)
        events.add(record["event"])

    # 全イベントが記録されていること
    for i in range(20):
        assert f"event_{i}" in events
```

**検証ポイント**: `asyncio.Lock` により行が混在しない。全20件が欠損なく記録される。

---

### テスト6: data=None の場合の記録

```python
@pytest.mark.asyncio
async def test_track_without_data(logger: EventLogger, log_dir: Path) -> None:
    """data=None の場合、recordに 'data' キーが含まれないこと."""
    await logger.track(
        "phase_start",
        issue_number=42,
        phase="hearing",
    )

    events_file = log_dir / "issue-42" / "events.jsonl"
    record = json.loads(events_file.read_text().strip())

    assert "data" not in record
    assert record["event"] == "phase_start"
```

**検証ポイント**: data未指定時にNullや空dictが書かれない。

---

### テスト7: write_phase_log のファイル出力

```python
@pytest.mark.asyncio
async def test_write_phase_log(logger: EventLogger, log_dir: Path) -> None:
    """write_phase_log()がタイムスタンプ付きファイル名でログを書き出すこと."""
    content = "=== Hearing Phase ===\nQuestion: What is the expected behavior?"

    await logger.write_phase_log(
        issue_number=42,
        phase="hearing",
        content=content,
    )

    # issue-42 ディレクトリ内にファイルが作成される
    issue_dir = log_dir / "issue-42"
    log_files = list(issue_dir.glob("*_hearing.log"))
    assert len(log_files) == 1

    written = log_files[0].read_text(encoding="utf-8")
    assert "What is the expected behavior?" in written
```

**検証ポイント**: `{timestamp}_{phase}.log` の命名規則。

---

### テスト8: write_phase_log のトークンマスク

```python
@pytest.mark.asyncio
async def test_write_phase_log_masks_tokens(logger: EventLogger, log_dir: Path) -> None:
    """write_phase_log()が文字列内のトークンをマスクすること."""
    content = "Auth with ghp_abcdefghijklmnopqrstuvwxyz1234567890 succeeded"

    await logger.write_phase_log(
        issue_number=42,
        phase="implement",
        content=content,
    )

    issue_dir = log_dir / "issue-42"
    log_files = list(issue_dir.glob("*_implement.log"))
    written = log_files[0].read_text(encoding="utf-8")

    assert "ghp_" not in written
    assert "***REDACTED***" in written
```

---

### テスト9: 複数Issueのイベントが分離される

```python
@pytest.mark.asyncio
async def test_events_separated_by_issue(logger: EventLogger, log_dir: Path) -> None:
    """異なるIssue番号のイベントが別ファイルに記録されること."""
    await logger.track("start", issue_number=42, phase="hearing")
    await logger.track("start", issue_number=55, phase="implement")

    file_42 = log_dir / "issue-42" / "events.jsonl"
    file_55 = log_dir / "issue-55" / "events.jsonl"

    assert file_42.exists()
    assert file_55.exists()

    record_42 = json.loads(file_42.read_text().strip())
    record_55 = json.loads(file_55.read_text().strip())

    assert record_42["issue"] == 42
    assert record_55["issue"] == 55
```

**検証ポイント**: Issue間のログが物理的に分離される。

---

### テスト10: 追記モード（既存ファイルに追加）

```python
@pytest.mark.asyncio
async def test_track_appends_to_existing(logger: EventLogger, log_dir: Path) -> None:
    """track()が既存ファイルに追記すること（上書きしない）."""
    await logger.track("event_1", issue_number=42, phase="hearing")
    await logger.track("event_2", issue_number=42, phase="hearing")
    await logger.track("event_3", issue_number=42, phase="design")

    events_file = log_dir / "issue-42" / "events.jsonl"
    lines = events_file.read_text(encoding="utf-8").strip().split("\n")

    assert len(lines) == 3
    assert json.loads(lines[0])["event"] == "event_1"
    assert json.loads(lines[1])["event"] == "event_2"
    assert json.loads(lines[2])["event"] == "event_3"
```

**検証ポイント**: 追記モード（mode="a"）で動作する。順序が保持される。

---

### テスト11: リスト値内のサニタイズ

```python
def test_sanitize_list_values(logger: EventLogger) -> None:
    """リスト値内のセンシティブデータもマスクされること."""
    data = {
        "commands": [
            "git push",
            "curl -H 'Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz1234567890'",
        ],
        "configs": [
            {"password": "secret123"},
            {"name": "safe"},
        ],
    }

    result = logger._sanitize_for_log(data)

    assert "ghp_" not in result["commands"][1]
    assert result["configs"][0]["password"] == "***REDACTED***"
    assert result["configs"][1]["name"] == "safe"
```

**検証ポイント**: リスト内の文字列・辞書も再帰的にサニタイズされる。

---

## ログローテーション（オプション）

簡易的なログローテーションとして、以下のアプローチを推奨する（初期実装ではスコープ外としてもよい）。

```python
async def _rotate_if_needed(self, events_file: Path, max_size_bytes: int = 10 * 1024 * 1024) -> None:
    """events.jsonl が max_size_bytes を超えたらローテーション."""
    if events_file.exists() and events_file.stat().st_size > max_size_bytes:
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        rotated = events_file.with_name(f"events.{ts}.jsonl")
        events_file.rename(rotated)
```

初期実装では、ファイルサイズが10MBを超えた場合にタイムスタンプ付きファイル名にリネームする。

---

## 依存関係

| 依存 | 用途 |
|------|------|
| `json` | JSONL シリアライズ |
| `datetime` | UTC タイムスタンプ生成 |
| `pathlib.Path` | ファイルシステム操作 |
| `asyncio.Lock` | 並行書き込みの排他制御 |
| `re` | トークンパターンの正規表現マッチ |
