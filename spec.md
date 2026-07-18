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
prompts/red_critique.md
prompts/judge_decide.md
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
- 後端會用每場 meeting 的 `execution.json` 暫存目前正在呼叫模型的 step；正常完成或已處理失敗會清除，若後端重啟時仍殘留，啟動時會追加 failed event

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

> 註（2026-07-12）：Post-MVP 前端已演進為沉浸式議事廳（場景 + 席位 + 抽屜/彈窗收納），本節保留為 MVP 歷史紀錄；現行前端架構見第 16.6 節與 `frontend/src/scenes.ts`。

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

> **Backlog Source of Record（SoR）**：本節是本產品唯一的 canonical product backlog。所有延期但仍可能實作的產品工作，都必須在此記錄；不得以 `.scratch/` 或 `docs/HANDOFF.md` 維護另一份產品 backlog。`.scratch/` 僅存放已核准工作的 PRD/ticket 執行資料，`docs/HANDOFF.md` 僅快照目前狀態、驗收基線與目前已核准批次。

1. Human message editing/correction：主席發言送出後的修正策略與事件記錄（已落地為 append-only correction event）
2. Token streaming：Agent 逐字輸出到前端（backend WebSocket foundation 已落地；真 provider streaming 與 UI 顯示待後續）
3. 自動恢復執行中任務：後端重啟或 API 呼叫中斷時判斷是否能安全重送（backend interrupted-state detection 已落地；不自動重送）
4. Markdown 反向解析：從 `transcript.md` 還原狀態
5. 更多 provider adapters：Anthropic、Gemini 等（已完成：anthropic-http / gemini-http adapters 已落地）
6. Subscription model CLI bridge 進階穩定化與跨版本相容性
7. Parallel brainstorming mode（已完成 2026-07-13：brainstorm 上線，six-hats / persona-testing 設定補齊；執行器規格見 §16.3）
8. Custom roster and topology（設計已定，見第 16 節）
9. Drag-and-drop sequence/topology builder
10. Conditional branching between roles
11. Regex purifier
12. LLM fallback purifier
13. Anonymization layer（已完成 2026-07-13：parallel synthesis anonymization hook；設定見 `synthesis.anonymize_inputs`，實作見 §16.3/§16.7）
14. Advanced meeting search
15. Meeting tags/folders（已完成：tags 已落地，PUT /meetings/{id}/tags）
16. Favorites/pinning（已完成：pinned 已落地，PUT /meetings/{id}/pinned）
17. Share links/export views
18. Permissions and collaboration
19. Frontend model config management（已完成 2026-07-13，見 §17）
20. Secret management
21. Additional subscription model CLI provider presets
22. Subscription model CLI subprocess cancellation and session management
23. Provider-specific CLI output normalization
24. Subscription model CLI compliance review
25. Visual meeting room UI（已完成：沉浸式議事廳 + 法院場景 + 席位系統，2026-07-12）
26. Agent character cards（大致完成：立繪席位 + 角色抽屜；新角色立繪待補）
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
46. Background model health checks（backend startup health projection 已落地）
47. Auto-discover available models from endpoint（已完成：GET /models/{id}/available-models）
48. Performance benchmark
49. Token usage and cost tracking（backend cost estimate foundation 已落地）
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
60. Prompt versioning（backend prompt/schema metadata foundation 已落地）
61. Prompt test harness
62. Prompt library / presets
63. Role-specific output schemas（已完成 2026-07-13：versioned schema registry + per-role selection foundation）
64. Schema migration/versioning（已完成 2026-07-13：舊事件 read-time fallback，不重寫 events）
65. Rich structured verdicts for Judge（已完成 2026-07-13：adjudicator `structured-verdict/v1` + evidence refs）
66. UI i18n
67. Prompt language presets
68. Per-meeting output language setting
69. Full Playwright E2E suite（已落地：31 案例，隨功能持續擴充）
70. Frontend component tests
71. Real provider integration tests
72. Docker Compose setup
73. Containerized deployment
74. Reverse proxy / production hosting guide
75. Meeting reopen endpoint（誤按取消/結案的事件溯源復原：append `reopened` event，終端狀態投影需認得它）（已完成 2026-07-13）
76. 測試 flake：`test_api.py` 的 `wait_for_activity` 2 秒 deadline 在機器負載下偏緊（背景執行緒跑四步偶爾超時；單獨重跑即過）——放寬到 5 秒（已完成 2026-07-13）

