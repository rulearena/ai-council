# 案卷容量限制設定化實作計畫

**Goal:** 完成 backlog 81。將 Case Files Phase 1 的硬編碼 20,000/60,000 字元限制改成可設定且對使用者可見的 50,000/120,000 預設，建立前提供 token/context 風險與明確錯誤，不做 RAG。

## Architecture contract

- 環境變數：`AI_COUNCIL_MAX_CASE_FILE_CHARS`、`AI_COUNCIL_MAX_TOTAL_CASE_FILE_CHARS`。
- 預設值：單份 50,000、總量 120,000；必須是正整數且總量不得小於單份，無效設定使 app startup 以清楚訊息失敗。
- `GET /case-file-limits` 回傳實際生效的 `per_file_chars`、`total_chars`，前端不得假設 env 仍是預設值；後端不可接受超出該值的 payload。
- 字元計算沿用 Python/JavaScript Unicode string length 的既有近似；token 只標示「粗估」，不得宣稱模型 tokenizer 精確值。
- token 粗估採保守且可解釋的 UI heuristic：CJK 字元每字約 1 token，其他非空白字元約 4 字元 1 token；僅供風險提示，不參與後端驗證。
- 超限時 modal inline 顯示哪一份或總量超限，停用建立按鈕且不得送 `POST /meetings`。
- 即使 client 預檢通過後 server 仍回錯（例如 limits 在頁面載入後改變），modal 必須顯示 FastAPI `detail`，保留使用者輸入。
- 不取消 hard limit、不新增 model context-window 欄位、不摘要/切片/檢索、不改案卷儲存與 role visibility。

## Confirmed TDD seams

- **Config/API seam:** app startup + `GET /case-file-limits` + `POST /meetings`。
- **Frontend seam:** Playwright 透過 New Case modal 觀察 limits、inline validation、network request 與輸入保留。
- **Compatibility seam:** 無案卷與既有小案卷建立流程保持不變；API 413 detail 契約仍為 string。

## Tasks

1. Backend red→green：預設/覆寫 limits endpoint；50,000 可接受、50,001 拒絕；總量 120,001 拒絕；invalid env/startup 拒絕。
2. Frontend red→green：載入實際 limits；每份/總量與 token 粗估；超限 inline + disabled/no POST；合法 payload 可建立。
3. Error red→green：server 413 detail 顯示在 modal，modal 不關閉、輸入不遺失。
4. Docs/gates：`.env.example`、backend full、frontend build、full e2e、真 Chromium smoke。

## Acceptance baseline

- Backend 不低於 241 passed，新增 tests 全綠。
- Frontend build 綠；Chromium 不低於 31 passed，新增情境全綠。
- 獨立 Spec/Quality review pass；merge main、清理 worktree/branch，標記 `implemented / awaiting acceptance`。
