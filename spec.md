# AI 眾議院 MVP 規格書

## 1. 產品定位

AI 眾議院是一個可插拔模型執行池的 AI 會議 orchestration 系統。使用者可以建立一場由多個 AI 角色參與的結構化討論，系統負責排程、紀錄、解析、重試、取消與即時狀態呈現。

MVP 的核心是先把 AI 會議室的 orchestration 做穩，並提供基本的訂閱制 CLI provider，讓已登入的 CLI 可作為模型執行來源。

## 2. MVP Scope

MVP 只做紅藍對抗模式，固定三個角色：

1. Blue：提出初始方案
2. Red：攻擊方案並指出缺陷
3. Judge：閱讀完整對話並給出裁決與建議

固定流程：

```text
Blue propose -> Red critique -> Blue revise -> Judge decide
```

使用者可以：

- 建立 meeting（必填 topic，作為討論主題注入所有角色 prompt）
- 列出 meetings
- 開啟單一 meeting
- 替 Blue / Red / Judge 選擇 model config
- 啟動紅藍對抗流程
- 取消整場 meeting run
- retry failed step
- 下載 Markdown transcript
- 測試 model connection

## 3. Non-Goals

MVP 不做：

- 平行腦力激盪模式
- 自訂 Agent 數量、角色、回合拓撲
- Deep Dive 追問與二次總結
- token streaming 逐字輸出
- Ollama 專用 adapter
- 前端模型設定管理 UI
- 前端 prompt editor
- 帳號、登入、權限、多租戶
- 多 project / workspace
- Docker Compose / production deployment
- 完整 Playwright E2E
- 本地模型服務安裝、啟動、GPU/VRAM 管理

## 4. Architecture

技術棧：

```text
Frontend: Vue 3 + TypeScript + Vite
Backend: Python FastAPI
Realtime: WebSocket
Persistence: local files
Config: YAML
Backend tests: pytest
```

核心後端模組：

```text
MeetingRunner
MeetingRepository
ModelAdapter
PromptRenderer
TranscriptProjector
ModelConfigRepository
```

後端 orchestration 必須放在可測試的 Python service 中，不得把核心流程塞進 API route 或 WebSocket handler。

## 5. Model Adapter Design

模型執行層以「呼叫方式」分類，不以「雲端 / 本地」分類。

MVP 正式 adapter：

```text
mock
openai-compatible-http
subscription-cli
```

`openai-compatible-http` 同時支援雲端 API 與本地 HTTP endpoint，例如：

```text
https://api.openai.com/v1
http://localhost:8000/v1
http://<vllm-server>/v1
http://<lm-studio-server>/v1
http://<llama-cpp-server>/v1
```

本地模型 runtime 是外部依賴。系統只呼叫已存在的 HTTP endpoint，不負責安裝模型、下載權重、啟動服務或管理 GPU。

`openai-compatible-http` 在 endpoint 支援時應帶上 `response_format: {"type": "json_object"}`（OpenAI 與 vLLM 均支援），以降低 JSON 解析失敗率。是否啟用由 model config 控制（見第 6 節 `supports_json_mode`）。

## 6. Model Config

MVP 使用檔案設定模型，不做前端新增/編輯模型設定。

暫定檔案：

```text
config/models.yaml
```

範例：

```yaml
models:
  - id: mock-fast
    adapter: mock

  - id: local-qwen
    adapter: openai-compatible-http
    base_url: http://localhost:8000/v1
    model: Qwen/Qwen2.5-72B-Instruct
    api_key_env: null
    supports_json_mode: true

  - id: openai-main
    adapter: openai-compatible-http
    base_url: https://api.openai.com/v1
    model: gpt-4o
    api_key_env: OPENAI_API_KEY
    supports_json_mode: true
```

MVP 支援最小 model availability check：

- `GET /models` 回傳 configured models
- 每個 model 有 `status: unknown | available | unavailable`
- 後端啟動時不因模型不可用而失敗
- 前端可按 Test connection
- Test connection 發送一個小 prompt
- `POST /models/{model_config_id}/test` 對 `openai-compatible-http` 會實際呼叫 adapter；成功回 `available`，失敗回 `unavailable` 與錯誤訊息

## 7. Prompt Templates

Prompt templates 放在檔案，不寫死在 Python code。

暫定：

```text
prompts/blue_propose.md
prompts/blue_revise.md
prompts/red.md
prompts/judge.md
```

Blue 有兩種發言階段，任務不同，各用獨立 template：

- `blue_propose.md`：僅根據 topic 提出初始方案
- `blue_revise.md`：閱讀 Red 的攻擊後修訂方案

後端注入：

```text
topic
prior_transcript
role
required_json_schema
```