> **個人版範圍外（2026-07-13 裁定）**：本工具定位為單人自用，多人/帳號/工作區類項目（18、40–44、50–53）不再排程，保留編號僅供追溯。
77. Slice B 審查遺留（皆 non-blocker）：metadata 的 `mode_id` 指向已從 modes.yaml 移除的模式時 `GET /meetings` 整組 400（單筆髒資料炸全列表）；`"red-blue"` 預設值字面值散落三處可抽 DEFAULT_MODE_ID 常數；create 驗證錯誤碼不對稱（unknown mode 400 vs unknown participant model 404）；NewCaseModal submit 失敗仍關閉 modal（使用者輸入遺失）（已完成 2026-07-13）
78. **案卷（Case Files）Phase 1**：建立會議時附多份文件（貼上/上傳純文字或 markdown，各有標題），**每份可指定可見角色**（法庭：控方證據/辯方書狀/雙方已提交卷宗給法官；紅藍：方案全文；辯論：參考資料；盲測：產品規格）。注入走既有 mode inputs 機制 + prompt 模板 `{{ case_files }}` 佔位符（slice B 的 renderer inputs 注入直接沿用）；全文注入 + 大小上限與 token 成本警告；存放於 meeting data dir（file-based，不建外部索引）。動機：法庭審理的災難覆盤需要事故時間軸/log/設計文件等卷宗，topic 單欄位明顯不足（2026-07-13 使用者提出）（已完成 2026-07-13）
79. **案卷 Phase 2：可追溯檢索與 RAG**。當多份判決、書狀與證據達數十萬字時，不再把全文無差別塞入每次 prompt；同時支援使用者查案與模型按需取證。原始案卷仍是 Source of Truth，檢索結果必須保留證物錨點、文件、原文位置與實際注入紀錄，且在檢索前套用角色可見性，避免把未授權卷宗送入 prompt。分階段交付：**79A** 本地切片索引與全文搜尋 UI（優先採 embedded SQLite FTS/trigram，不新增外部服務）；**79B** 在 runner 前以小型 `retrieve(meeting_id, role_id, query, token_budget)` interface 選取片段，依 token budget 注入並可回到原文；**79C** 僅在真實案件評測證明關鍵字召回不足時加入 embedding 與本地向量索引，採 lexical/vector hybrid ranking，不預設需要獨立向量資料庫。必須測試關鍵證據漏取、引用可追溯性、角色隔離、索引重建與無索引/小案卷相容路徑（2026-07-13 使用者要求提前納入 backlog；尚未核准實作批次）
80. 證據編號引用：案卷文件賦予「證物一/證物二」式編號，prompt 要求角色引用時帶錨點——與 backlog 65（豐富裁決結構）銜接，依賴 78（已完成 2026-07-13）
81. **案卷容量限制設定化與建立前提示**：單份/總量 hard limit 改由環境變數設定，預設提高為 50,000/120,000 字元；後端公開實際限制，New Case 顯示每份與總量、粗估 token/context 風險，超限時 inline 阻擋並保留後端 detail。仍採全文注入，不包含 RAG（已完成 2026-07-13）
82. **每場會議的 LLM attempt 診斷紀錄與檢視器**：補齊 §9 已定義但失敗路徑尚未完整保存的診斷資料。每次模型 attempt 於該 meeting 的 `events.jsonl` 記錄 `model_config_id`、adapter、完整 prompt、可取得的 raw/parsed output、token usage、開始/結束/耗時、結構化 `failure_kind`、error 與是否排定自動 retry；parse/schema failure 必須保存完整失敗 raw output。CLI timeout/exit 可保存最多 8,192 字元且經敏感值遮罩的 stdout/stderr excerpt，不保存 API key、環境變數內容或完整 command。Records Drawer 提供預設摺疊的診斷檢視與複製；舊 events 必須相容。本項不改 retry 次數、timeout 政策、模型選擇或 RAG（已完成 2026-07-14）
83. **每場 meeting 的角色模型指派持久化**：修復目前模型選擇只存在前端記憶體、重整或切換 meeting 後退回第一個可用模型的問題。建立 meeting 時需把 relay 與 parallel 全部 participant 的 `model_config_id` 寫入 metadata；開啟、重整或切換 meeting 時從 participants 還原各自模型，不得跨 meeting 污染；Settings 變更目前 meeting 的角色模型後必須持久化，後續 start/respond/sequence/retry 使用同一份 meeting assignment。模型已刪除或不存在時才 fallback，並提供明確提示。舊 meeting 若 participants 無模型，依各角色最新一筆帶 `model_config_id` 的 event 回復；仍無紀錄才用預設，且不得改寫歷史 events。需以 API 與 Playwright 覆蓋建立→重整、設定→重整、meeting 切換、parallel instances、舊 meeting fallback、刪除模型 fallback（已完成 2026-07-14）
84. **Provider 導引式模型與型號選擇**：修復模型管理 UI 目前只暴露技術性的 `adapter` 名稱與 `model` 自由文字、沒有可選 Provider／模型型號的落差。使用者應先選人類可理解的 Provider（含 custom OpenAI-compatible／subscription CLI），再依 Provider 顯示可用模型與確切型號／版本 ID；可 discovery 時提供載入／重新整理與下拉選擇，不支援 discovery 或需使用新型號時保留手動 model ID。既有 `GET /models/{id}/available-models`（backlog 47）需接入前端，並補 Anthropic/Gemini/CLI 的明確 unsupported/manual UX；角色模型下拉與模型列表應顯示 Provider + 模型型號，而不只 config id。不得把 API key 值送到或保存在前端。需覆蓋 discovery 成功、失敗、空清單、手動 fallback、編輯既有 config 與舊設定相容（已完成 2026-07-14）
85. **Provider 與模型設定 UX 強化**：在 #84 基礎上補齊 Anthropic、Gemini provider-specific model discovery；成功時提供可搜尋／重新整理的 exact model ID 下拉，失敗、空清單或新型號未列出時保留手動輸入。Subscription CLI 改為導引式 preset：先選 Claude CLI、Codex CLI、AGY 或 Custom CLI，preset 預設使用 CLI 自動選擇模型並由後端／domain module 產生安全 argv，使用者不需手打 executable、子命令或 `{prompt}`；進階模式才允許 exact model ID 或 custom command，且既有 `models.yaml` command 必須相容。Human Owner 驗證並於 2026-07-14 核准的 exact argv contract 為：Claude `claude --model <id> -p {prompt}`、Codex `codex exec --model <id> {prompt}`、AGY `agy --model <id> -p {prompt}`；每個 preset 必須自行擁有 argv builder，不得假設不同 CLI 共用旗標位置。模型「測試連線」期間顯示 spinner 與進度文字、停用重複提交；慢速時提示仍在等待，完成後顯示成功／失敗，切換模型、關閉表單或重啟測試後不得讓過期回應污染目前畫面。不得在儲存或 discovery 時發出付費 completion；不得保存 API key 明文。需以 backend API、frontend unit 與 Playwright 覆蓋 discovery headers/response normalization/error fallback、CLI preset/legacy round-trip、loading/slow/stale response 與舊設定相容（已完成 2026-07-14）
86. **會議名稱／AI 目標契約、中文呈現與定向追問 UX**：meeting 必須把給人識別的 `title` 與提供給 AI 的最終 `goal` 分開，兩者於新建時皆必填；列表、頂欄、搜尋、複製與下載逐字稿使用 `title`，所有角色 prompt 只以 `goal` 作為任務目標。不得接受新建時只送舊 `topic` 的相容契約。舊 meeting 僅有 `topic` 時視為待遷移：讀取可將舊值呈現為待確認的 `title`，但不得把它當 `goal`；使用者保存 title + goal 前，start、retry、指定角色回應與角色序列皆須拒絕，保存後 metadata 改為新欄位並移除 `topic`，不得改寫歷史 events。主要會議流程的固定 UI 文案、角色名稱、步驟名稱、輸出區塊與 decision 顯示須使用繁體中文；內部 role/step/schema/model/provider ID 保持不變，只能在診斷／進階資訊顯示。頂欄顯示 title，不常駐 meeting ID；複製案件資訊需同時包含 title 與 ID。`POST /meetings/{id}/roles/{role}/respond` 必須接收非空白 `instruction`，保存具 `target_role_id` 的 Human 定向指示，使用共用定向回應 prompt 回答該指示，不得重跑該角色原本的 phase template；回應事件需可追溯至指示事件。需以 backend API/runner、frontend unit 與 Playwright 覆蓋新建契約、舊 meeting gate/遷移、prompt 只使用 goal、中文 label/step/output、複製內容、空白 instruction 拒絕及角色針對明確問題回應。不得批次或靜默回填現有 meeting/events；遷移只在使用者明確保存單一 meeting 時發生。（已完成 2026-07-14）
87. **主席操作整合、會議資訊編輯與逐一爭點法院流程**：主席是 meeting 的 Human 操作者；主要輸入區必須以單一下拉明確區分「記錄補充（不呼叫 AI）」、「請全體回應」及「請指定角色回答」，送出按鈕、placeholder 與完成提示須描述實際效果，不得把指定角色追問藏成另一套不易發現的主要流程。指定角色選項只列出 mode/backend 明確支援定向回應的 active roles；parallel mode 不得顯示會導致 400 的假選項，且本批次不擴張 parallel directed runner。meeting 建立後需能從 title 附近編輯 `title` 與 `goal`；執行中不得修改，修改 title 只改識別，已有 AI events 後修改 goal 必須確認、只影響後續 prompt、保存 Human audit event且不改寫歷史。courtroom 的爭點確認前可修改 goal；確認後 goal 唯讀且不得建立隱含新版爭點，title 在非執行中仍可修改。上方入口命名為「系統設定」；底部齒輪不得再偽裝成第二個設定，改為語意明確的「流程操作」。移除依任意 event 數量顯示的模糊「繼續討論」：按鈕必須顯示將執行的確切動作與下一角色；完成一輪後不得暗中執行目前 sequence preset。

    法院模式改為 issue-driven workflow。AI 可依 meeting `goal`、可見案卷與既有逐字稿產生爭點清單草稿，但不得自動確認；主席必須能新增、修改、刪除、排序並明確確認。可編修爭點定義保存在 meeting metadata，確認後的攻防與裁判結果保存為 append-only events。每次只處理一個 current issue：檢察官主張 → 辯護律師答辯 → 檢察官反駁，然後停下供主席補充或定向追問；只有主席按「送交爭點裁定」才呼叫法官。逐點裁定 outcome 至少支援主張方勝、答辯方勝、部分成立、證據不足，並保存理由、證據引用與未解問題。裁定後必須停止，由主席手動進入下一爭點；全部已確認爭點都有 completed ruling 後，才允許法官作成綜合全部爭點的最終判決。舊 courtroom meeting 不改寫既有 metadata/events，但下一次法院執行前同樣必須建立並確認爭點，不得再走舊的一鍵全案流程。非 courtroom modes 保持既有 runner 行為。需以 HTTP/runner tests、frontend unit、Playwright 與 direct browser smoke 覆蓋 draft/CRUD/reorder/confirm、非法狀態拒絕、逐點停頓、主席追問、逐點裁定、手動 next、final gate、重整恢復、舊 courtroom gate、統一主席 composer、title/goal edit audit 與精確流程文案。（2026-07-14 Human Owner 核准；已完成 2026-07-15，`implemented / awaiting acceptance`）
