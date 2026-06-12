// 中断 Issue のエラー詳細モック

export interface ErrorInfo {
  issue: number;
  phase: string;
  kind: string;
  message: string;
  failedAt: string;
  attempts: number;
  maxAttempts: number;
  /** 失敗した CI ログの抜粋 */
  ciLog: string;
  /** エージェントによる原因分析と提案 */
  suggestion: string;
  prNumber?: number;
}

const ciLog118 = `$ pytest tests/webhook -v

tests/webhook/test_signature.py::test_valid_signature_accepted PASSED        [ 20%]
tests/webhook/test_signature.py::test_invalid_signature_rejected PASSED      [ 40%]
tests/webhook/test_signature.py::test_timestamp_within_tolerance FAILED      [ 60%]
tests/webhook/test_signature.py::test_timestamp_expired_rejected FAILED      [ 80%]
tests/webhook/test_signature.py::test_replay_attack_rejected FAILED          [100%]

=================================== FAILURES ===================================
______________________ test_timestamp_within_tolerance ________________________

    def test_timestamp_within_tolerance():
        ts = int(time.time()) - 299  # 5分 - 1秒前
        sig = make_signature(PAYLOAD, ts)
>       assert verify_webhook(PAYLOAD, sig, ts) is True
E       AssertionError: assert False is True
E        +  where False = verify_webhook(b'{"event":"payment"}', 'v1=ab3f...', 1749500701)

tests/webhook/test_signature.py:42: AssertionError
----------------------------- Captured stdout call -----------------------------
verify_webhook: timestamp drift 301s exceeds tolerance 300s
=========================== short test summary info ============================
FAILED test_timestamp_within_tolerance - assert False is True
FAILED test_timestamp_expired_rejected - assert True is False
FAILED test_replay_attack_rejected - ReplayCache not initialized
========================= 3 failed, 2 passed in 1.84s ==========================`;

export const errorInfos: Record<number, ErrorInfo> = {
  118: {
    issue: 118,
    phase: "implement (ci_fix)",
    kind: "CI 失敗が上限超過",
    message:
      "署名検証の timestamp 許容範囲テストが 2 回の修正後も失敗。リトライ上限 (2) に達したため中断しました。",
    failedAt: "5時間前",
    attempts: 3,
    maxAttempts: 3,
    ciLog: ciLog118,
    suggestion:
      "テストが実時間 time.time() に依存しており、CI 実行のタイミングで境界値 (300s) を跨いでいる可能性が高い。verify_webhook にクロックを注入するか、テスト側で freezegun を使って時刻を固定すべき。また test_replay_attack_rejected は ReplayCache の初期化漏れで、署名検証とは別の問題。",
  },
};

export function getErrorInfo(n: number): ErrorInfo | null {
  return errorInfos[n] ?? null;
}