MVP 預設繁體中文，不做語系切換。

## 8. Output Schema

MVP 三個角色共用同一個 output JSON schema，角色差異由 prompt 控制。

暫定 schema：

```json
{
  "summary": "string",
  "arguments": [
    {
      "title": "string",
      "detail": "string"
    }
  ],
  "risks": [
    {
      "title": "string",
      "detail": "string"
    }
  ],
  "recommendation": "string"
}
```

Parser 策略：

- 要求模型輸出 JSON
- 解析前先做基本解碼（視為 parser 的一部分，不算 purifier）：
  - 剝除 markdown code fence（```` ```json ```` / ```` ``` ````）
  - 擷取回應中第一個完整 JSON 物件，忽略前後多餘文字
- 後端用 schema 驗證
- 驗證失敗自動 retry 一次（同一 step 產生新 attempt event）
- 自動 retry 仍失敗才將該 step 標記為 `failed`
- 使用者可手動 retry failed step
- MVP 不做語意層 Regex purifier、LLM fallback purifier、匿名化洗白

## 9. Data Model And Persistence

JSONL event log 是唯一真相來源。Markdown transcript 是 read model / 報表，不作為系統狀態來源。

資料結構：

```text
data/
  meetings/
    <meeting_id>/
      events.jsonl
      transcript.md
      metadata.json
```

`data/` 根目錄位置可透過環境變數（暫定 `AI_COUNCIL_DATA_DIR`）覆寫。`events.jsonl` 是高頻 append 的執行期資料，若專案放在雲端同步資料夾（如 Synology Drive），建議把 data 目錄指到同步範圍外，避免同步衝突產生 conflicted copy。

事件至少記錄：

```text
event_id
meeting_id
step_id
role
model_config_id
prompt_messages
raw_output
parsed_output
status
started_at
completed_at
error
```

每次 agent 呼叫必須保存完整 prompt、raw model output、parsed output 與錯誤資訊，以利除錯 AI 決策流程。

`transcript.md` 從 `events.jsonl` 產生，供人閱讀、下載、分享或丟給 LLM 摘要。

## 10. Resume, Cancel, Retry

MVP 支援最小中斷恢復：

- 後端重啟或前端重整後，可以從 `events.jsonl` 還原已完成發言與 meeting 狀態
- 不自動重送正在執行中的 API 呼叫
- 中斷中的 step 先標記為 `failed`，由使用者手動 retry

MVP 支援取消整場 meeting run：

- 使用者可以 cancel meeting
- 未開始 steps 不再執行
- 執行中 HTTP request 嘗試取消
- 若底層無法取消，標記 `cancel_requested`，結果回來後丟棄
- `events.jsonl` 記錄 cancellation event

MVP 支援 retry failed step：

- 只能 retry failed step
- retry 使用同一份 prior context 重新組 prompt
- retry 產生新的 attempt event，不覆蓋舊失敗紀錄
- retry 成功後 meeting 可從該 step 繼續往下跑

狀態投影規則：

- 同一個 step 有多個 attempt 時，以「最新一次 attempt」為準
- `TranscriptProjector` 與前端 step timeline 都遵守此規則
- 舊 attempt 保留在 `events.jsonl` 供除錯，但不進 transcript

併發語意：

- 後端為單一 process
- 每場 meeting 同時只能有一個 run；meeting 執行中再呼叫 `start` 回 `409 Conflict`
- 不同 meeting 可以同時執行

## 11. API And WebSocket Surface

前端不直接讀 Markdown 檔。前端透過後端 API / WebSocket 取得 meeting 狀態。

暫定 API：

```text
GET    /models
POST   /models/{model_config_id}/test

GET    /meetings
POST   /meetings              # body 必填 topic
GET    /meetings/{meeting_id}
DELETE /meetings/{meeting_id}
POST   /meetings/{meeting_id}/start   # 202 Accepted，背景執行
POST   /meetings/{meeting_id}/cancel
POST   /meetings/{meeting_id}/close
POST   /meetings/{meeting_id}/messages
POST   /meetings/{meeting_id}/messages/{event_id}/correct
POST   /meetings/{meeting_id}/roles/{role}/respond
POST   /meetings/{meeting_id}/sequences
POST   /meetings/{meeting_id}/steps/{step_id}/retry
GET    /meetings/{meeting_id}/transcript.md
```

WebSocket：

```text
WS /meetings/{meeting_id}/events
```

WebSocket 先傳完整 snapshot，之後持續傳送 `activity_status` 與新增事件，直到前端斷線。

前端重新整理時：

```text
GET /meetings/{meeting_id}
```

後端讀取 `events.jsonl` 還原狀態並回傳。