88. **審議生命週期、案卷版本與民刑事法院體驗重整**：所有 meeting mode 必須支援「重開審議」，在不複製或刪除案卷證據的前提下，將上一輪主席發言、AI 回應、失敗診斷與流程進度 append-only 封存，新一輪 prompt 不得讀取封存討論。重開必須選擇或填寫原因，只允許在非執行中、非結案狀態使用；結案 meeting 需先重新開啟。議事紀錄依審議輪次分組，預設只顯示目前輪，可查看或下載舊輪，但封存記錄不可 retry/edit 也不可污染 live meeting projection。法院另支援「重開目前爭點」、「重開全部審議」、「重新整理爭點」三層操作；前者保留其他爭點已完成判斷但使 final verdict 失效，中者保留 confirmed docket 並清除全部進度，後者封存 docket 並重新開放 AI 目標與案件類型編輯。舊 events 不得重寫，新 epoch 的 event identity 必須唯一，current-issue reset 必須正確保留非目標爭點的 carry-forward 結果，不得只以「最新 marker 之後」作為單純 suffix filter。

    案卷與證據必須成為 meeting-scoped 的可管理資源：證物 ID、編號與 citation anchor 終身穩定且不重用；title、content 或可見角色變更以新版本保存，停用只影響後續 prompt，不刪除歷史。案件備註與證物同樣版本化、可指定角色可見，普通主席發言只屬於當輪，只有主席明確「轉為案件備註」才跨輪保留。已有 AI output 後新增、換版、停用或重啟會進入 prompt 的資料，必須標記證據已變更並拒絕繼續 AI/法官判斷，直到主席選擇重開目前爭點、全部審議或重新整理爭點。舊格式案卷只在 read-time 相容，第一次明示修改才升級版本，不批次回填。

    Courtroom 新 meeting 建立時必須由使用者選擇 `civil` 或 `criminal`，舊 courtroom meeting 在下次執行前也必須明示選擇，不得由 AI 、title 或 goal 自動推論。案件類型在爭點確認前可改，變更會使未確認 docket 失效；確認後與 goal 一併鎖定，只有「重新整理爭點」才重新開放。internal role IDs 維持穩定，但民事顯示為原告代理人／被告代理人／法官，刑事顯示為檢察官／辯護人／法官。兩類爭點草稿都由法官模型中立產生、主席確認；固定三段攻防為主張方陳述 → 答辯方答辯 → 主張方限縮反駁，第三段不得新增主張或證據，之後必須停下，由主席決定是否追問答辯方，並手動按「請法官判斷此爭點」；不可自動判斷。單一爭點的產出稱「法官對此爭點的判斷」，只有全案結果稱「最終判決」；結果文案依民事／刑事投影，後端保持一致的中立 issue outcome IDs。最終判決採 case-specific versioned schema：刑事只判斷罪責與量刑考量，不產生具體刑期、罰金或刑罰；民事只能使用案卷中已有金額與計算基礎，每個金額必須有非空證據引用，證據不足時不得自行估算。

    UI 必須把 scope 拆清：全域「系統設定」只管 Provider、模型設定／健康與「進階功能 → 顯示事件原始資料」（預設關閉、不影響 AI）；meeting 次導覽提供「會議設定」、「案卷與證據（數量）」、「議事紀錄」，「流程操作」只放重開、重新整理爭點、序列、取消、結案與重新開啟。會議設定使用右側 drawer，統一編輯 title、goal、case type、scene 與完整角色模型，全部先留在 local draft，最後以單一原子儲存 interface 一次驗證與寫入；執行中禁止，dirty close 要求確認，鎖定欄位顯示原因。等待法官時，目前爭點卡必須顯示「攻防已完成，等待主席送交法官；不會自動判斷」與 sticky 主按鈕「請法官判斷此爭點」。設定、重開、證據變更、歷史輪次、民刑事全流程、375px layout 及 reload/switch isolation 需有 HTTP、frontend unit、Playwright 與真瀏覽器覆蓋。

    **Acceptance 修補（2026-07-16 Human Owner 核准）**：舊 courtroom 缺少案件類型時，不得在爭點審理區另放一套 case-type 表單；該區只顯示阻擋原因與「前往會議設定」，案件類型仍由 meeting settings drawer 的 atomic interface 一次儲存。Courtroom 主席 composer 不得顯示語意不實的「請全體回應」；正式流程只能由獨立主 CTA 推進，composer 僅提供記錄補充與 backend 允許的指定角色補充，且指定回應必須明示不會裁定或推進流程。等待裁定時，完整爭點名稱只顯示在焦點卡，sticky CTA 縮短為「送交法官判斷」，旁邊說明按下後才呼叫法官；法官完成後改為「進入下一爭點」，全部爭點完成後才顯示最終判決。Activity idle 不得顯示為「已完成」而誤認案件完成；法院狀態需依 workflow 投影為「待補案件設定／待主席開始攻防／攻防完成，待主席送交法官／待主席進入下一爭點／待主席作成最終判決」等可操作狀態。（原批次 2026-07-15 核准、2026-07-16 初次實作；acceptance 修補已完成 2026-07-16，Human Owner 於 2026-07-17 驗收通過，`accepted / done`）
