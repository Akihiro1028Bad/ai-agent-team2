"""config.yaml の監視リポジトリ追加/削除 (#138).

setup コマンドと同じ「config 全体を round-trip して repositories のみ変更」方式で、
accounts や機密 (token_command 等) を温存したまま repositories を編集する。Web の
書き込み API から呼ぶため、入力検証と冪等な失敗 (明確な例外) を重視する。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# GitHub の owner / repo 名として許容する文字 (YAML/パス混入を防ぐホワイトリスト)。
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
# ブランチ名 / account 識別子の許容パターン。
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_LABEL_RE = re.compile(r"^[^\n\r]{1,100}$")


class RepoRegistryError(ValueError):
    """リポジトリ登録/削除の入力・状態エラー (API は 400/404/409 へ写す)."""


def _load(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RepoRegistryError("config.yaml の形式が不正です")
    return data


def _write(config_path: Path, data: dict[str, Any]) -> None:
    config_path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def add_repository(
    config_path: Path,
    *,
    owner: str,
    repo: str,
    account: str | None = None,
    label: str = "ai-agent",
    base_branch: str = "main",
) -> None:
    """config.yaml の repositories に 1 件追加する (#138).

    機密フィールドは受け取らない。owner/repo/branch/account/label を検証し、
    accounts は温存したまま repositories のみを更新する。

    Raises:
        RepoRegistryError: 入力不正・未登録 account・重複登録。
    """
    if not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
        raise RepoRegistryError("owner / repo は英数字・ . _ - のみ使用できます")
    if not _BRANCH_RE.match(base_branch):
        raise RepoRegistryError("base_branch の形式が不正です")
    if not _LABEL_RE.match(label):
        raise RepoRegistryError("label の形式が不正です")
    if account is not None and not _ACCOUNT_RE.match(account):
        raise RepoRegistryError("account の形式が不正です")

    data = _load(config_path)
    accounts = data.get("accounts", {})
    if account is not None and (not isinstance(accounts, dict) or account not in accounts):
        raise RepoRegistryError(f"account '{account}' は config に登録されていません")

    repositories: list[dict[str, Any]] = data.get("repositories", []) or []
    if any(r.get("owner") == owner and r.get("repo") == repo for r in repositories):
        raise RepoRegistryError(f"{owner}/{repo} は既に登録されています")

    entry: dict[str, Any] = {"owner": owner, "repo": repo, "label": label, "base_branch": base_branch}
    if account is not None:
        entry["account"] = account
    repositories.append(entry)
    data["repositories"] = repositories
    _write(config_path, data)


def remove_repository(config_path: Path, owner: str, repo: str) -> bool:
    """config.yaml の repositories から 1 件削除する (#138).

    Returns:
        削除したら True、該当が無ければ False。
    """
    data = _load(config_path)
    repositories: list[dict[str, Any]] = data.get("repositories", []) or []
    remaining = [r for r in repositories if not (r.get("owner") == owner and r.get("repo") == repo)]
    if len(remaining) == len(repositories):
        return False
    data["repositories"] = remaining
    _write(config_path, data)
    return True


def list_repositories(config_path: Path) -> list[dict[str, Any]]:
    """config.yaml から repositories の非機密フィールドのみを読み出す (#138).

    ファイル不在/不正は空リスト。token 等の機密は元々 repositories には無いが、
    既知の非機密キーのみへ正規化して返す。
    """
    try:
        data = _load(config_path)
    except RepoRegistryError:
        return []
    rows: list[dict[str, Any]] = []
    for r in data.get("repositories", []) or []:
        if not isinstance(r, dict) or "owner" not in r or "repo" not in r:
            continue
        rows.append(
            {
                "owner": r.get("owner"),
                "repo": r.get("repo"),
                "account": r.get("account"),
                "label": r.get("label", "ai-agent"),
                "base_branch": r.get("base_branch", "main"),
                "slack_channel": r.get("slack_channel"),
            }
        )
    return rows
