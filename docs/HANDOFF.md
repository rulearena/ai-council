# 交接文件（2026-07-13，Claude → Codex）

> 給接手開發的 agent（Codex 或任何新 session）。讀完本檔 + 引用的 spec 章節即可接續，不需要舊對話脈絡。

## 1. 現況：什麼已經完成

目前分支包含四個已完成的大功能，全部驗證通過：

| 功能 | Merge commit | 內容 |
|------|--------------|------|
| Mode system slice A | `981f355` | 前端席位動態化、模式卡片牆、本地 catalog |
| Mode system slice B | `059dcbe` | `config/modes.yaml` + `GET /modes` + relay 執行器參數化 + 法庭審理/辯論上線（實作計畫留檔：`docs/plans/2026-07-12-mode-system-slice-b.md`） |
| Model config mgmt（spec §17） | `ac44fef` | 模型 CRUD API + Settings 模型管理分頁（實作計畫：`docs/plans/2026-07-13-model-config-management.md`） |
| Mode system slice C | 本次分支 | parallel 執行器 + per-member retry/synthesis gating + 腦力激盪上線；六帽/盲測設定與 prompt 補齊（實作計畫：`docs/plans/2026-07-13-mode-system-slice-c.md`） |

**驗收基線（任何改動後不得低於此）**：後端 `pytest` **180 passed**；前端 `npm run build` 綠；e2e **28/28**。

## 2. 待辦佇列（優先序）

1. **Backlog 76–77 清理**（小）：測試 flake timeout 放寬；ghost mode_id 防禦、DEFAULT_MODE_ID 常數、錯誤碼對稱、NewCaseModal 失敗保留輸入。
2. **Reopen endpoint**（backlog 75）：append `reopened` event；`api.py` 的 `project_meeting_status`/`reject_terminal_meeting` 與 `runner._is_terminal` 的終端判定需認得它（掃到 cancelled/closed 之後若有 reopened 則不算終端）。
3. **案卷 Phase 1**（backlog 78）：per-role 可見的文件注入。沿用 slice B 建的 inputs 注入機制（`PromptRenderer.render(inputs=...)`）+ `{{ case_files }}` 佔位符。**不做 RAG**（backlog 79 明文延後）。
4. **Slice D：彙整匿名化 hook 啟用**（spec §16.3、§16.7 切片 D）：slice C 已預留彙整輸入組裝點，預設仍關閉。
5. 新角色立繪：使用者自行產圖，不是 agent 工作。

## 3. 架構關鍵事實（改動前必讀）

- **模式是設定不是程式碼**：`config/modes.yaml`（六模式）→ `backend/ai_council/meetings/modes.py`（`ModeCatalogRepository` + `relay_plan()`/`parallel_plan()`）。relay step_id 慣例 = template 名把 `_` 換 `-`；parallel fanout step_id = `fanout-{round}-member-{k}`，base_step_id = `member-{k}`，synthesis step_id = `synthesis-{round}`。directed response = relay 角色**最後一個** step 的 template，step_id `{role小寫}-response`。
- **相容鐵則**：events.jsonl 既有 step_id（`blue-propose`、`round-N-*`、`directed-N-*`、`sequence-N-*`）不可變；無 `mode_id` 的舊會議投影為 red-blue；共用 output schema（spec §8）不變。守門測試：`backend/tests/test_mode_catalog.py::test_repo_modes_yaml_is_loadable`。
- **Runner**：relay 公開方法收 `plan: RelayPlan` + `inputs`（API 層用 `meeting_mode()` → `relay_plan(mode)` 解析）。relay round 計數 = `plan.steps[-1].step_id` 完成次數。parallel 走 `MeetingRunner.start_parallel()` / `retry_failed_parallel_step()` + `ParallelPlan`；fanout adapter calls 併發，事件按 member index 寫入，member failure 投影 `waiting`，retry 成功且全員完成後觸發 synthesis。
- **模型寫入紀律**（§17 實作）：所有 models.yaml 寫入走 `model_write_lock`（存在性檢查+寫入+health clear 同鎖）；health store 有 generation token——**generation 取值必須在讀 model config 之前**（先取 gen → 讀 config → 檢查 → record(gen)，過期即丟棄）；`_write_config` 是 temp+rename 原子寫。
- **422 契約**：/models 寫入路徑的驗證錯誤（含 pydantic 層）統一 `[{"field", "message"}]`，前端 `ApiError.detail` 依 field 對應表單欄位。
- **前端 active mode**：`useCouncil.ts` 的 `activeModeSource`（module ref）跟著 `selectedMeeting.mode_id` 走（watchEffect，catalog splice 會重解析）；場景 override 是 keyed watch（`meeting_id::defaultScene` 字串）——**不要 watch 整顆 meeting 物件**（串流事件會整物件替換）。catalog 來源 = `GET /modes`，`modes.ts` 本地常數只是後端不可達時的 fallback。
- **前端無 unit test runner**，只有 Playwright e2e（`frontend/tests/e2e/control-flow.spec.ts`，共用一個 spec 檔）。