89. **法院非同步完成後偶發卡在無可用下一步**：在法院 arguments／ruling／final job 已寫入 completed events 後，前端偶發取得 `courtroom.available_actions=[]` 並長時間顯示「請先完成目前爭點的必要步驟」，直到 reload 才恢復。需釐清 WebSocket completion、backend job reservation release、`live_activity_status` 與 `refreshMeetingUntilSettled()` 的 ordering，建立能控制 release 時序的 deterministic integration test；前端不得把 job 尚未 release 的中間 projection 當成 settled。2026-07-16 於 #88 acceptance gate 發現：feature 完整 Chromium 兩次各 89/90、失敗落在不同 courtroom transition；main 固定點相同壓力測試 10 次重現 4 次，證明不是 #88 acceptance 修補 regression。（2026-07-17 Human Owner 核准並驗收通過；`accepted / done`）
90. **會議工作區與時間序對話介面重整**：目前沉浸式場景佔據主要畫面，角色發言位於下方卡片，使用者需反覆捲動才能確認誰先說、誰後說；主席操作也與逐字稿分離，造成「開始新回合／請全體回應」重複且難以理解。一般接力與平行模式統一改用同一個 Conversation workspace：左側為極窄、可收合的角色狀態列，中間依事件實際保存順序呈現主席與 AI 的時間序對話，右側為可收合的會議脈絡／進度。長回應預設收合並可展開；點角色可篩選並跳至該角色最近發言；原場景與角色形象保留為次要、可收合的狀態視圖，不再主導閱讀。主席輸入與對話同區，`+` 只開啟既有版本化「案卷與證據」流程，不建立另一套訊息附件契約；能力與文案必須精確反映 backend，移除沒有新指示卻重跑同一目標的重複按鈕。relay 與 parallel 只差執行語意，不分裂 UI：parallel 全員以同一份 fanout 前 transcript 同時開始，誰先完成就立即按完成順序保存並顯示，較晚完成者不可讀取同輪較早完成者輸出；全部完成後才由彙整者加入最後訊息，失敗、retry、cancel 與 synthesis gate 維持既有契約。法院使用同一 workspace shell 但採 Court Hearing presentation：中央依爭點與攻防階段分組，右側放 backend `available_actions` 所決定的正式 CTA，不把法院事件偽裝成自由聊天，也不由 composer 推進裁判流程。法院案件名稱只在全域頂欄呈現，不在中央紀錄重複占用垂直空間；桌面版中央紀錄必須獨立滾動，滾動長篇庭審內容時左右角色列與正式流程仍留在工作區內可見。需以 deterministic backend tests 證明 parallel arrival-order persistence、partial live visibility、frozen context 與 synthesis gating；frontend pure projection/unit tests固定 Conversation／Court Hearing presentation、時間序、角色篩選、長文收合與 mode isolation；Playwright 覆蓋 relay、parallel reload、法院逐點流程與 375px responsive。不得重寫歷史 events、不得新增 free-form chat mode、不得擴張 parallel 指定角色回應能力。（2026-07-18 Human Owner 核准並完成；驗收發現法院中央重複標頭與整頁滾動，修補中；`implemented / acceptance fix in progress`）
91. **無流程限制的 AI 聊天室模式**：建立 meeting 時只需聊天室名稱，不強制 AI 最終目標或固定 round／sequence；主席訊息是對話的驅動來源，可用 `@角色` 指定一位、`@all` 同時邀請全部角色，並可引用另一位角色的發言請大家評論。回應應採一般聊天的精簡篇幅，而非每位角色預設輸出長篇正式報告。附件與長期資料仍需沿用版本化案卷／證據契約，不得另存 API key 或建立不可追溯的臨時附件。需先釐清 mention parsing、parallel directed fanout、對話 context/token budget、回應長度政策與自由聊天是否需要可選 goal；本項是 #90 完成後的獨立產品批次，尚未核准實作。

