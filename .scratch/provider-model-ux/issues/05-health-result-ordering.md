# Model health result ordering

Type: task
Status: resolved
Blocked by: 03

## 問題

Frontend 已只接受最新 test request，但 backend `ModelHealthCheckStore` generation 只在 model config clear 時遞增。若舊 test/startup health check 晚於新 test 完成，舊結果仍可能覆寫 health projection，下一次 `GET /models` 又顯示過期狀態。

## 目標

每次 health check 開始時取得單調遞增 token；只有該 model 最新 token 的結果能寫入。Model save/delete clear 仍須使所有 in-flight token 失效。

## TDD

- Store public interface：newer check records first，older late record 被丟棄。
- HTTP seam：同 model 兩個 concurrent test 以 controlled adapter 反向完成，最後 projection 保留 newer result。
- Startup checker 與 manual test race、save-during-check 既有契約不退化。

## 驗收

- Targeted backend tests 與 API regression 綠；不改 response schema；單一目的 commit。

## Resolution Notes

- `ModelHealthCheckStore.begin(model_id)` 為每次檢查配置遞增 token；`record()` 只接受該模型最新 token，避免舊檢查 late-write。
- Manual HTTP test 與 startup checker 都在讀取 model config 前 begin；save/delete 的 `clear()` 繼續推進 token，使所有 in-flight 結果失效。
- 新增 store ordering、反向完成的 concurrent HTTP tests，以及 save-during-check regression；API regression 123 passed，完整 backend 290 passed。
