"""ローカルファイル I/O のセキュリティハードリング (#115 Unit C1).

読み取り/書き込みを行う各層が共通で使うための小さなヘルパー群:

- ``atomic_write_text``: tmp + chmod 0o600 + replace で原子的に書き出す。
- ``ensure_private_file``: 追記ログ等を所有者のみ可読 (0o600) で用意する。
- ``read_text_capped``: サイズ上限を超えるファイルは読まずに弾く。

いずれも **localhost バインド・単一ユーザー前提** の現行設計における多層防御。
他のローカルユーザーからの可読化 (umask 依存の 644) と巨大ファイルによる
メモリ過大消費を防ぐ。
"""

from __future__ import annotations

import os
from pathlib import Path

# 所有者のみ読み書き (rw-------)。他ローカルユーザーからの読み取りを防ぐ。
PRIVATE_FILE_MODE = 0o600

# 状態/ヘルス系 (health/queue/state) の読み取り上限。これらは小さい想定。
MAX_STATUS_FILE_BYTES = 5 * 1024 * 1024  # 5 MiB

# 追記ログ (events/agent) の読み取り上限。通常運用で増えるため余裕を持たせる。
MAX_LOG_FILE_BYTES = 64 * 1024 * 1024  # 64 MiB


class FileTooLargeError(OSError):
    """ファイルが許容サイズ上限を超えたため読み取りを拒否したことを表す。

    ``OSError`` を継承するので、読み取り側の既存の ``except OSError`` が
    そのまま捕捉でき、安全側 (停止中扱い / 空) に倒せる。
    """


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """tmp ファイル経由で原子的に書き出し、最終ファイルを 0o600 にする。

    親ディレクトリが無ければ作成する。tmp に書いてから ``chmod 0o600`` し、
    ``replace`` で差し替える (rename は inode の権限を引き継ぐので最終ファイルも
    0o600 になる)。既存ファイルの広い権限も上書きで 0o600 にリセットされる。

    Args:
        path: 書き出し先のパス。
        text: 書き出す文字列。
        encoding: テキストエンコーディング。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = path.with_suffix(".tmp")
    tmp_file.write_text(text, encoding=encoding)
    os.chmod(tmp_file, PRIVATE_FILE_MODE)
    tmp_file.replace(path)


def ensure_private_file(path: Path) -> None:
    """追記用ファイルを所有者のみ可読 (0o600) で用意する。

    親ディレクトリを作成し、ファイルが未作成なら 0o600 で作成する。既存ファイルの
    中身は破壊しない (追記ログ前提)。``open("a")`` の直前に呼ぶことで、umask に
    依存せず作成時点から他ローカルユーザー可読を防ぐ。

    Args:
        path: 追記対象のファイルパス。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    # 作成と同時に権限を絞る。umask 非依存にするため chmod も明示的に行う。
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, PRIVATE_FILE_MODE)
    os.close(fd)
    os.chmod(path, PRIVATE_FILE_MODE)


def read_text_capped(path: Path, max_bytes: int, *, encoding: str = "utf-8") -> str:
    """サイズ上限以内のときだけファイル全体を読み込む。

    ``st_size`` が ``max_bytes`` を超える場合は読み込まずに ``FileTooLargeError``
    を送出する (巨大ファイルでのメモリ過大消費を防ぐ)。

    Args:
        path: 読み取り対象のファイルパス。
        max_bytes: 許容する最大バイト数 (この値ちょうどは許可)。
        encoding: テキストエンコーディング。

    Returns:
        ファイル内容の文字列。

    Raises:
        FileTooLargeError: ファイルサイズが ``max_bytes`` を超える場合。
        OSError: stat / read に失敗した場合 (呼び出し側の既存ハンドリングに委ねる)。
    """
    size = path.stat().st_size
    if size > max_bytes:
        raise FileTooLargeError(f"file exceeds size limit: {size} > {max_bytes} bytes")
    return path.read_text(encoding=encoding)
