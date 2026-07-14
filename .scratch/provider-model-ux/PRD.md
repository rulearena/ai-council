# Provider 與模型設定 UX 強化

Status: implemented / awaiting acceptance

## 產品價值

讓使用者不需理解 adapter、provider-specific listing protocol 或 CLI argv，即可可靠地新增、選擇與測試模型；同時保留新模型、客製 endpoint 與既有 `models.yaml` 的逃生路徑。

## 固定行為契約

- Anthropic 與 Gemini 可由既有 preview/existing discovery interface 載入 exact model ID；credential 只接受環境變數名稱。
- Discovery 不發出 completion、不寫入 model config；失敗或空清單保留 manual exact ID。
- Provider-specific discovery 隱藏 URL、header、pagination/response shape 差異，回傳排序去重後的 model ID list。
- Subscription CLI 提供 Claude CLI、Codex CLI、AGY、Custom CLI。preset 產生 argv，預設讓 CLI 自動選擇模型。
- preset 的進階 exact model ID 由 preset 負責轉成正確 argv；Custom CLI 與無法辨識的 legacy command 保留逐參數編輯。
- Exact argv contract（Human Owner 既有實測並於 2026-07-14 核准）：Claude `claude --model <id> -p {prompt}`；Codex `codex exec --model <id> {prompt}`；AGY `agy --model <id> -p {prompt}`。Claude/Codex 另以官方 CLI reference 交叉驗證旗標；每個 preset 自行定義 default/exact argv，不使用共用位置推論。
- 既有 subscription `command`、`extra_body.cli_provider` 與所有舊 model config 可讀、可編輯、可原樣保存；不 migration。
- Test 按鈕顯示立即 loading；進行中停用；達 slow threshold 顯示仍在等待；最新 request 才能更新狀態。
- 儲存與 discovery 不自動測試，不產生付費 completion。

## 不在範圍

- API key 明文保存、OAuth/login 管理。
- 安裝、升級或登入 Subscription CLI。
- 保證列出 provider 所有歷史、preview 或無權限模型。
- 變更 meeting assignment、runner 或歷史 events。

## 已確認 TDD seams

1. Discovery HTTP seam：`POST /models/available-models` 與 `GET /models/{id}/available-models`，外部 HTTP 以 fake transport 驗證 request 與 normalization。
2. Provider/CLI domain seam：pure provider definition、legacy projection、preset-to-payload interface。
3. Model health HTTP seam：既有 test endpoint 的 request/result；不測內部 task state。
4. Playwright seam：真瀏覽器操作 discovery、CLI preset、manual/legacy fallback 與 test loading/slow/stale race。

## 驗收

- Backend 全套不低於 280 passed；frontend unit 不低於 8 passed；新增測試全綠。
- Frontend build、完整 Chromium e2e 與真瀏覽器 smoke 通過。
- Standards 與 Spec 獨立 review pass。
- 測試 runtime 僅使用 worktree 內 `.scratch/`，禁止 `/tmp`、`mktemp` 或 workspace 外資料路徑。