## 16. 會議模式系統（Mode System）設計

> 狀態：設計定稿（2026-07-12），分四個切片實作。切片 A 為前端先行，切片 B/C/D 為後端（Codex 依本節實作）。

### 16.1 目標與原則

支援多種會議模式（mode）。核心原則：

1. **模式是宣告式設定，不是程式碼。** 一個 mode = 角色清單 + 拓撲 + prompt 模板引用 + 使用指引 + 預設場景。新增模式 = 新增設定與 prompt 檔，不改執行器。
2. **只有兩種執行器。** `relay`（回合接力，深度驗證）與 `parallel`（平行扇出 + 彙整，廣度探索）。六個初始模式全部落在這兩種之上。
3. **事件模型不變。** `events.jsonl` 的 `role` 本來就是字串、`base_step_id`/`round` 機制沿用；既有會議（無 `mode_id`）一律視為 `red-blue`，完全向後相容。
4. **共用 output schema 不變**（第 8 節）。角色差異由 prompt 控制；豐富化裁決結構仍屬 backlog 65。

### 16.2 Mode 定義 Schema

檔案：`config/modes.yaml`（與 `models.yaml` 同慣例）。欄位：

```yaml
modes:
  - id: red-blue                # 唯一識別
    name: 紅藍對抗
    category: relay             # relay | parallel
    tagline: 一句話賣點（前端模式卡顯示）
    when_to_use: 什麼情境該用這個模式（前端指引）
    sop:                        # 操作 SOP，前端逐步顯示
      - 輸入要被驗證的方案主題
      - 為藍軍/紅軍/裁判挑選模型
      - 開始審議，觀察紅軍指出的缺陷
      - 對裁決不滿可追問或開新回合
    default_scene: meeting-room # 前端場景對應
    inputs: []                  # 除 topic 外的額外建立參數（見 16.4）
    roles:
      - id: Blue                # 進 events.jsonl 的 role 字串
        name: 藍軍
        color: "#4D8DFF"
        portrait: blue          # 前端立繪 key，無對應美術時用剪影
        kind: member            # member | adjudicator | synthesizer
    steps:                      # relay 專用：接力步驟
      - { role: Blue, template: blue_propose }
      - { role: Red, template: red_critique }
      - { role: Blue, template: blue_revise }
      - { role: Judge, template: judge_decide }
    # parallel 專用（與 steps 二擇一）：
    # fanout:
    #   role: Member            # 扇出角色原型
    #   template: brainstorm_member
    #   min_instances: 2
    #   max_instances: 6
    #   instance_prompt: optional   # 允許每個實例附加自訂視角/persona
    # synthesis:
    #   role: Moderator
    #   template: brainstorm_synthesis
```