## 12. Frontend UX

MVP 前端採操作台 / 除錯台風格，不做華麗會議室視覺化。

暫定 layout：

```text
左側：meeting list
上方：create meeting + Blue/Red/Judge model selectors
中央：step timeline
右側：raw/debug panel
底部：role output cards + transcript preview
```

前端必須使用穩定 `data-testid` contract，以利未來測試：

```text
meeting-list
meeting-filters
meeting-search-input
meeting-status-filter
create-meeting-button
blue-model-select
red-model-select
judge-model-select
start-meeting-button
cancel-meeting-button
close-meeting-button
step-timeline
debug-panel
operation-status
role-output-panel
transcript-preview
```

MVP 不做 token streaming。前端即時性先靠狀態事件：

```text
queued
thinking
parsing
completed
failed
cancel_requested
cancelled
```

## 12.1 Post-MVP: Human Chair Message Slice

已實作第一個主席介入切片：

- 使用者可以在已建立的 meeting 中送出主席發言
- 主席發言透過 `POST /meetings/{meeting_id}/messages` 寫入 `events.jsonl`
- 主席發言使用 event role `Human`、step `human-message`
- `TranscriptProjector` 會把主席發言渲染進 Markdown transcript
- 後續 AI role prompt 的 `prior_transcript` 會包含主席發言
- 前端有主席發言輸入框與送出按鈕
- 主席可以修正已送出的主席發言，API 為 `POST /meetings/{meeting_id}/messages/{event_id}/correct`
- 修正會以新的 append-only Human event 保存，並用 `corrects_event_id` 指向原始主席發言
- transcript 會清楚標示主席發言修正項目
- 主席發言後再次開始/繼續討論時，後端會產生新的 AI 回合
- 第一輪維持原本 step id：`blue-propose`、`red-critique`、`blue-revise`、`judge-decide`
- 第二輪起使用 `round-N-*` step id，例如 `round-2-blue-propose`
- 事件同時保留 `base_step_id` 與 `round`，讓前端顯示與後續 retry/投影能分辨回合
- retry 可接受 round-scoped failed step，例如 `round-2-red-critique`，並用 `base_step_id` 回到固定步驟序列後繼續該輪
- 前端會在 failed timeline event 顯示 retry 按鈕，成功後重新整理 meeting 與 transcript
- 主席也可以指定單一角色回應，不必跑完整四步流程
- 指定角色回應使用 API `POST /meetings/{meeting_id}/roles/{role}/respond`
- 指定角色回應 step id 使用 `directed-N-{role}-response`，例如 `directed-1-blue-response`
- 指定角色事件記錄 `interaction_type: directed-role-response` 與 `directed_sequence`
- 主席可以執行預設角色序列，讓多個角色自動接續回應
- 角色序列使用 API `POST /meetings/{meeting_id}/sequences`
- 角色序列 request body 使用 `roles: ["Red", "Blue", "Judge"]` 與既有 `models` mapping
- 角色序列 step id 使用 `sequence-N-{role}-response`，例如 `sequence-1-red-response`
- 角色序列事件記錄 `interaction_type: role-sequence-response`、`sequence` 與 `sequence_index`
- 任一序列角色失敗時，序列停止在該 failed event，不繼續後續角色
- 主席可以直接結案，API 為 `POST /meetings/{meeting_id}/close`
- 結案會寫入 System `closed` event
- meeting 結案後，後續 `start`、指定角色回應或角色序列不再新增 AI event
- `closed` 與 `cancelled` 是 terminal state，重複 close/cancel 不會重複寫終端事件
- 前端在 terminal state 下會停用開始、取消、結案、主席發言、指定角色回應、角色序列等會新增事件的操作
- API 在 terminal state 下會以 `409 Conflict` 拒絕 start、主席發言、指定角色回應、角色序列、retry 等會新增事件的操作
- API 會投影 meeting status：`open`、`closed`、`cancelled`
- API 會投影 `activity_status`：`idle`、`waiting`、`completed`、`failed`、`closed`、`cancelled`
- API 會在 meeting read model 投影 `created_at`、`updated_at`、`last_step_id`
- 前端 meeting list 與選中會議標題會顯示 status badge 與 activity status
- 前端 meeting list 支援搜尋、status 篩選，並依 `updated_at` 由新到舊排序
- model test response 會回傳 `tested_at`，前端顯示最後測試時間與錯誤訊息
- 前端提供 role output cards，把 `summary`、`arguments`、`risks`、`recommendation` 從 raw JSON 中拆出顯示
- WebSocket 已支援非持久化 `stream_events`，讓 adapter 可在模型執行期間送出 token delta；目前已用 mock stream chunks 覆蓋後端測試，真 provider streaming 與 UI 顯示仍屬後續切片

