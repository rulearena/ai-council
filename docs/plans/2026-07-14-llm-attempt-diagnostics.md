# LLM Attempt 診斷紀錄與檢視器實作計畫

**Goal:** 完成 spec backlog 82，讓每場 meeting 的成功與失敗模型 attempt 都具備可追溯診斷資料，並能從 Records Drawer 安全查看與複製。

**Architecture:** `events.jsonl` 維持唯一真相來源，不另建全域 debug log。Runner 在模型呼叫前建立 attempt timing，透過一個共用 failure-event seam 將 relay、directed、parallel 的 parse/schema/adapter failure 正規化。Adapter error 可攜帶安全、有限長度的診斷 excerpt；API 只做既有 event projection，前端 Records Drawer 讀取 additive event fields。舊 event 缺欄位時保持正常呈現。

## 固定契約

- 每次完成 attempt 保存：`model_config_id`、`adapter`、`prompt_messages`、`raw_output`、`parsed_output`、可取得的 `token_usage`、`started_at`、`completed_at`、`duration_ms`。
- 每次失敗 attempt 另保存：`failure_kind`、`error`、`retry_scheduled`；parse/schema failure 保存 `OutputParseError.raw_output` 與 response token usage。
- `failure_kind` 至少區分 `parse_error`、`timeout`、`adapter_error`、`configuration_error`、`interrupted`。
- Subscription CLI timeout/非零 exit 最多保存 stdout/stderr 各 8,192 字元的尾端 excerpt；寫入前遮罩該模型設定所指向的 API key 值與常見 Bearer token。不得保存完整 command 或環境變數內容。
- Records Drawer 的診斷 `<details>` 預設關閉；內容包含分類、模型、adapter、attempt、時間、retry 狀態、error、raw output 與 adapter excerpts，並可複製 JSON 診斷包。
- 所有欄位為 additive；舊 events、transcript、step/attempt IDs 與狀態投影不變。
- 不變更 retry 次數、timeout 秒數與自動／手動 retry 政策，不修改模型選擇、prompt schema、RAG 或既有 meeting 資料。

## 已確認 TDD seams

1. **MeetingRunner → MeetingRepository public event seam**：fake adapter 產生 malformed JSON、adapter error 與 parse retry，讀回 `events.jsonl` 驗證診斷欄位和原始輸出。
2. **SubscriptionCLIAdapter seam**：可控制的 timeout／non-zero subprocess fixture 驗證 bounded/redacted stdout/stderr 與 failure classification。
3. **HTTP meeting projection seam**：`GET /meetings/{id}` 對新欄位透明，舊事件缺欄位仍可讀。
4. **Playwright Records Drawer seam**：真瀏覽器展開失敗診斷、檢查預設摺疊與複製內容；不依賴私有 Vue state。

## Tasks

1. 以 runner public seam 建立 parse failure red test；保存完整失敗 attempt 診斷後轉綠。
2. 以 adapter public seam 建立 timeout/exit red tests；加入 structured diagnostics、bounded excerpt 與 secret redaction 後轉綠。
3. 將共用 attempt diagnostics 套用 relay/directed/parallel 與 interrupted path，鎖定舊狀態投影和 retry 語意。
4. 擴充 frontend event type 與 Records Drawer 診斷 details/copy UI，以 Playwright red→green 驗證。
5. 更新文件；執行 targeted tests、backend full、frontend build、full Chromium、`git diff --check`。

## 驗收線

- Backend 不低於 249 passed，新增 tests 全綠。
- Frontend build 綠；Chromium 不低於 37 passed，新增情境全綠。
- 雙軸獨立 review 均 pass；worktree、暫存服務與測試資料清理完成。