平行模式的成員是「角色原型的實例」：`member-1`…`member-N`，每個實例各自綁 model config、可附加實例級 prompt（persona / 思考帽視角）。實例的 role 字串進事件時用 `Member-1` 形式，顯示名稱由 participants 記錄。

### 16.3 兩種執行器

**relay（接力）**：現行 `MeetingRunner` STEPS 的參數化。step_id 沿用 `{template}`/`round-N-{template}` 慣例；失敗中止批次、retry 從失敗步驟續跑到結尾、round 計數依「最後一個 step 完成次數」推進 —— 全部既有語意不變，只是步驟序列來自 mode 設定。

**parallel（平行）**：新執行器。
- 扇出階段：所有成員實例併發呼叫（asyncio gather），step_id `fanout-{round}-member-{k}`。individual 失敗不中止其他成員；全部結束後若有失敗，進入 `waiting`，成員可單獨 retry。
- 彙整階段：所有成員成功（或使用者明示跳過失敗成員）後觸發，step_id `synthesis-{round}`。彙整 prompt 收到全部成員輸出。
- 匿名化（backlog 13 / 方向五）掛在彙整輸入組裝點：成員輸出洗牌、以「委員A/B/C」代稱、字串層過濾自我指認（如「身為 ChatGPT」）。第一版平行執行器即預留此 hook，預設關閉，per-mode 設定開啟。

