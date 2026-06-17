# WSL2 常駐デプロイ / コスト上限の自動停止（#92）

自宅 Windows デスクトップ（WSL2）で 3 プロセス（next / api / orchestrator）を常駐させ、
外からはリモートデスクトップで操作する運用を想定する。

> 本ドキュメントのうち **「日次コスト上限の自動停止」は実装済み**。WSL2 セットアップ
> スクリプト・systemd unit・logrotate・再起動復帰手順は順次整備する（Mac でのフルスタック
> 動作を優先しているため後追い）。

## 日次コスト上限の自動停止（実装済み）

`config.yaml` の `cost_limits.daily_usd` に上限（USD）を設定する。0 以下なら無効。

```yaml
cost_limits:
  daily_usd: 20.0   # 1 日の累積コストが 20 ドルを超えたら自動停止
```

挙動:

- orchestrator はフェーズ完了ごとに当日（UTC）の累積コストを加算する。
- 上限を超えると **1 度だけ** 次を行う:
  1. `cost_limit_exceeded` イベントを記録し、Slack 通知（設定時）。
  2. タスクキューを drain（新規ディスパッチを止める）し、in-flight 完了後に graceful stop。
- 日付（UTC）が変わると累積はリセットされる。

### systemd と併用する場合の注意（重要）

`orchestrator` の unit は **`Restart=on-failure`** にすること。`Restart=always` だと
コスト上限で自動停止しても systemd が即座に再起動させ、課金が止まらない。
`next` / `api` の 2 unit は `Restart=always` で良い。

停止は「control.jsonl に shutdown を積む → 猶予後に `systemctl --user stop`」の 2 段階で行う
方式と整合する（#87 の起動/停止方式）。本機能の in-process 停止（drain → graceful stop）は
その in-process 等価であり、systemd 環境では unit 設定で再起動を防ぐ。

## 残作業（未実装・順次整備）

- [ ] WSL2 セットアップスクリプト（uv / node / 依存一式）
- [ ] systemd unit 3 本（next/api=Restart=always, orchestrator=Restart=on-failure）+ Windows タスクスケジューラでの WSL 自動起動
- [ ] listen 127.0.0.1 固定の確認（外部公開なし）
- [ ] logrotate（events / agent ログ 30 日）
- [ ] 再起動復帰の手順書（state.json レジューム + control.jsonl 未消費分）