這個切片已支援主席發言、固定回合續跑、指定單一角色回應、預設角色序列自動接續、失敗 retry、列表搜尋/篩選、角色輸出卡片與結案。尚未實作的是更完整的拓撲編輯，例如自訂 Agent 數量、拖拉排序、條件式分支、暫停/恢復佇列與可視化 speaking order。

新增前端測試 id：

```text
chair-message-input
send-chair-message-button
role-response-actions
request-blue-response-button
request-red-response-button
request-judge-response-button
role-sequence-controls
sequence-preset-select
run-sequence-button
retry-step-button
```

## 13. Testing Strategy

MVP 一開始就加測試，後端核心測試優先。

必做測試：

- `MeetingRepository` append/read events
- `TranscriptProjector` 從 events 產生 Markdown
- `MeetingRunner` 用 mock adapter 跑完整 Blue -> Red -> Blue -> Judge 流程
- failed step retry
- retry 後狀態投影以最新 attempt 為準
- cancel meeting
- parser 基本解碼：剝 code fence、擷取第一個 JSON 物件
- schema parse failure -> 自動 retry 一次 -> 仍失敗才標 failed event
- meeting 執行中重複 start 回 409
- model config loading

前端 MVP 要求：

- 主要互動元件與狀態區塊有穩定 `data-testid`
- Playwright E2E 覆蓋建立會議、列表搜尋/篩選、mock model test、狀態投影、角色輸出卡片、開始固定回合、主席發言、指定角色回應、預設角色序列、續跑第二回合、結案與 terminal disabled state

前端 component tests、真實 provider integration tests、跨瀏覽器/視覺回歸完整 gate 進 backlog。

## 14. Local Dev

MVP 不做完整 Docker 化。先提供清楚本機啟動流程。

需要提供：

```text
README local dev setup
scripts/dev_backend.sh
scripts/dev_frontend.sh
scripts/test_all.sh
config/models.yaml.example
.env.example（含 AI_COUNCIL_DATA_DIR 說明）
```

## 15. Backlog

1. Human message editing/correction：主席發言送出後的修正策略與事件記錄（已落地為 append-only correction event）
2. Token streaming：Agent 逐字輸出到前端（backend WebSocket foundation 已落地；真 provider streaming 與 UI 顯示待後續）
3. 自動恢復執行中任務：後端重啟或 API 呼叫中斷時判斷是否能安全重送
4. Markdown 反向解析：從 `transcript.md` 還原狀態
5. 更多 provider adapters：Anthropic、Gemini 等
6. Subscription model CLI bridge 進階穩定化與跨版本相容性
7. Parallel brainstorming mode
8. Custom roster and topology
9. Drag-and-drop sequence/topology builder
10. Conditional branching between roles
11. Regex purifier
12. LLM fallback purifier
13. Anonymization layer
14. Advanced meeting search
15. Meeting tags/folders
16. Favorites/pinning
17. Share links/export views
18. Permissions and collaboration
19. Frontend model config management
20. Secret management
21. Additional subscription model CLI provider presets
22. Subscription model CLI subprocess cancellation and session management
23. Provider-specific CLI output normalization
24. Subscription model CLI compliance review
25. Visual meeting room UI
26. Agent character cards
27. Drag-and-drop roster builder
28. Voting/speaking-order visualization
29. Advanced dashboard views
30. Deep Dive follow-up
31. Secondary summary
32. Follow-up event threading
33. Cancel single step
34. Pause/resume meeting
35. Scheduler queue management
36. Retry successful step
37. Branching alternative histories
38. Compare attempts
39. Automatic retry policy
40. User accounts
41. Authentication/session management
42. Permissions and multi-user access
43. Team/workspace collaboration
44. Audit log for multi-user operations
45. Ollama-specific adapter
46. Background model health checks
47. Auto-discover available models from endpoint
48. Performance benchmark
49. Token usage and cost tracking
50. Multiple projects/workspaces
51. Workspace switching UI
52. Workspace-scoped model configs
53. Workspace data isolation
54. PDF export
55. HTML report export
56. Notion export
57. Google Docs export
58. Shareable links
59. Frontend prompt editor
60. Prompt versioning
61. Prompt test harness
62. Prompt library / presets
63. Role-specific output schemas
64. Schema migration/versioning
65. Rich structured verdicts for Judge
66. UI i18n
67. Prompt language presets
68. Per-meeting output language setting
69. Full Playwright E2E suite
70. Frontend component tests
71. Real provider integration tests
72. Docker Compose setup
73. Containerized deployment
74. Reverse proxy / production hosting guide