### 16.4 六個初始模式

| id | 類別 | 角色 | 拓撲 | 額外 inputs | 預設場景 |
|----|------|------|------|-------------|----------|
| `red-blue` 紅藍對抗 | relay | 藍軍/紅軍/裁判 | propose→critique→revise→decide | — | meeting-room |
| `courtroom` 法庭審理 | relay | 檢察官/辯護律師/法官 | 指控→辯護→再質詢→判決 | — | courtroom |
| `debate` 辯論 | relay | 正方/反方/仲裁人 | 正申論→反申論→正質詢→反質詢→裁決 | `position_a`、`position_b` | meeting-room |
| `brainstorm` 腦力激盪 | parallel | 委員×N（2–6）/主持彙整 | 扇出→彙整（共識/分歧/結論） | 每委員可選自訂視角 | meeting-room |
| `six-hats` 六頂思考帽 | parallel | 白/紅/黑/黃/綠帽×5（固定）/藍帽統整 | 扇出→藍帽彙整 | — | meeting-room |
| `persona-testing` 盲測用戶 | parallel | 使用者定義 persona×N/產品顧問彙整 | 扇出反應→彙整報告 | `personas[]`（名稱+描述） | meeting-room |

法庭審理定位：災難覆盤與複雜架構除錯（topic = 被審理的事故/設計）。辯論的兩條路線由 `position_a/b` 注入雙方 prompt。六帽採經典分工：白=事實數據、紅=直覺感受、黑=風險批判、黃=價值樂觀、綠=創意發想、藍=流程統整（藍帽即彙整者）。

新增 prompt 檔（`prompts/`）：courtroom_charge / courtroom_defense / courtroom_rebuttal / courtroom_verdict、debate_statement_pro / debate_statement_con / debate_cross_pro / debate_cross_con / debate_verdict、brainstorm_member / brainstorm_synthesis、hat_white / hat_red / hat_black / hat_yellow / hat_green / hat_blue_synthesis、persona_member / persona_synthesis。

### 16.5 API 變更

```text
GET  /modes                       # mode catalog：完整 16.2 結構（前端指引資料來源）
POST /meetings                    # body 新增 mode_id（預設 red-blue）、
                                  # participants: [{role_id 或 instance slot, model_config_id,
                                  #                display_name?, instance_prompt?}]、
                                  # inputs: {position_a?, position_b?, personas?...}
GET  /meetings/{id}               # read model 投影 mode_id 與 participants
POST /meetings/{id}/roles/{role}/respond   # role 接受該 mode 的任意 role/instance id
POST /meetings/{id}/sequences              # roles 陣列同上
```

無 `mode_id` 的舊會議投影為 `red-blue` + 現行三角色 participants。

### 16.6 前端要求

- **席位動態化**：移除寫死的 `CouncilRole` union；席位、pendingRoles、抽屜、事件歸戶全部改由 meeting 的 participants 驅動（角色數 3–7 不等）。顏色/立繪來自 mode 定義，無立繪的新角色用角色色剪影 placeholder。
- **場景席位槽**：`SceneConfig.seats` 由固定四鍵改為槽位群組：`adjudicator`（上）、`chair`（下）、`podium[]`（左右講位）、`ring[]`（環繞席，供平行模式 N 成員）。mode 的角色 `kind` + 位置慣例對應到槽位群組；同群組多實例時均分排列。
- **建立會議流程（模式選擇器）**：New Case 改為兩步 —— (1) 模式卡片牆：名稱、類別徽章（回合制/平行）、tagline、「適合情境」、可展開 SOP；(2) 參與者設定：角色→模型對應、平行模式的成員增減（min/max 來自 mode）、persona/視角編輯、辯論的雙立場輸入。
- **會議中指引**：接力模式顯示步驟進度（「第 2 步／共 4 步：紅軍質詢中」，資料來自 mode.steps 與 pendingRoles）；平行模式顯示「N 位委員思考中（k/N 完成）→ 等待彙整」。頂欄常駐「?」按鈕開模式說明抽屜（tagline/when_to_use/SOP，同一份 catalog 資料）。
- **指引資料來源**：`GET /modes`；後端未上線前，前端內建同 schema 的本地 catalog 常數（切片 A 用），後端上線後切換資料來源、本地常數轉為 fallback。

### 16.7 實作切片