## 4. 開發環境

- 後端測試：`cd backend && .venv/bin/python -m pytest tests/ -q`（venv 在主 repo `backend/.venv`；worktree 沒有 venv——pytest `pythonpath=["."]` 會 import 執行目錄的程式碼，所以**在 worktree 的 backend 目錄下用主 repo 的 venv 跑**即測 worktree 的碼）。
- **已知 flake（backlog 76）**：`test_api.py` 少數測試在機器負載下偶發超時（`wait_for_activity` 2s deadline），單獨重跑即過。全套紅一個先單獨重跑再判斷。
- e2e：`playwright.config.ts` 無 webServer，baseURL 吃 `E2E_BASE_URL`（預設 3009）。**主 repo 的 3009/5009 常被使用者的 dev server 佔用**——一律用空閒 port 自起：
  ```bash
  DATA=$(mktemp -d); cp config/models.yaml.example $DATA/models.yaml
  AI_COUNCIL_DATA_DIR=$DATA AI_COUNCIL_MODEL_CONFIG_PATH=$DATA/models.yaml \
    <主repo>/backend/.venv/bin/python -m uvicorn ai_council.main:app --port 8123 &
  cd frontend && npx vite --port 3123 &
  E2E_BASE_URL=http://127.0.0.1:3123 \
  PLAYWRIGHT_BROWSERS_PATH=<主repo>/frontend/.cache/ms-playwright npx playwright test
  ```
  e2e 會寫入 models.yaml（模型管理測試），**絕不可指向 repo 的 config/**。跑完清理進程與暫存目錄。
- 環境變數：`AI_COUNCIL_DATA_DIR` / `AI_COUNCIL_MODEL_CONFIG_PATH` / `AI_COUNCIL_MODES_CONFIG_PATH` / `AI_COUNCIL_PROMPT_DIR`（見 `.env.example`）。

## 5. 工作規範（使用者的既定政策）

- **一個 feature 一個 worktree**（前後端可共用），完成即 merge 回 main 並刪 worktree/branch——**不批次**。trivial 單檔修改可直接 main。
- **TDD**：先寫 failing test、確認紅燈（且紅得有意義——參考兩份留檔計畫裡的紅燈驗證寫法）、再實作。
- 寫計畫：大 feature 先寫 `docs/plans/YYYY-MM-DD-<name>.md`（兩份現有計畫是格式範本），bite-sized tasks、完整程式碼、明確驗收線。
- 註解風格：解釋 why、不留實作史（不要寫「Task 5 加的」）；spec.md 與文件用繁體中文。
- 完成一項就在 spec.md backlog 標記（已完成 YYYY-MM-DD）。
- Commit 訊息慣例照 git log；使用者信任「測試綠 + 真瀏覽器冒煙」為驗收，冒煙要真的開瀏覽器操作，不是只跑測試。

## 6. 交接時的未結事項

- `mode-system-slice-c` worktree/branch 完成待 merge；驗收已通過：backend 180 passed、frontend build 綠、e2e 28/28。
- spec §16 slice D 未實作；§17 已完成。
- 使用者已裁定：個人版不做多人/帳號（backlog 有註記）；案卷 Phase 1 不做 RAG。
