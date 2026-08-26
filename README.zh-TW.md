[English](README.md) | 繁體中文

# AI Council

本地端單人使用的 AI 會議協作應用。

本應用依據模式目錄（`config/modes.yaml`，透過 `GET /modes` 提供）執行會議。
預設的接力模式為紅藍辯論＋裁判：

1. 藍方提出方案
2. 紅方批判
3. 藍方修正
4. 裁判裁決

其他接力模式（例如 `courtroom`、`debate`）使用相同步驟流程，但有不同的名冊與提示模板；模式系統設計請見 `spec.md` 第16節。

主持人可在會議中加入人類回饋、要求單一角色回應，或執行預設角色序列（例如 `Red -> Blue -> Judge`）進行自動後續。

後端將會議事件以 JSONL 格式儲存於 `data/meetings/<meeting_id>/events.jsonl`。Markdown 逐字稿為衍生的讀取模型，並非資料來源。模型嘗試診斷為附加的事件欄位；請開啟**紀錄 → 時間線 → LLM 嘗試診斷**來查看或複製安全的 JSON 捆包。CLI 失敗摘要僅保留最後8,192個字元，並會隱藏設定的 API 金鑰與常見 Bearer 欃杖。

## 專案結構

- `backend/`：FastAPI 應用、會議執行器、持久層、提示渲染、輸出解析與模型連接器。
- `frontend/`：Vue 3 控制與偵錯介面。
- `config/models.yaml.example`：相容 OpenAI 的模型設定範例。
- `config/modes.yaml`：模式目錄（名單、步驟、提示模板），透過 `GET /modes` 提供。
- `prompts/`：會議流程使用的提示模板。
- `.scratch/mvp/`：本 MVP 的本地 PRD、票證與议题檔案。

## 後端設定

請使用 Python 3.11 或更新版本。後端依賴管理採用 `uv`，它會自動建立並使用專案虛擬環境。

```bash
cd backend
uv sync --extra dev
```

建立本地模型設定：

```bash
cd ..
cp config/models.yaml.example config/models.yaml
```

啟動 API：

```bash
scripts/dev_backend.sh
```

執行後端測試：

```bash
cd backend
uv run pytest
```

## 前端設定

```bash
cd frontend
npm install
../scripts/dev_frontend.sh
```

Vite 應用預設連接 `http://localhost:5009`。可透過以下環境變數覆寫：

```bash
VITE_API_BASE_URL=http://localhost:5009 npm run dev
```

建置前端：

```bash
cd frontend
npm run build
```

## 驗證

執行後端測試與前端型別檢查／建置：

```bash
scripts/test_all.sh
```

啟動後端與前端開發伺服器後，再執行 Playwright E2E：

```bash
RUN_E2E=1 scripts/test_all.sh
```

E2E 流程包含建立模擬會議、測試模擬模型、啟動完整輪次、加入主持人回饋、執行單一角色回應、執行預設角色序列、繼續固定輪次，並關閉會議。

## 模型設定

`config/models.yaml` 可設定一個或多個模型。你可以手動編輯，或使用應用內的**設定 → 模型管理**分頁來新增、編輯、測試與刪除模型設定（最終會以原子操作寫回同一檔案）：

```yaml
models:
  - id: qwen27
    adapter: openai-compatible-http
    base_url: http://host:port/v1
    model: model-id
    api_key_env: null
    supports_json_mode: true
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
```

`api_key_env` 對應環境變數名稱，而非實際金鑰。若為無驗證的本地端點，請設為 `null`。設定後，連接器會在請求時讀取該變數，並以對應供應商預期的方式傳送（`openai-compatible-http` 使用 `Authorization: Bearer`、`anthropic-http` 使用 `x-api-key`、`gemini-http` 使用 `?key=`）。若變數未設定，將導致明確的 `AdapterError`，而不會以無驗證方式呼叫端點。

MVP 支援的連接器：

- `mock`：本地測試用的確定性連接器。
- `openai-compatible-http`：呼叫相容 OpenAI 的伺服器 `/v1/chat/completions`。
- `anthropic-http`：呼叫 Anthropic Messages API `/v1/messages`。
- `gemini-http`：呼叫 Gemini API `/v1beta/models/{model}:generateContent`。
- `subscription-cli`：執行已驗證的 CLI 程式，無需 API 欃杖。

```yaml
- id: claude-api
  adapter: anthropic-http
  base_url: https://api.anthropic.com/v1
  model: claude-sonnet-4-5
  api_key_env: ANTHROPIC_API_KEY
  extra_body:
    max_tokens: 4096

- id: gemini-api
  adapter: gemini-http
  base_url: https://generativelanguage.googleapis.com/v1beta
  model: gemini-2.5-pro
  api_key_env: GEMINI_API_KEY
```

訂閱制 CLI 模型使用參數列表，並需包含 `{prompt}` 佔位符：

```yaml
- id: claude-subscription
  adapter: subscription-cli
  command: [claude, -p, "{prompt}"]
  timeout_seconds: 300

- id: codex-subscription
  adapter: subscription-cli
  command: [codex, exec, "{prompt}"]
  timeout_seconds: 300

- id: agy-subscription
  adapter: subscription-cli
  command: [agy, -p, "{prompt}"]
  timeout_seconds: 300
```

使用前請先各自安裝並完成驗證。應用不會讀取或管理訂閱憑證。指令會直接執行（無 shell），非零結束、缺少執行檔、空白輸出或逾時都會以模型錯誤呈現。取消會議時會立即終止仍在執行的訂閱 CLI 程式。

本應用不負責管理或啟動本地模型服務。它會呼叫已設定的相容 OpenAI 的 HTTP 端點或明確設定的訂閱 CLI 指令。

## 社群 / Community

- [貢獻指南](CONTRIBUTING.md)
- [安全政策](SECURITY.md)
- [行為準則](CODE_OF_CONDUCT.md)

## 提示模板

執行器會從 `AI_COUNCIL_PROMPT_DIR` 讀取以下檔案：

- `blue_propose.md`
- `red_critique.md`
- `blue_revise.md`
- `judge_decide.md`

可用的模板變數：

- `{{ role }}`
- `{{ topic }}`
- `{{ prior_transcript }}`
- `{{ required_json_schema }}`

模型輸出需包含一個 JSON 物件：

```json
{
  "summary": "string",
  "arguments": [{ "title": "string", "detail": "string" }],
  "risks": [{ "title": "string", "detail": "string" }],
  "recommendation": "string"
}
```

## 授權條款

本專案採用 [MIT 授權條款](LICENSE) © 2026 RuleArena。