- **切片 A（前端先行，不依賴後端）**：席位動態化重構 + 場景席位槽 + 本地 mode catalog + New Case 模式選擇器與指引 UI。六模式卡片全部可瀏覽（含 SOP），但僅 `red-blue` 可建立，其餘標示「即將推出」。既有功能與 e2e 全數保留。
- **切片 B（後端）**：`config/modes.yaml` + `GET /modes` + relay 執行器參數化 + `POST /meetings` 收 mode_id/participants/inputs → `courtroom`、`debate` 上線。——已完成（2026-07-13）
- **切片 C（後端）**：parallel 執行器（含 per-member retry 與 synthesis gating）→ `brainstorm` 上線；`six-hats`、`persona-testing` 為純設定追加。——已完成（2026-07-13）
- **切片 D（後端）**：彙整匿名化 hook 啟用（方向五）。——已完成（2026-07-13）
- **美術（使用者產圖，隨切片 B/C 進度）**：檢察官/辯護律師/仲裁人立繪、六帽委員立繪、persona 通用立繪；辯論場景（可選，預設沿用議事廳）。

## 17. 前端模型設定管理（Model Config Management）設計

> 狀態：設計定稿（2026-07-12）。後端（Codex）先行，前端 UI 隨後接上。對應 backlog 19，取代「只能手動編輯 `config/models.yaml`」的現況。——已完成（2026-07-13）

### 17.1 原則

1. **`config/models.yaml` 仍是唯一真相來源。** API 寫入即改寫該檔（原子替換：寫 temp 檔 + rename），人工手動編輯仍然有效，兩者互通。保留檔內註解不是需求（YAML round-trip 允許丟失註解）。
2. **絕不經手金鑰明文。** UI 與 API 只接受 `api_key_env`（環境變數「名稱」）。表單需明確標示「此欄位填環境變數名稱，非 API 金鑰本身」。原因：專案位於雲端同步資料夾（Synology Drive），金鑰明文落檔等於外洩。金鑰保存屬 backlog 20（Secret management），不在本設計範圍。
3. 後端為單一 process（第 10 節），read-modify-write 無需跨程序鎖；同 process 內以單一寫入路徑序列化。

### 17.2 API

```text
POST   /models                # 新增 model config
PUT    /models/{id}           # 更新（id 不可改）
DELETE /models/{id}
```

- 欄位同第 6 節 schema：`id`、`adapter`、`base_url`、`model`、`api_key_env`、`supports_json_mode`、`extra_body`、`command`、`timeout_seconds`
- 驗證：`id` 唯一且符合 `^[A-Za-z0-9][A-Za-z0-9_.-]*$`；`adapter` 限 `SUPPORTED_ADAPTERS`（`backend/ai_council/models/config.py`，以程式碼為準；截至本節完成時為 `mock | openai-compatible-http | anthropic-http | gemini-http | subscription-cli` 五種）；`openai-compatible-http`/`anthropic-http`/`gemini-http` 三個 http 系 adapter 皆必填 `base_url` + `model`；`subscription-cli` 必填 `command`。驗證失敗回 `422` 與逐欄錯誤
- 新增/更新後該 model `status` 重設為 `unknown`（使用者可按 Test）
- `DELETE`：一律允許（歷史事件記錄的是 id 字串，不受影響；進行中的呼叫已持有設定物件）。回應為 `200` + JSON body `{"id", "warning"}`；若該 id 正被任一 open meeting 的最近選擇引用，`warning` 為說明字串，否則為 `null`
- 執行中的 meeting run 不受寫入影響：runner 在 start 時已解析設定

### 17.3 前端 UI

Settings 彈窗新增「模型管理」分頁（與既有「角色模型選擇/場景/開發者模式」並列）：

- 模型列表：id、adapter、base_url/model 摘要、status dot、Test 按鈕（沿用既有）、編輯/刪除按鈕
- 新增/編輯表單：依 adapter 動態顯示欄位（mock 無額外欄位；http 顯示 base_url/model/api_key_env/supports_json_mode/timeout；cli 顯示 command/timeout）；`api_key_env` 欄位下方固定顯示金鑰安全說明
- 刪除需 `window.confirm`；被引用中的模型刪除時顯示後端回傳的 warning
- 寫入成功後重抓 `GET /models`，角色選擇下拉即時更新；若被刪除的模型正被某角色選中，該角色 fallback 到清單第一個模型（沿用既有 fallback 行為）
- testid：`model-manager-tab`、`model-manager-list`、`add-model-button`、`model-form`、`model-form-save`、`delete-model-button`

### 17.4 測試

- 後端：CRUD 往返（寫檔後重讀）、驗證錯誤 422、原子替換（寫入失敗不留半成品檔）、刪除被引用模型的 warning
- 前端 e2e：新增模型 → 出現在角色下拉 → Test → 編輯 → 刪除（含 confirm 與 fallback）
