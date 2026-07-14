# 每場會議的 LLM attempt 診斷紀錄與檢視器

Status: ready-for-agent
Blocked by: none

## Goal

依 `docs/plans/2026-07-14-llm-attempt-diagnostics.md` 完成 backlog 82。

## Required behavior

- relay、directed、parallel 的成功與失敗 attempt 具備一致、additive 的診斷欄位。
- Parse/schema failure 保存完整 raw output 與可取得的 token usage，且 auto retry 語意不變。
- CLI timeout/exit 保存 bounded、redacted excerpts 與結構化分類；不保存 command、env 內容或 secret。
- GET meeting 回傳診斷欄位；舊 events 缺欄位仍正常。
- Records Drawer 診斷預設摺疊，可查看與複製 JSON。

## Forbidden

- 不改 retry 次數、timeout 政策、模型選擇、prompt/output schema、RAG。
- 不改寫既有 meeting/events；不建立全域或 workspace 外 log。
- 不把 secret、完整 CLI command 或環境變數內容寫入 event。

## TDD and verification

- 僅使用計畫已確認的四個 public seams，逐一 red→green。
- Targeted backend/adapter/API、frontend build、targeted Chromium；最後 backend full + full Chromium。
- 回報 commits、red/green 證據、完整 gates、未驗證範圍與模型 runtime。

## Comments
