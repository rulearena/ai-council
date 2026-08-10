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
90. **會議工作區與時間序對話介面重整**：目前沉浸式場景佔據主要畫面，角色發言位於下方卡片，使用者需反覆捲動才能確認誰先說、誰後說；主席操作也與逐字稿分離，造成「開始新回合／請全體回應」重複且難以理解。一般接力與平行模式統一改用同一個 Conversation workspace：左側為極窄、可收合的角色狀態列，中間依事件實際保存順序呈現主席與 AI 的時間序對話，右側為可收合的會議脈絡／進度。長回應預設收合並可展開；點角色可篩選並跳至該角色最近發言；原場景與角色形象保留為次要、可收合的狀態視圖，不再主導閱讀。主席輸入與對話同區，`+` 只開啟既有版本化「案卷與證據」流程，不建立另一套訊息附件契約；能力與文案必須精確反映 backend，移除沒有新指示卻重跑同一目標的重複按鈕。relay 與 parallel 只差執行語意，不分裂 UI：parallel 全員以同一份 fanout 前 transcript 同時開始，誰先完成就立即按完成順序保存並顯示，較晚完成者不可讀取同輪較早完成者輸出；全部完成後才由彙整者加入最後訊息，失敗、retry、cancel 與 synthesis gate 維持既有契約。法院使用同一 workspace shell 但採 Court Hearing presentation：中央依爭點與攻防階段分組，右側放 backend `available_actions` 所決定的正式 CTA，不把法院事件偽裝成自由聊天，也不由 composer 推進裁判流程。法院案件名稱只在全域頂欄呈現，不在中央紀錄重複占用垂直空間；桌面版中央紀錄必須獨立滾動，滾動長篇庭審內容時左右角色列與正式流程仍留在工作區內可見。需以 deterministic backend tests 證明 parallel arrival-order persistence、partial live visibility、frozen context 與 synthesis gating；frontend pure projection/unit tests固定 Conversation／Court Hearing presentation、時間序、角色篩選、長文收合與 mode isolation；Playwright 覆蓋 relay、parallel reload、法院逐點流程與 375px responsive。不得重寫歷史 events、不得新增 free-form chat mode、不得擴張 parallel 指定角色回應能力。（2026-07-18 Human Owner 核准並完成；2026-07-19 完成法院重複標頭／中央獨立滾動 acceptance 修補並通過雙軸 review 與完整 gates；2026-07-20 Human Owner 驗收通過；`accepted / done`）
91. **無流程限制的 AI 聊天室模式**：建立 meeting 時只需聊天室名稱，不強制 AI 最終目標或固定 round／sequence；主席訊息是對話的驅動來源，可用 `@角色` 指定一位、`@all` 同時邀請全部角色，並可引用另一位角色的發言請大家評論。回應應採一般聊天的精簡篇幅，而非每位角色預設輸出長篇正式報告。附件與長期資料仍需沿用版本化案卷／證據契約，不得另存 API key 或建立不可追溯的臨時附件。需先釐清 mention parsing、parallel directed fanout、對話 context/token budget、回應長度政策與自由聊天是否需要可選 goal；本項是 #90 完成後的獨立產品批次。**Gate A 通過後實作**：Codex Gate A review 通過後完成全部 implementation task groups。650 backend / 99 frontend unit / 105 e2e 全數通過；direct Chromium smoke 通過。已完成 2026-07-21，`implemented / awaiting acceptance`；2026-07-23 Human Owner 驗收發現 UX 問題（見 backlog 92），視為原需求尚未完成，進入修正循環，`implemented / acceptance rejected — see #92`；2026-07-31 依 #92 完成全部驗收回饋並經 Human Owner 最終驗收通過，本需求完成，`accepted / done`（2026-07-31）。
92. **聊天室工作區 UX 精修（#91 驗收回饋）**：Human Owner 於 2026-07-23 驗收 #91 聊天室模式時發現九項 UX 問題：角色列座位互動不一致（Chairman 座位點擊開詳情抽屜、其他角色座位點擊做訊息篩選）、篩選開關不對稱（左側角色座位觸發篩選、清除篩選的「顯示全部發言」按鈕卻在對話標題列右側）、角色名稱／數量／頭像寫死於 mode 設定（此項另立 backlog 93，本項不含）、換模型入口藏在頂欄「會議設定」抽屜、聊天訊息卡片無頭像（僅顏色框＋文字名稱）、頂欄「會議設定／案卷與證據／議事紀錄」三按鈕與既有入口（composer `+`／ActionBar）重複、訊息串滑鼠滾輪疑似無法捲動（靜態 CSS 檢視 `min-height:0`／`overflow-y:auto` 鏈已具備，需實機重現定位根因）、角色場景圖無法點擊放大、新增會議模式選單聊天室排在最後（`config/modes.yaml` 檔案順序決定前端呈現順序）。本項處理除角色自訂外的八項：座位主要點擊行為於 Chairman 與一般角色間統一（詳情視圖改為座位內次要控制）；篩選改為同一座位可切換開關並顯示篩選中狀態，標題列按鈕保留為次要清除入口；訊息卡片加入頭像；`config/modes.yaml` 聊天室移至第一筆；場景圖加入點擊放大；換模型控制移入角色列座位（沿用既有 `updateSelectedModel`／`testSelectedModel`，`MeetingSettingsDrawer` 移除該區塊）；議事紀錄併入右側會議脈絡欄分頁、頂欄冗餘按鈕（會議設定／案卷與證據／議事紀錄）移除，會議設定改為標題旁鉛筆圖示；訊息串滾輪捲動失效需先實機重現再定案修法。純前端 + `config/modes.yaml` 排序調整，不動後端 API、事件結構或聊天室執行語意（`@角色`／`@all`／token budget 不變）。OpenSpec change：`chatroom-ux-polish`。Gate A 通過（`2dc55e9`，一項 Minor：MODIFIED spec 需保留「顯示全部發言」清除篩選並捲到最新訊息的語意，已修正）。Gate B 歷經 7 輪 review-fix 循環（最終 fixed range `2dc55e9...f7065a9`）：round 1 修正 app crash／破損 e2e selector／死碼／假測試；round 2 修正法院模式失去換模型能力／滾動根因未確診／新增修復自己弄壞 e2e／CouncilStage 場景冒泡 regression；round 3 修正法院模式紀錄入口缺失；round 4 修正案卷數量顯示消失；round 5 用獨立 mutation test 證實 auto-scroll 從未真正生效並修正根因、同時發現並修正移除舊 UI 時連帶弄丟的模型失效警告與存檔死路；round 6 修正 ≤640px 窄視窗完全無法換模型、警告文案中英夾雜、換模型失敗無提示、鍵盤操作意外改變篩選；round 7 修正上一輪新增測試本身空洞的問題（改用 mutation test 與 Vue store 直接操控驗證）。最終 Gate B `pass`（無 Blocking/Major），650 backend／116 frontend unit／118 e2e／build 全綠，Orchestrator 已 fast-forward merge 至 main（`f7065a9`）並重跑 post-merge checks（650／116／build 全綠）確認一致。已完成 2026-07-28，`implemented / awaiting acceptance`。**2026-07-30 第二輪驗收修正**（Human Owner 指出「只有第 9 點有做到」後）：app-shell 視窗高度上限、座位語意與模型控制、脈絡欄收合回收空間、紀錄密度、mode 感知的案卷用語、LINE 式訊息版面、訊息串開在最新處並跟隨自己送出、聊天室換模型 500、思考氣泡、中文選字被 Enter 送出、提及選單鍵盤操作（見 backlog 95）。同日再依 Human Owner 指示補完兩項：①composer `+` 由側邊抽屜改為置中彈出視窗（元件更名 `CaseMaterialsDrawer`→`CaseMaterialsModal`、testid `case-materials-drawer`→`case-materials-modal`；沿用既有 `Modal.vue`，法院模式一併改變）；②法院模式套用同一套座位契約（座位改為真正的 `<button>`、主席座位行為與其他座位一致改為篩選、新增 ℹ 詳情控制與具可視提示的模型控制）並補上場景點擊放大。**已知限制**：法院場景正中央為座位（座位帶 `@click.stop`），該處點擊只會選取角色而不會放大，空白處才會放大；聊天室因中央恰為桌面而無此現象。此為分層行為非失效，但「點擊放大」在法院模式可發現性不佳，是否改為明確的放大按鈕待 Human Owner 決定。新增 e2e 13.26（彈出視窗置中且非全高、聊天室用語為附件而非證物）與 court hearing seat parity（座位皆為 `<button>`、主席與角色座位篩選行為對稱、ℹ 不改變篩選、場景可放大），兩者變異測試皆紅。125 e2e／116 unit／653 backend／build 全綠。**2026-07-31 Gate B 通過並 merge**：獨立 Reviewer 審查 `chatroom-ux-round2`（fixed base `2ee4147`，HEAD `ebc49f2`，13 commits／16 files）逐行通過 Spec 與 Quality 雙軸，Verdict `pass`（無 Blocking/Major），並獨立驗證 653 backend／116 unit／build／125 e2e 與基線一致。Orchestrator 已 fast-forward merge exact reviewed HEAD 至 main（`ebc49f2`）並重跑 post-merge checks（653／116／build 全綠）確認一致，狀態維持 `implemented / awaiting acceptance`。審查 Minor 裁定：HANDOFF commit 計數文字誤差（修正於 HANDOFF）；`.meeting-goal-migration` z-index 防護屬同批布局改動附隨（補記於此，非未授權 scope creep）；`MentionAutocomplete.vue` `activeIndex` 未隨過濾收斂（`aria-activedescendant` 可能指向不存在的 option，下一方向鍵自癒）與 `ChatroomComposer` 組字中點「送出」可能遺失未 commit 候選字（與 base 同軌，非本批 regression）兩項 Minor 記入 backlog 94。**已知限制**：①「附件」用語在聊天室指純文字資料卡、無檔案上傳，Human Owner 已裁定於 backlog 96 交付 LINE 式檔案附件；②法院場景點擊放大可發現性問題如上。**2026-07-31 驗收中發現「+」無檔案上傳（見 backlog 96）。** 2026-07-31 Human Owner 完成最終驗收，本需求通過，`accepted / done`（2026-07-31）。#91 與 #92 的 delta specs 已於同一次 closeout 一併 sync 進 `openspec/specs/` 並 archive（`openspec/changes/archive/2026-07-31-<name>`）。
93. **每場會議可自訂角色名稱／數量／頭像／Persona**：目前角色名單（名稱、數量、色彩、立繪）由 `config/modes.yaml` 依所選 mode 固定，使用者無法在建立會議時自訂。Human Owner 於 #91 驗收（見 backlog 92）時提出，明確裁定本次不做、記錄進 backlog。2026-08-09 Human Owner 進一步確認：聊天室未來可建立使用者自訂角色，讓使用者定義角色名稱、Persona prompt 與模型，但自訂 Persona 只屬於 `user/context` 層，不得覆寫 system／developer 的安全、`@`／`#` 路由、來源授權或輸出契約；此能力應與 #103 的固定五角色分開開發。範圍與設計仍待後續需求討論（含自訂角色是新增或取代、數量／prompt 長度限制、角色改名／刪除與歷史訊息、`@all`、附件可見性、頭像上傳／選擇機制、與既有 mode SOP／steps／fanout 定義的相容性），非核准實作批次。
94. **backlog 92 Gate B round 7 遺留 Minor 項（皆 non-blocker，merge 時 Orchestrator 裁定記入 backlog）**：①`spec.md` 完成狀態標記時機與 `docs/agent-prompts/reviewer.md`「狀態更新需在送審 chain 內」的要求有既有流程衝突，需擇一為準並統一套用；②法院模式的模型失效警告文案與紅藍模式互為逐字複製，無專屬測試防止未來走鐘；③鍵盤啟動 ℹ 詳情按鈕的「不得改變篩選」情境只測了一般角色座位，Chairman 座位與 Space 鍵未覆蓋；④模型登錄表為空（`no models are configured`）時警告文案仍落回英文原文；⑤≤640px 窄視窗下模型失效／存檔失敗兩個警告橫幅會被角色列的水平捲動裁到畫面外（內容仍可橫向捲動看到、螢幕閱讀器仍讀得到，非完全靜默失效，但相對 base 是呈現倒退）；⑥`assignmentUpdateError` 直接顯示後端英文 `detail` 原文，未轉繁中；⑦模型 select 執行中 disabled 時沒有任何提示告知原因；⑧13.15／13.20 兩個換模型 e2e 用 `if (optionCount > 1)` 包住核心斷言，模型只有一個時會悄悄跳過；⑨`assignmentWarnings`／`resolveModelName` 邏輯在兩個元件間逐字重複、無 unit 測試；⑩`mergeServerParticipantModels` 命名與行為不符（不讀入參數，純覆蓋）；⑪觸控裝置上 ℹ 詳情按鈕因 `opacity:0` + hover-only 顯示規則而不可見；⑫座位 `div[role="button"]` 內巢狀 `<button>`／`<select>` 為 ARIA 不合規結構；⑬`TopBar.vue`／`MeetingSettingsDrawer.vue` 各有一處本批次引入的死 import／死綁定；⑭`MentionAutocomplete.vue` `activeIndex` 未隨 `menuItems` 過濾收斂，打字收窄期間 `aria-activedescendant` 可能指向不存在的 option（下一方向鍵以 modulo 自癒，屬 ARIA 暫時脫離）；⑮`ChatroomComposer.vue` 組字中直接點「送出」會先 blur 使 `composing=false`，未 commit 的候選字視 IME 決定被取消而遺失（與 base 同軌、非本批 regression，但本批已接手 IME 故事）。⑭⑮ 為 2026-07-31 round-2 Gate B 審查 Minor，由 Orchestrator 裁定記入本 backlog。
95. **提及選單完全無法用鍵盤操作**：`MentionAutocomplete.vue` 的 `onKeyDown`（處理 ↑／↓／Enter／Tab／Escape 的選單導航與選取）是死程式碼——既未綁在任何元素上、未 `defineExpose`，父元件 `ChatroomComposer.vue` 也沒有呼叫它，因此 `@` 提及選單只能用滑鼠點選，鍵盤使用者與螢幕閱讀器使用者無法選取任何角色（選單本身已標記 `role="listbox"`，卻沒有對應的鍵盤契約，屬 ARIA 承諾與實作不符）。修法需將 keydown 契約接上 composer 的 textarea，且必須與 IME 組字防護共存：選單開啟時的 Enter 只有在非組字狀態才可用於選取，組字中的 Enter 一律讓給輸入法（見 2026-07-30 IME 修復），否則會複製同一類 bug。另附一項較輕的同類問題：`MeetingsModal.vue` 逐字稿搜尋用 `@keyup.enter`，中文選字確認時的 Enter 於 keyup 階段 `isComposing` 已為 false，會提早觸發一次搜尋（文字此時已 commit，結果正確，僅時機提前，非資料遺失）。2026-07-30 修復聊天室 IME 送出 bug 時發現。**同日 Human Owner 指示一併修復並完成**：`handleKeyDown` 以「是否已消耗此鍵」的布林回傳接到 composer textarea，順序為 IME 防護優先（輸入法同樣用方向鍵選候選字、用 Enter 確認，順序寫反等於在上一層重犯同一個 bug）；認領條件由 `isOpen` 改為 `showMenu`，避免選單為空時 Enter 被 `preventDefault` 吃掉而既不選取也不送出；連帶清除同樣未被綁定的死程式碼 `onInput`；`role="listbox"` 由永遠存在的外層 div 移至條件渲染的選單本身（原本選單關閉時仍宣告一個空 listbox），並補 option `id`／`aria-activedescendant`／`aria-expanded`／`aria-controls` 與 `scrollIntoView`（選單有 200px 上限會捲動）。行為改變：選單開啟時 Enter 選取候選項而非送出，需再按一次 Enter 才送出（Slack／Discord／GitHub 標準行為）。新增 e2e 13.24／13.25，兩項變異測試皆紅（拆接線→13.24／13.25 紅；選單置於 IME 防護之前→13.25 紅）。123 e2e／116 unit／build 全綠。上述 `MeetingsModal.vue` `@keyup.enter` 一項仍未處理。

    **Residual IME fix／Gate B／Acceptance／Closeout（2026-08-05）**：針對本條目附帶的逐字稿搜尋問題，`MeetingsModal.vue` 已改以 composition-aware keydown guard：composition 期間按 Enter 不觸發搜尋；composition 結束後普通 Enter 仍可搜尋，滑鼠點擊搜尋仍保留。此 scoped fix 不改 API、搜尋語意、其他 mention 行為或其他 IME 行為。Exact implementation identity 為 `b4b6f94470232d673b02e6ad7c2fbec3d097926e`，fixed range 為 `b9389d90180aa0ddbfa439152e7dec7b680cc23e..b4b6f94470232d673b02e6ad7c2fbec3d097926e`；commit chain 為 `05fd1b4`（red regression test）→ `b4b6f94`（green IME guard fix）。Gate B 由兩個獨立 axis Reviewer（Standards、Spec）審查固定 implementation identity，皆為 `pass`、無 findings。變更產品檔案為 `frontend/src/components/MeetingsModal.vue` 與 `frontend/tests/e2e/control-flow.spec.ts`。驗收／post-merge 證據：focused Playwright `tests/e2e/control-flow.spec.ts -g 'transcript search ignores IME'` **1/1**、frontend `npm run test:unit` **162/162**、`npm run build` 通過、`git diff --check` 通過。未驗證範圍：未重跑 full backend suite、full Chromium E2E，且本次未保存 direct Chrome/browser version evidence。Human Owner 於 2026-08-05 原始確認「#95 驗收通過」。本項現標記為 **`accepted / done`**；這是小型 `.scratch` scoped fix，不建立、修改或封存 OpenSpec change/archive。
96. **聊天室 LINE 式檔案附件（「+」可上傳檔案）**：Human Owner 於 #92 round-2 驗收（2026-07-31）指出「+」彈出的案卷 modal（`CaseMaterialsModal`）只支援純文字表單（標題＋內容＋可見角色），而 round-2 引入的非法院模式用語「附件（0）」承諾了上傳能力卻無處上傳，屬誤導；全系統唯一的檔案上傳只在建立會議的 `NewCaseModal.vue`（且只接受 `.txt/.md` 讀成文字），後端 `case_materials.py` 的 `MaterialVersion` 只有 `title+content`，完全沒有二進位附件契約。Human Owner 裁決採用 LINE 式聊天附件：「+」上傳檔案後以訊息氣泡顯示在聊天串、可下載；`.txt/.md` 直接讀全文注入既有版本化案卷契約（AI 看得見，沿用字元上限、可見角色與 revision）；PDF／圖片等其他類型以二進位附件儲存、不注入 prompt（需新後端二進位儲存與下載端點）。此需求反轉 spec.md #90「不建立另一套訊息附件契約」的決策，屬明確範圍擴張。非核准實作批次，須先登錄本 backlog 再開 OpenSpec proposal；`chatroom-ux-round2` 的「附件」用語待本項交付後自然相符，期間保持誤導屬已知狀態。**Gate A（2026-07-31）**：OpenSpec change `chatroom-line-attachments`（`afd2c43...3b930a5`，head `3b930a5`）經獨立 Reviewer 審查 `pass`。審查期間 Human Owner 裁決檔案類型路由採「完全依 #96 原文」：文字僅 `.txt/.md` 注入 prompt，其餘所有類型（含 `.zip/.docx/.mp4`）一律二進位儲存、可下載、無 whitelist／無 reject（size 上限與未知 file_id 404 仍保留）；另修正 AI-unawareness 情境改為 prompt/context 組裝的確定性斷言、tasks 補 4.7（binary 下載不受 `visible_roles` 控管而 text 仍受控管）、補通用二進位氣泡渲染契約（非圖像／非 PDF 的 binary 以 filename+size+download 卡片呈現）。**Artifacts 已核准，可開始實作。** **Gate B（2026-07-31）**：實作於隔離 worktree 完成（fixed range `0187664...3c44b01`，10 commits、19 檔 +1828），歷經 1 輪 review-fix 循環：round 1 `needs-fixes`（Major：法院模式附件顯示為「（沒有文字內容）」空氣泡；Minor：upload state machine 無 unit、無通用二進位 e2e；4 Nit）→ 全部修正後複審 `pass`。修正內容：`CourtroomDocketPanel.vue` 三處訊息位置以 `AttachmentBubble`（證物）渲染附件、upload 狀態機抽成 `attachmentUpload.ts` 純模組＋unit、`.zip` generic card e2e、upload 端點以宣告 Content-Length 在緩衝前拒絕過大 body、移除 `BINARY_MIME_TYPES` 死條目、修正 evidence 與 api.ts 註解。合併後 post-merge checks：backend **681 passed**、frontend unit **126 passed**、build 綠。Orchestrator fast-forward merge 至 main（`3c44b01`）。**`implemented / awaiting acceptance`（2026-07-31）。** **2026-08-01 驗收修正（第一輪）**：Human Owner 驗收時在附件上傳區上傳 `.txt`，依契約路由至案卷表單並存檔後，因 #88（AI 發言後新增會進 prompt 的資料）暫停 AI 並跳出「附件已在 AI 發言後變更」banner，無事前警告造成誤會。Orchestrator 實測確認二進位上傳不觸發 `pending_impact`（`None`），行為符合契約；Human Owner 裁決加「存檔前警告」。Fix（`16c1b34...efd0bc1`，5 commits／4 檔 +92）：`meetingWorkspace.ts` 新增純函式 `hasAiOutput`（role∉{Human,System} 且 status=completed，對齊後端 `material_change_impact`）與 `materialImpactConfirmMessage(modeId)`（法院「案卷與證物」／其他「附件與資料」、皆含暫停＋重開審議＋確定儲存）；`CaseMaterialsModal.vue` 在 `saveMaterial`（含 `.txt` 路由存檔）與 `toggle` 前，當 `hasAiOutput` 為真以 `window.confirm` 先確認；unit 新增 `materialMutation.test.ts`（7 tests）。Gate B 複審：round 1 Reviewer `needs-fixes`（Major：e2e `control-flow.spec.ts` 的 confirm 被 Playwright 自動 dismiss 造成 regression；Minor：確認訊息對 vocab label 字串耦合）→ 修正（e2e 於 3 個 post-AI 動作註冊 `page.once('dialog')` 斷言文案並 accept；訊息改由 `modeId` 派生）→ round 2 Reviewer 複審 `pass`（無 Blocking/Major）。post-merge checks：frontend unit **133 passed**（+7）、build 綠；backend 未動（維持 681）。Orchestrator fast-forward merge 至 main（`efd0bc1`），worktree/branch 已清理。**`implemented / awaiting acceptance`（2026-08-01，重新驗收中）。** **2026-08-02 驗收修正（第二輪）**：Human Owner 重新驗收時上傳 `.md`（與 `.txt` 同路由至案卷表單），發現聊天室材料卡顯示「證物」（`[證物N]`），追問「為什麼是寫證物」。根因：引用錨點 token 由後端以法庭用語硬編碼生成（`case_materials.py:703`、`api.py:3110`），原樣流入 prompt 與 UI 投影；#92 的 mode 感知用語只涵蓋章節標題／按鈕，未涵蓋錨點；聊天室連 AI 回應的引用也是 `[證物N]`（mock adapter 抓 prompt 錨點回填）。Human Owner 裁決：非法院模式錨點改「附件」（`[附件N]`）。Fix 採輕量疊代（Reviewer 審設計 Gate A 角色）：設計（`.scratch/96-citation-anchor-design.md`）經獨立 Reviewer 設計審查 `pass`（2 Minor 事實性修正：`:4089` 呼叫端實為 `project_meeting_summary`、`case_profiles.py` 為 courtroom 專用且已接線的 validator 非 dead code）。核心決策：儲存層典範 token `[證物N]` 不變（不遷移），所有輸出面（prompt 組裝、UI 投影、AI 輸出驗證、前端新建預覽）依 mode 本地化；新增 `evidence_anchor_label`／`localize_evidence_anchor`（idempotent）helper；`EVIDENCE_REF_PATTERN`（parser）與 mock adapter 寛容接受 `證物|附件`（法院模式非法院 token 仍由 `case_profiles.validate_final_semantics` 攔截，屬預期防護）。實作於 worktree `.worktrees/evidence-anchor-localization`（fixed range `6813798...ac6671c`，5 commits／8 檔 +386）：`f60b051`(test backend)→`182c94f`(feat backend：api.py 本地化 helper＋15 處輸出/呼叫觸點、adapters.py regex、parser.py 寛容)→`9870575`(test frontend)→`9d6c3f5`(feat frontend：`draftEvidenceAnchor` 抽至 `meetingWorkspace.ts` mode-aware，`NewCaseModal.vue` 委派)→`ac6671c`(test e2e：control-flow `:46` helper mode-aware、`:980/:2839/:3003` red-blue 改 `[附件一]`、courtroom 維持)。測試：backend **715 passed**（基線 681＋新增 34）、frontend unit **137 passed**（＋4）、build 綠（vue-tsc exit=0）；唯一 1 個 pytest failure 為 pre-existing timing flake（base 同現）。Gate B 獨立 Reviewer 審查 `pass`（無 Blocking/Major；1 Minor 流程：docs 紀錄併入送審 chain）。**`implemented / awaiting acceptance`（2026-08-02，重新驗收中）。** **2026-08-02 驗收修正（第三輪：拆分附件上傳與資料管理）**：Human Owner 重新驗收時指出 `＋` 把「上傳」與「管理」混在彈出視窗（`CaseMaterialsModal`），要求 LINE 風格拆分：`＋` 只做上傳（彈出快速選單「上傳檔案／資料管理」）、管理移至右側側欄新增「資料」頁（與脈絡/紀錄並列）、法院一併拆分（「案卷」頁）、二進位上傳進度列顯示在資料頁頂部；`.txt/.md` 分流保留（自動開資料頁預填表單，沿用 round-1 存檔前確認）。設計（`.scratch/96-upload-management-split.md`）經獨立 Reviewer Gate A 角色兩輪：round 1 `needs-fixes`（1 Blocking 法院頁籤 label 內部矛盾、3 Major 上傳鎖消失／跨會議 uploads/textDraft 狀態洩漏／收合與 mobile 自動開資料頁未定義、6 Minor＋2 Nit）→ 全數修入後複審 `pass`（殘留 4 Nit 亦修入：附件清單/upload-zone 用語遷移指名、MaterialsPanel `active` prop、`openMaterialsTab` 依容器分叉、隱藏 input 鎖定時 `:disabled`）。核心決策：`＋`→`MaterialsQuickMenu`（dropdown＋常駐 DOM 隱藏 file input，`materials-quick-menu`/`materials-menu-upload`/`materials-menu-manage`/`attachment-upload-input`）；側欄新增第三頁籤 conversation「資料（N）」／法院「案卷（N）」（`materialVocabulary` 新增 `tabLabel` 欄位）；新 composable `useMaterialUploads`（`watch(meetingId)` 清空跨會議狀態、`onPickedFiles` 分流、`openMaterialsTab` 與 upload boundary 注入供 unit fake）；新 `MaterialsPanel.vue`（管理內容＋上傳進度列獨立於 materials 載入渲染＋**附件清單為新增功能**列舉 `meeting.events` 中 `isAttachmentEvent`，download href 走 `attachmentDownloadUrl`）；`CaseMaterialsModal.vue` 整個移除（App/TopBar 死碼清除）；`ChatroomComposer` 新增獨立 `uploadDisabled` prop **只餵快速選單**（運行中整組 composer 不因上傳鎖停用，還原 base 行為）；`pending_impact` 警告、`hasAiOutput`＋`materialImpactConfirmMessage` 確認、mode 感知用語、`attachmentUpload.ts`/`AttachmentBubble`/後端全部不動。實作於 worktree `.worktrees/materials-upload-management-split`（fixed range `ce458e7...04817ce`，10 commits／14 檔 +933/-260）：Gate B round 1 `needs-fixes`（Major：設計明列的「運行中上傳停用」與「附件清單」兩項新 e2e 斷言未實作、`ChatroomComposer` 上傳鎖被放大成整組 composer 鎖定；Minor：`.txt` 自動開資料頁 seam 未被測試；3 Nit）→ Executor 修正（4 commits：`78a456f` 運行鎖（mutation 手法＋等 WebSocket snapshot settle）與附件清單（download href＋GET 逐 byte 比對）e2e、`d95d9cb` `uploadDisabled` 分離、`413af4a` `.txt` 自動開頁 seam 斷言（移除手動開頁）、`04817ce` 3 Nit）→ round 2 複審 `pass`（殘留 3 Nit 不阻擋）。e2e 期間另抓到並修正一個真 bug：restart 後側欄案卷面板因 `v-show` 快取不重載，`pending_impact` 警告殘留（`16313b5`：重新啟用同一會議且快取仍帶 `pending_impact` 時重載一次，其餘保留 state）。測試：frontend unit **146 passed**（＋9）、build 綠（vue-tsc）、`chatroom.spec.ts` 全 **33 pass**、`control-flow.spec.ts` 受影響用例全綠（既有 4 個 rotation 用例為 pre-existing flake）；後端未動（維持 715）。**2026-08-02 驗收修正（第四輪：主題樣式）**：Human Owner 重新驗收時指出「＋ 點下去底色是白的？管理附件底色也白的」。根因確診：App 為深色主題，`frontend/src/styles.css` `:root` 只定義 `--color-*`（`--color-bg #0b0e14`、`--color-surface #131722`、`--color-surface-muted #171c27`、`--color-border #232b38` 等），但第三輪新元件 `MaterialsQuickMenu.vue`（scoped :121-122/:138）與 `MaterialsPanel.vue`（:294/:300/:304/:348/:355/:373/:382/:440/:447）用了**未定義** `var(--bg, #fff)`／`var(--border, #eee)`／`var(--bg-muted, #f5f5f5)`／`var(--accent, #888)`／`var(--warning, #d99a2b)`／`var(--danger, #c00)`，全部 fallback 白/淺色，且 scoped 優先權高於 styles.css 既有深色 global 規則（`.material-card` 等 :2602-2665）。Fix（`39e41d1`，1 commit／2 檔 +21/-19）：兩檔 scoped style 未定義 fallback 全換 `--color-*` 深色 token（`--color-surface`／`--color-border`／`--color-surface-muted`／`--color-completed-tint`／`--color-failed-tint`／`--color-text`／`--color-text-muted`／`--color-border-strong`／`--color-danger`／`--shadow-md`；warning 用 `rgba(245,178,66,0.1)` 與 :2653 一致）。未動 layout/template/script/styles.css/其他元件（`AttachmentBubble.vue` 等 base 既有同型 fallback 不在範圍）。`rg` 兩檔零殘留；驗證：frontend unit **146 passed**、build 綠、`chatroom.spec.ts` **33 pass**。Orchestrator 已 fast-forward merge 至 main（`39e41d1`）。**2026-08-02 驗收修正（第五輪：側欄佈局）**：Human Owner 驗收時指出（a）資料頁跟紀錄混合在一起、（b）側欄必須橫向滾動才能看全貌、（c）質疑上傳後是否如 LINE 般顯示在聊天視窗。Orchestrator 以 Playwright 實測 DOM 確診：**(c) 正常**（上傳完成後 `attachment-image` 在 message feed 內渲染 AttachmentBubble 氣泡，e2e 13.28-13.30 亦驗證）。(a) 根因 `ConversationWorkspace.vue` 的紀錄區塊用 `v-else`（「脈絡」`v-if` 的 else），資料頁啟用時紀錄仍渲染；改為 `v-else-if="activeContextTab === 'records'"`。(b) 根因長檔名把側欄內容 min-content 撐到 844px（`attachment-upload-name`／`materials-attachment-row strong` 有 ellipsis 但 grid/flex item 缺 `min-width:0`，`1fr` 軌不縮，ellipsis 永不觸發）；在 `.materials-panel`／`.attachment-upload-list`／`li`／`.attachment-upload-name`／`.materials-attachment-list`／`.materials-attachment-row`／`strong` 補 `min-width:0` 鏈後，panel scrollWidth 由 856px 回到 299px＝clientWidth，長檔名改以 ellipsis 截斷。Fix（`be8da43`，1 commit／2 檔 +11/-1）。驗證：unit **146 pass**、build 綠、`chatroom.spec.ts` **33 pass**、control-flow 受影響 7 用例全過（完整跑一遍時 test 58/61 各 fail 一次，單獨重跑皆 pass，判為 suite 擁塞 flake 與本改動無關）。已 FF merge 至 main（`be8da43`）。**`implemented / awaiting acceptance`（2026-08-02，重新驗收中）。** **2026-08-02 驗收修正（第六輪：LINE 式上傳）**：Human Owner 指出「＋」不該出現「上傳附件／資料管理」兩選單、modal 也不需要（LINE 風格就是 ＋ 直接開原生檔案選取器）；側欄「備註（0）／新增附件」屬重工；聊天室不需要「需重開審議」機制（此為 round 1 起既有行為：後端 `material_change_impact`（api.py:894）全模式生效，聊天室 AI 回應經 `require_case_materials_ready`（api.py:3371）受 `pending_impact` 阻擋（409），而聊天室無「重開審議」UI（僅 ActionBar.vue）＝會卡死）。**Human Owner 裁決：聊天室類別停用 impact 閘門**，並要求 `.txt/.md` 上傳自動 mirror 成 case evidence（AI 可讀）且以附件卡片呈現（點開才見全文，不把全文貼進聊天串）、聊天室側欄資料頁移除備註／表單／版本管理。設計（`.scratch/96-line-style-upload-round6.md`）Gate A round 1 `needs-fixes`（3 Major＋1 Minor＋2 Nit，含既有 reject 測試 `test_upload_text_file_rejected_by_attachment_endpoint`（test_api.py:7205）與 `chatroom.spec.ts:1059` `.txt` 契約測試漏列、`ConversationWorkspace.vue` 同時服務 relay/parallel 需 mode-limited）→ 全數修入；round 2 **Approve with conditions**（4 條件：`.txt/.md` 接受僅限 chatroom 類別（非聊天室直接 API 上傳維持 400）、讀側恢復機制（`require_case_materials_ready` 新增 `ignore_pending_impact`，`chatroom_mention_context` 傳 True 治癒既有 pending_impact 死鎖、免遷移）、`summary()` 存在但無 total chars 措辭、e2e quick-menu selector 遷移）全數納入設計。實作 `9850e34...f0a6f73`（13 commits／12 檔 +546/−72）：backend `upload_meeting_attachment` chatroom 一魚兩吃（先 `perform_material_mutation` mirror evidence 成功才存 blob＋`attachment-added` event，mime text/plain｜text/markdown）、`perform_material_mutation` mode-aware（chatroom→impact=None）、`require_case_materials_ready` 讀側停用（僅 chatroom）；frontend `ChatroomComposer` 移除 `<MaterialsQuickMenu>` 改「＋」（`chatroom-attachment-button`）直開 `attachment-upload-input`、`ConversationWorkspace` `routeTextToCaseFiles: () => !isChatroom`＋`:simple="isChatroom"`、`AttachmentBubble` text reader（`attachment-text`／`attachment-reader`，fetch→`<pre>`）、`MaterialsPanel` simple prop、`materialCountFor` 排除 text mime 附件事件防 N+1。Gate B round 1 `pass`（2 Minor＋1 Nit：post-AI 上傳無 banner 之 e2e 缺漏、reader 樣式未定義 fallback token（round-4 同類缺陷）、重複 hover rule）→ 修正（`f77530b`/`8fc34ee`/`f0a6f73`）→ 聚焦複審 `pass`（No new findings）。post-merge checks：backend **720 passed**（基線 715＋5）、frontend unit **147 passed**、build 綠、`chatroom.spec.ts` **35 passed**（基線 33＋2）、control-flow 受影響用例綠。已 FF merge 至 main（`f0a6f73`）。**`implemented / awaiting acceptance`（2026-08-02，重新驗收中）。** **2026-08-02 驗收修正（第七輪：聊天室附件修正）**：Human Owner 重新驗收時裁決三件事：① 聊天室證據卡「使用中／已停用」狀態無按鈕是假功能；② 應有「刪除附件」功能（LINE 回收概念）；③ 聊天室仍出現「附件已在 AI 發言後變更…重開全部審議」banner。範圍裁定：刪除功能**所有模式都有**（聊天室／接力／平行／法庭）；刪 `.txt/.md` **一併移除 mirror 成的 AI 可讀 case evidence**；聊天串氣泡**保留**並標「已刪除」且**不可點選開啟**（非整串消失、非維持可點）。根因確診：③＝round-6 只停用寫側（`perform_material_mutation` chatroom→impact=None）與讀側（`require_case_materials_ready` ignore_pending_impact），但 `project_case_materials`（api.py:3239）仍把**存留的 pending_impact** 投影進 payload → `MaterialsPanel.vue:221` banner 照顯示（實例：`data/meetings/meeting-cbacabaea0384375a921771d19d957e3/case_files.json`）；①＝`MaterialsPanel.vue:243` 無條件顯示狀態文字但按鈕列在 simple（聊天室）被 `v-if="!simple"` 隱藏；②＝v1 附件 append-only 無 delete/deactivate。設計（`.scratch/96-chatroom-attachment-fixes-round7.md`）Gate A 獨立 Reviewer `pass`（無 Blocking/Major；3 Spec Minor＋2 Quality Minor＋2 Nit 全數裁定納入）：`removed?: boolean` type 契約（api.ts MeetingEvent＋meetingWorkspace.ts WorkspaceEvent）、e2e 補聊天室 evidence-card header 無狀態文字斷言、**多裝置 WS trade-off 採記錄不實作**（tombstone 於 `project_events` 過濾後其他已連線 client 的 delta 為空、refresh/reconnect 自癒；刪除者 openMeeting refetch 即時）、legacy text fallback 歧義防護（無 `evidence_id` 時 title 匹配 0→跳過／恰1→移除／**>1→400**）、`evidence_id` 存在但 view 已無→跳過 mutation、`transcript.py` render 排除 tombstone、confirm 中性文案「刪除後無法復原。確定刪除？」。實作於 worktree `.worktrees/96-chatroom-attachment-fixes-round7`（fixed range `96444e1...cee96c1`，8 commits／18 檔 +1262/−38）：`ebf201c`(append-only `attachment-removed` tombstone＋blob 刪除＋`removed_file_ids`/`attachment_event(s)` 排除)、`321aaf7`(`case_materials.remove_evidence`，transition `remove-evidence`、limits=None)、`95c8bde`(`DELETE /meetings/{id}/attachments/{file_id}` 端點：`reject_running_meeting`、evidence 移除**先於** tombstone、legacy fallback 歧義 400、`project_events` 過濾 tombstone＋已刪 `attachment-added` 標註 `removed:true`，4 呼叫端傳 `removed_attachment_ids`)、`3ebb8d7`(chatroom `pending_impact` 投影抑制：`project_case_materials` category 參數、四呼叫端 :864/:942/:967/:823 全傳、list summary 一致性；純投影抑制不遷移資料)、`79ca475`(前端 `deleteAttachment` API＋`materialCountFor` 跳過 removed)、`93a0f3d`(刪除按鈕 `attachment-delete-{file_id}`＋`window.confirm`＋已刪後 reload、AttachmentBubble「已刪除」不可點卡、simple 狀態文字隱藏)、`ac2d723`(e2e)、`cee96c1`(刪除後 `MaterialsPanel` reload materials 修 stale 證據卡 bug——`.txt` 連動刪除 e2e 抓到的真 bug：`openMeeting` 刷新 events/selectedMeeting 但證據卡來自自身 `getCaseMaterials` load)。另 runner.py:1441／chatroom_context.py:49 排除 tombstone 防漏進 AI context。Gate B 獨立 Reviewer `pass`（無 Blocking/Major；1 Minor 流程：docs 紀錄併入送審 chain——已於本 commit 記錄；1 Nit：`AttachmentBubble.vue:247` `.attachment-card-removed:hover` 用未定義 `--border` 淺色 fallback，深色主題 hover 閃 `#ddd`，純外觀不阻擋、列為後續小修）。post-merge checks：backend **743 passed**（基線 720＋23；唯一 1 failure＝pre-existing timing flake `test_startup_health_check_does_not_block_app_creation`，源自 `1c588ba`、本輪 diff 未觸、Reviewer 同 code 全量 743 passed，因 load avg 121-152 機器擁塞觸發 0.5s 門檻）、frontend unit **149 passed**（基線 147＋2）、build 綠（vue-tsc）、`chatroom.spec.ts` **40 passed**（基線 35＋5）、`control-flow.spec.ts` relay binary delete **1 passed**。已 FF merge 至 main（`cee96c1`）。**`implemented / awaiting acceptance`（2026-08-02，重新驗收中）。**

97. **VibeCoding Workflow 首次採用（AIDLC bootstrap）**：中央工作流 repo（`/Users/chrischiu/SynologyDrive/Project/VibeCoding_Workflow`，固定 revision `de1aca49181af3ce8583f6d59b034ea8136d42c6`）正式成為本專案流程來源。新增 `docs/agents/workflow-bindings.md`（§0 來源 bootstrap、§1 專案資訊、§2 三角色執行者與模型、§3 六個正式流程入口、§4 canonical 紀錄、§5 安全邊界、§6 交接）；`AGENTS.md`／`CLAUDE.md` 政策入口改為 bootstrap 單一語意並修正過時 `.scratch` tracker 說明；三份角色 prompt 必讀清單加入 bootstrap 並修正與中央規範的 3 處衝突（orchestrator「可直接動手的範圍」違反中央「不實作」、reviewer Verdict 缺 `Reviewed identity`、必讀順序缺綁定檔）。review(doc) 由獨立 Reviewer subagent 對 fixed range `83cea96...96e083c` 通過（1 Minor＋1 Nit：本地 `multi-agent-development.md` 與中央同相對路徑的優先順序、Idea 入口路徑，均已套用修正並複審 `pass`），Orchestrator fast-forward merge 至 main（`96e083c`），worktree/branch 已清理、既有 untracked 保留。三角色模型經 Human Owner 確認皆為 session runtime `opencode/big-pickle`（綁定檔 §2）。**2026-07-31 Human Owner 驗收通過，`accepted / done`。**

98. **聊天室 @all 平行回應的批次群組顯示**：Human Owner 於 #96 第七輪驗收後測試 @all，質疑「沒有平行一起執行」。Orchestrator 以 backend events 實證後端**確實平行**（`fanout_chatroom_all` 用 `ThreadPoolExecutor(max_workers=len)`，runner.py:595；測試 meeting「創業」178c58e1 四角色 `started_at` 全同秒、耗時 17.7–20.1s 重疊，若序列執行總耗時 ~75s）。使用者觀察到的「一個一個出現（隔幾秒）」是**完成順序**的正常呈現：runner 用 `as_completed` 依完成先後逐一 append（runner.py:600），前端 feed 因此逐條浮現。Human Owner 裁決採「批次群組顯示」：feed 中把同一輪 @all（共享 `chat-fanout-{timestamp_ms}-*` 前綴）的回覆群組在一起，顯示「N 位角色回應中」＋完成後逐條填入，讓使用者看出是同一輪平行 fanout。純前端變更（`meetingWorkspace.ts`／`ConversationWorkspace.vue`／`useCouncil.ts` 的 pendingRoles 期望成員集合擷取與 failure 語意調整），不動後端 API、事件結構或聊天室執行語意（@all fanout 本身已平行）。**2026-08-04 Human Owner 驗收通過，狀態 `accepted / done`。** Exact implementation merge：`2d1b9a5`。最終 contract：只對 chatroom `@all` 顯示可在首個回應前出現的 `0/N` 批次群組與全部預期角色 placeholders；回覆依事件 arrival order 顯示，未完成 placeholders 固定留在底部且分母固定；各成員 failure、terminal unknown、request failure、disconnect/reconnect degradation 均有明確投影。`@all` 以外的 directed single-role／multi-mention 保持 flat，relay／parallel／courtroom／其他正式或非聊天室流程與歷史 fallback 不變。驗收證據：`focused Playwright tests/e2e/chatroom.spec.ts -g '13\\.4|13\\.7'` **4/4**、`frontend tests/unit/meetingWorkspace.test.ts` **31/31**、`npm run build` 通過。未驗證範圍：本次 acceptance 未重跑 full backend suite、full frontend unit suite 或 full Chromium E2E；本次未新增 backend/event schema/API/data migration。

99. **聊天室自然回覆契約**：Human Owner 於 2026-08-04 驗收「創業」meeting 時發現聊天室的 `@Advisor` 回覆仍以「摘要／論點／風險／建議處置」正式報告格式呈現，與 #91 要求的「一般聊天精簡篇幅」不符。聊天室應使用獨立的 `chat-message/v1` 輸出契約，前端聊天氣泡只呈現自然、精簡的 `message` 內容；證據引用仍可保留 `[附件N]`，raw/parsed output 與診斷資料仍須保存，relay／parallel／brainstorm／courtroom／正式裁決的結構化 output schema 與 presentation 不受影響。既有事件必須 read-time 相容，不回寫歷史 events，且不做 migration。OpenSpec change `chatroom-natural-response` 的 tasks 已全數完成；exact implementation merge 是 `111e898`。Human Owner 已於 2026-08-04 明確確認「#99 驗收通過」，狀態為 `accepted / done`。驗收證據：focused `Playwright tests/e2e/chatroom.spec.ts -g '13\\.3'` **1/1**、`frontend tests/unit/meetingWorkspace.test.ts` **31/31**、`backend tests/test_runner_chatroom.py` **13/13**、`backend tests/test_prompting.py -k 'chat_message_v1 or chatroom_response_template'` **5/5**、`frontend npm run test:unit` **162/162**、`frontend npm run build` 通過。Scope exclusions：不改 directed／@all 以外的執行語意、不改 relay／parallel／brainstorm／courtroom／正式 schema 或 presentation、不重寫歷史 JSONL、不做資料 migration，且不納入 #98／#101。未驗證範圍：本次 acceptance 未重跑 full backend suite、full Chromium E2E、direct browser smoke 或其他非列明模式的完整回歸。

100. **右側會議脈絡欄收合後可重新展開**：Human Owner 於 2026-08-04 驗收 #96/#98/#99 時發現桌面版右側會議脈絡欄收合後，三個分頁仍留在 52px header 內，將 32px 展開控制推到 viewport 邊界，只剩約 14px 可見，造成使用者無法可靠重新展開。修正限於 `ConversationWorkspace`／workspace context CSS 與前端 regression coverage：收合時隱藏分頁、完整保留且置中展開控制，桌面與 responsive layout 均不得裁切；不得改動 API、事件格式、聊天執行語意或法院流程。Executor implementation `12da498` 經獨立 Gate B Reviewer 審查 `PASS`，Orchestrator 以 exact merge commit `16002be` 合併。驗證範圍：focused Playwright、Chrome smoke、frontend unit `162/162`、`npm run build` 均已通過；full E2E 未執行，因此 full E2E 為未驗證範圍。Chrome smoke 驗證桌面收合後可重新展開、重複循環穩定且 375px responsive 行為保留。Human Owner 於 2026-08-04 明確確認：「驗收通過可以做收尾了」。狀態：`accepted / done`。
101. **聊天室引用預覽套用深色主題**：Human Owner 於 2026-08-04 點選聊天室訊息的「引用」後，發現 composer 上方的引用預覽呈現刺眼淺色背景。Chrome 實測 `.chatroom-composer-quote` 背景為 `rgb(245, 245, 245)`；根因是 `ChatroomComposer.vue` 使用未定義的 `--bg-muted`，fallback 到 `#f5f5f5`，與本專案既有 `--color-*` 深色 token 不一致。修正限於引用預覽的前端 theme token 與 regression coverage：使用既有深色 surface/border/text token，保留引用內容、取消引用與送出語意；不得改動 backend API、事件格式、聊天執行語意或其他模式。驗收需覆蓋點選引用後的預覽背景與文字可讀性，且不得在桌面／responsive layout 回退為 light fallback。

    **Implementation／Gate B／Acceptance／Closeout（2026-08-05）**：Exact implementation identity 為 `b813a0ba10d5f6ce56c63d62119c45ca86aadf34`；implementation chain 為 `e862629`（red test）→ `631e008`（引用預覽深色 CSS）→ `b813a0b`（長引用 responsive overflow regression test）。Implementation Gate B final independent Reviewer 審查固定範圍 `bdfd81d71cd709e2b654aef469d4f40e4ad9da68..b813a0ba10d5f6ce56c63d62119c45ca86aadf34`，Verdict `pass`，無新 findings。變更的產品檔案為 `frontend/src/components/ChatroomComposer.vue` 與 `frontend/tests/e2e/chatroom.spec.ts`；未改 backend API、事件格式、聊天執行語意或其他模式。可查核驗證為 focused `frontend/tests/e2e/chatroom.spec.ts -g '13\\.5'` **2/2**、`npm run test:unit` **162/162**、`npm run build` 通過、`git diff --check` 通過。未驗證範圍為本次 post-merge 未重跑 full backend suite、full Chromium E2E，亦無 direct Chrome/browser version evidence。Human Owner 於 2026-08-05 原始確認：「#101 驗收通過」。本項現標記為 **`accepted / done`**；這是 `.scratch/quote-preview-theme-fix/` scoped fix，不建立、修改或封存 OpenSpec artifacts。

102. **聊天室初始空白提示修正**：Human Owner 於 2026-08-07 確認聊天室一開始顯示「尚未有會議發言；可先記錄主席補充，或啟動第一次審議」不符合聊天室行為。聊天室沒有自動啟動第一次審議，應改顯示「還沒有訊息；可直接輸入文字，想請 AI 回應時請 @角色 或 @all。」；非聊天室空白提示與角色篩選空提示維持不變。範圍限 `ConversationWorkspace` 前端呈現與 Playwright regression coverage，不改 API、事件格式、mention／AI 執行語意或歷史資料。小型 `.scratch` scoped fix，後續 ChatGPT 式聊天互動另以 `grill-with-docs` 討論。

    **Implementation／Gate B（2026-08-07）**：Gate A plan identity 為 `48b769bd051bc9405b8ba6ec3be197d3312dd583`，獨立 Reviewer `pass`；implementation fixed identity 為 `48b769bd051bc9405b8ba6ec3be197d3312dd583..3b9ce71408fe59accb771cfe65382ac99b9f15f3`，commit chain 為 `0d7236b`／`ad0efe0`／`72523b6`／`3b9ce71`。Gate B 獨立 Reviewer 審查完整 fixed identity，Verdict `pass`，無新 findings。變更檔案為 `frontend/src/components/ConversationWorkspace.vue` 與 `frontend/tests/e2e/chatroom.spec.ts`；新增公開 UI regression 覆蓋 chatroom（13.1）、非聊天室（13.1a）與 selected role（13.1b）三種空態。驗證：Executor focused Chromium 3 cases 各 **1/1**、frontend unit **165/165**、main post-merge `npm run build` 通過、`git diff --check` 通過；Reviewer 獨立確認 frontend unit **165/165**、type check 通過。未驗證範圍：未重跑 full Chromium E2E、backend tests 或 direct browser smoke；Reviewer worktree 缺少指定 Chromium executable，未能獨立啟動 E2E。**目前狀態：`implemented / awaiting acceptance`。**

103. **聊天室 ChatGPT 式互動：預設主持、`@`／`#` 路由、共享記憶與自然 prompt**：Human Owner 於 2026-08-07 完成需求討論並確認進入規格階段。聊天室未指定 `@` 時由固定主持 AI（內部 `host` role ID）回覆；`@角色`、多角色 mention 與 `@all` 採明確、可預期的收件者規則，無效 mention 不得誤觸發主持，`@all` 包含主持且同輪使用凍結上下文。composer 需以 autocomplete 明示 `@指定 AI` 與 `#選取附件`，畫面使用角色／附件顯示名稱，傳送使用穩定 ID；一則訊息可引用多個附件，只有明確 `#` 且附件仍存在、AI 可讀、對目標角色可用時，才把 `.txt/.md` 正文或相關段落注入 prompt，沒有 `#` 絕不讀取或檢索任何附件正文，失效引用阻擋本次 AI 執行。附件引用以結構化 refs 呈現為可點擊 chip，不把全文展開在聊天氣泡。prompt 分層為 system／developer 的角色 Persona 與硬規則，加上當輪訊息／共享上下文；回覆採自然、長度自適應、可視需要使用 Markdown，JSON 只作傳輸格式。完整 transcript 是唯一事實來源；模型 prompt 使用最近訊息＋共享會議摘要，摘要由專用任務更新、可在脈絡欄查看但不產生聊天氣泡，失敗時保留上一版並退回最近訊息。此項不改非聊天室模式、歷史 events 不重寫、不做 migration；需建立 OpenSpec change `chatroom-chatgpt-interaction`，先通過 Gate A 才能實作。

**#103 Gate A 契約補充（2026-08-07）**：角色引用使用 display-name chip（`@顧問`／`@主持 AI`／`@全部角色`），chip 內隱藏 stable `role_id`；request 使用 NFC canonical content 與 code-point span token model：`mentions[{token_id,role_id,display_text,start,end}]`、`source_tokens[{token_id,source_ref,display_text,start,end}]`、ordered/deduped `source_refs`、`quoted_event_id`。手打未被 chip span 覆蓋且符合 Unicode raw-@ grammar 的 role-like token 回 `INVALID_MENTION_TOKEN`；raw `#` 永遠是普通文字；span、schema、source、quote validation 與 stale payload 均使用 OpenSpec 封閉 400 mapping table，rejection 先於 event/job。202／400／404／409 response envelope 與 warning code 依 OpenSpec 定義。source namespace 僅 `attachment:<file_id>` 與 `evidence:<evidence_id>`，readability 分別為 active readable `.txt/.md` blob 與 active non-empty string evidence content；初始／legacy 無副檔名 evidence 可讀，`notes` 排除。citation 使用 selected allow-list 的 `{source_ref,label,segment_refs}` 並驗證 projection label／available segment refs。summary 使用與 `MeetingJobManager` 分離的 per-meeting `ChatroomMemoryTaskManager`，manual/automatic trigger 共用 idempotent reservation，generation 不阻擋 chat；可由 `POST /meetings/{meeting_id}/chat/memory/regenerate` 觸發，並以 `chatroom_memory_updated` projection event 更新；失敗保留上一版或標為 `empty`，不產生 feed event。OpenSpec artifacts fix commit 為 `a14ada0` 的後續修正版，仍須獨立 Reviewer 重新 Gate A。

**#103 Gate A 契約再收斂（2026-08-09）**：Human Owner 經 `grill-with-docs` 確認五個固定聊天室角色使用 backend-only `persona_prompt` 與可公開 `persona_summary`；Persona 缺漏須設定載入失敗，不得靜默 fallback。Host 每場必選，其他四角色只在建立會議時選擇，建立後 active roster 固定；`@`／`@all`／pending／來源授權只使用該 roster，舊會議的空 roster read-time 回退五角色，非空 subset 僅補 Host。Canonical chatroom prompt/audit 固定保存 transport 前 `system → developer → user` 三層；adapter capability 由程式碼擁有、`supports_developer_role` 預設 false，不進入模型／會議／使用者設定。Slice 2 僅使用當輪 instruction、quote、recent transcript，維持 message-only `chat-message/v1`，並先移除聊天室自動案卷正文注入；selected source/citation 在 Slice 3、shared summary 在 Slice 4 才加入。文字上傳的 attachment＋mirror evidence 在 selector/citation 只呈現 canonical `attachment:<file_id>` 一項；每個新 evidence version 保存 `host_acl_explicit:true`，只有 marker 缺席的 legacy version 才允許 Host fallback，linked attachment 同步套用；每次呼叫保存 immutable `chatroom-source-context/v1` snapshot，以實際送入的 segment allow-list驗證引用與 retry。使用者自訂角色／Persona 已併入 backlog 93，屬 user/context 且不得覆寫 system/developer，與 #103 分開開發。OpenSpec strict validation 已通過，仍須獨立 Reviewer 重新 Gate A。

**#96 Closeout（2026-08-04）**：Human Owner 明確確認「#96 驗收通過」。狀態更新為 **`accepted / done`**；exact implementation merge 為 `cee96c1`。驗收證據：`frontend/tests/e2e/chatroom.spec.ts` 聚焦 E2E **12/12**、`frontend npm run test:unit` **162/162**、`npm run build` 通過。Final contract 包含原始附件能力、round-6 LINE 式直接檔案選取／chatroom text mirror／pending-impact projection suppression，以及 round-7 全模式刪除、append-only tombstone、blob/download/quota/evidence removal、已刪除不可互動氣泡與 stale materials reload。已知非阻塞 Nit 保留：`AttachmentBubble.vue:247` 的 undefined `--border` hover fallback。未驗證範圍：本次 acceptance 未重跑 full backend suite 與 full Chromium E2E；既有 post-merge evidence 為 backend 743 passed（含一個 pre-existing timing flake）、frontend unit 149、chatroom E2E 40、relay binary-delete control-flow 1 passed。

**#103 Slice 1 implementation／Gate B／等待 Human Owner 驗收（2026-08-08）**：完成聊天室 routing slice：固定 `host` 主持角色、無 `@` 預設 Host、display-name structured chips、`@host`／`@主持`、多角色與 `@all` 平行 fanout、嚴格 request/span/schema validation、raw role-like mention rejection、accepted `IGNORED_INVALID_MENTION` warning、編輯後 stale chip invalidation，以及 Host／fanout pending projection。`@all` 的 server target set 是唯一執行與前端 pending/capture 的 authority，subset participant 不會誤執行非 active roles；NFC 與 astral Unicode code-point spans 已覆蓋。Exact implementation／merge identity 為 `b85352d932d80ec29cbb4a794f2b7c96bb78aa6b`，fixed Gate B range 為 `77d7a972f5cc548bd4fac6f7325be25d4f3dd237..b85352d932d80ec29cbb4a794f2b7c96bb78aa6b`；獨立 Reviewer Verdict `pass`、無新 findings。Post-merge main checks：backend routing／contract／runner **51 passed**、frontend unit **171 passed**、`npm run build` 通過、`git diff --check` 通過；先前 full backend evidence 為 implementation **784 passed**／approved base **747 passed**，最新全套重跑因環境 hang 未取得可靠終局。未驗證範圍：本輪 Chromium E2E 未執行（review worktree 無 Playwright Chromium binary），需由 Human Owner 驗收實際聊天室互動。**Slice 1 狀態：`implemented / awaiting acceptance`；#103 整體仍在進行，Slice 2–4 尚未開始。**

**#103 Slice 1 acceptance regression fix（2026-08-08）**：Human Owner 回報 PDF 上傳 API 失敗與 `😀 @顧問` 送出 400。診斷確認附件 endpoint 的 async handler 被同步 transition decorator 包裝，造成 coroutine 未 await；emoji 的現行 code-point payload 與 Chromium UI 實測可回 202，故補真實 autocomplete regression，不改 mention contract。修正以 shared per-meeting sync/async lock 保留同步 nested guard，並覆蓋同 event loop 競爭、跨 sync/async、exception、cancellation cleanup；未實作 `#`，該功能仍屬 Slice 3。Exact reviewed implementation range 為 `aa16a06d71a7be897fa051ccbdff5b7bbb9b67ea..193f6572c40f6e410015ca2ec31970dbc77b6c23`，獨立 Reviewer 複審 Verdict `pass`、無新 findings。Post-merge：backend targeted **30 passed**、frontend unit **171 passed**、build 綠、emoji Chromium regression **1 passed**；PDF browser smoke 上傳後下載端點回 **200** 且 bytes 完整一致。既有 PDF E2E 的 filename assertion 因聊天卡與資料側欄各有同名節點而 strict locator 失敗，未作為本修補的通過證據；full backend/frontend/E2E 與高併發負載公平性未執行。狀態：**`implemented / awaiting Human Owner re-acceptance`**。

**#103 Slice 2 implementation／Gate B fixes round 2（2026-08-10）**：固定 approved base `825a640dda02e815329b6017850673a84936b9e3` 的獨立 Executor worktree 已實作 prompt layering 與固定 Persona：五個 chatroom role 載入必須同時具備 `persona_summary`／backend-only `persona_prompt`，`GET /modes`／meeting projection 只公開 summary；新聊天室只有省略 `participants` 才 default 全五角色，explicit `[]`、非空但缺 Host 或 duplicate role 均拒絕，合法 Host subset 建立後凍結，settings 只接受該 active role set。Legacy metadata 的 absent／empty roster 仍 read-time 投影五角色，非空 subset 只補 Host，均不 migration。Chatroom request／audit 固定保存 `system`→`developer`→`user` 與 deterministic labeled flattening；system/developer 明定依目前使用者訊息與會議對話的語言回答，只有使用者明示才切換，prompt-template 語言不得決定回答語言；Persona、contract、current instruction 各自維持 system、developer、user/context 分層。OpenAI／Anthropic／Gemini native/fallback、CLI legacy flattening、mock observability、message-only/no-body boundary 與非聊天室行為維持 Slice 2 契約，`attachment_refs`、`#` retrieval/citations、Host ACL marker、shared summary 仍分別保留給 Slice 3／4。Gate B 對 `138a47d780126f27bbe69fa978b7f9d231532727` 與第二次受審 `7233eedce0b1242aa55df813783252319f2aa3fc` 均回覆 `needs-fixes`；本輪 concrete code/tests commit 為 `553e11d7d750716ff6d44f4bd47e85423d19f641`，補齊 roster matrix、CLI／mock、running／adapter-failure canonical audit、五角色兩 Persona 欄位 missing／blank／non-string matrix、public projection secrecy、frozen model update 與既有 browser／routing authority coverage。驗證：prompt-layering／adapter／audit **14 passed**、mode catalog **55 passed**、runner／prompt **68 passed**、finding-focused public API **12 passed**、frontend unit **172 passed**、production build、Chromium roster **1 passed**、OpenSpec strict 與 `git diff --check` 通過。依 Orchestrator timebox 停止 bounded multi-file backend aggregate，未取得完整 relevant-suite 終局；既有 adapter 全檔曾為 **23 passed／2 failed**，隔離為 **1 passed／1 failed**，剩餘 0.1 秒 CLI diagnostic 在本環境於 child flush 前 timeout，未修改 timeout／quota。最終 Gate-B 受審 branch tip 由 Orchestrator 於外部 review／merge closeout 記錄；尚無複審 pass 或 Human acceptance。狀態：**`implemented / awaiting Gate B re-review`**。

### #94⑭ closeout／accepted / done（2026-08-05）

本項修正 `MentionAutocomplete.vue` 的 `activeIndex` 未隨 `menuItems` 收窄而收斂的問題：候選人／參與者清單變短時，公開的 `aria-activedescendant` 必須持續指向目前存在的 option；鍵盤選取、滑鼠 hover、`aria-selected` 與 IME／非聊天室行為維持原契約。Executor red／green chain 為 `9430e8e` → `f90ecb3`，其中 red test 以同一 meeting 的參與者縮減重現 base 會留下不存在 option id 的失敗。

Implementation Gate B 獨立 Reviewer reviewed exact identity `702d60f8862ef1781472f13964970f1f9477dd31..f90ecb35ae0539395a287ee5c0f0725afecccc76` 並判定 `pass`，無新 findings。變更檔案為 `frontend/src/components/MentionAutocomplete.vue` 與 `frontend/tests/e2e/chatroom.spec.ts`；main merge commit 為 `7de2eb2`。驗證：Executor focused Chromium **3/3**，post-merge main focused Chromium **4/4**（13.10／13.10a／13.24／13.25）、frontend unit **162/162**、`npm run build` 通過、`git diff --check` 通過。Reviewer 因其 runtime backend path 不可用未重跑 focused Chromium，但已審查 red evidence 與測試契約；未驗證 full frontend E2E、full backend suite、實體輔助科技與真人中文輸入法。本項為小型 `.scratch` scoped fix，無 backend／API／event schema 變更，沒有建立 OpenSpec change。Human Owner 於 2026-08-05 確認「驗收 ok」；目前狀態為 **`accepted / done`**。

### #94⑮ implementation／Gate B／等待 Human Owner 驗收（2026-08-05）

Human Owner 已核准先處理聊天室 IME 點擊送出遺失草稿問題。初版 `151bacc` 通過 Gate B 後，Human Owner 實測真人中文輸入法仍可在候選字未確認時送出，因此該初版不視為驗收完成，沿同一契約重開修正循環。最新 fixed implementation range 為 `9d8fcf9eefa683a724bde590e22d171cc0b47171...f5d75fe7ee26b89dd65e2269dc37660ad6e8ec13`，red／green chain 為 `a0a3536` → `ab3ee2a`（compositionend-before-click）、`1e3b870` → `3b7e661`（pointercancel）、`1013945` → `f5d75fe`（disabled/no-click 後 keyboard activation）。最新契約為：composition 期間點擊「送出」不得送出或清空草稿，即使 `compositionend`／blur 先於 click；取消或未產生 click 的 pointer activation 不得污染後續獨立 pointer／keyboard click；composition 結束後的有效 activation 必須完整送出一次。既有 Enter／mention IME 行為、其他 mode、backend API 與 event format 不變。

第三輪 Gate B 獨立 Reviewer reviewed exact identity `9d8fcf9eefa683a724bde590e22d171cc0b47171..f5d75fe7ee26b89dd65e2269dc37660ad6e8ec13` 並判定 `pass`，無新 findings；前兩輪發現的 pointercancel 與 disabled/no-click stale guard 已由後續 red／green commits 修正。變更檔案為 `frontend/src/components/ChatroomComposer.vue` 與 `frontend/tests/e2e/chatroom.spec.ts`；main merge commit 為 `77caeb6`。驗證：post-merge focused Chromium 13.23／13.23a／13.23b／13.23c／13.23d／13.24／13.25 **7/7**、frontend unit **162/162**、`npm run build` 通過、`git diff --check` 通過；Reviewer 另確認真實 Chromium mouse／emulated touch 的 pointer identity 與 keyboard／programmatic click 邊界。未驗證 full frontend E2E、full backend suite、實體行動裝置／輔助科技與真人中文輸入法操作；backend 未修改。本項為小型 `.scratch` scoped fix，沒有建立 OpenSpec change；目前狀態為 **`implemented / awaiting acceptance`**。

### #94②③④⑤⑥⑦⑨⑩ closeout／accepted / done（2026-08-07）

本批只處理 backlog 94 的前端測試防護、文案／呈現修正與純 helper 重構；不改 backend API、event schema 或會議執行語意。各項均先由 Executor 以 TDD 產生 red evidence，再由獨立 Reviewer 審查 exact implementation identity。Human Owner 於 2026-08-07 確認「驗收通過」，本批統一標記為 **`accepted / done`**。

- **#94⑤ 窄視窗 warning 裁切**：red `f49600b` → green `2425059`；Reviewer Bacon 審查 `24497f1..2425059`，`pass`；main merge `e86a2fc`。post-merge focused Chromium **1/1**、frontend unit **162/162**、build／diff check 綠。
- **#94④ 空模型 warning 中文化**：red `b1f7cb1` → green `7a27bcb`；Reviewer Galileo 審查 `e86a2fc..7a27bcb`，`pass`；main merge `5f25b71`。post-merge focused Chromium **3/3**、frontend unit **162/162**、build／diff check 綠。
- **#94⑥ assignment update failure 中文化**：red `169babb` → green `b836c41`；Reviewer Cicero 審查 `5f25b71..b836c41`，`pass`；main merge `e38a06a`。post-merge focused Chromium **1/1**、frontend unit **162/162**、build／diff check 綠。
- **#94⑦ disabled model select 原因提示**：最終 green `e25e0f9`；Reviewer Linnaeus 審查 `e38a06a..e25e0f9`，`pass`；main merge `cbc21e1`。post-merge focused Chromium **1/1**、courtroom 回歸 **1/1**、frontend unit **162/162**、build／diff check 綠。
- **#94② courtroom warning 專用 role-name coverage**：red `a7c32c4` → green `9ac0f95`；Reviewer Lagrange 審查 `cbc21e1..9ac0f95`，`pass`；main merge `ff11542`。post-merge courtroom focused **2/2**、frontend unit **162/162**、build／diff check 綠。
- **#94③ Chairman／Space info button coverage**：coverage `0036b70`，red `8219ae0` → green `6cea84f`；Reviewer Raman 審查 `ff11542..6cea84f`，`pass`；main merge `4811fc1`。一般工作區與 courtroom focused Chromium **2/2**、frontend unit **162/162**、build／diff check 綠，未改產品程式。
- **#94⑨ 共用 assignment warning projection**：初始 red `7d043de` → green `b5bc63e`，follow-up red `5d8c86a` → final green `238b905`；Reviewer Nash 審查 `4811fc1..238b905`，`pass`；main merge `349a7c9`。focused unit **3/3**、frontend unit **165/165**、build／diff check 綠；兩元件共用單一純 helper，並覆蓋真正無 fallback 的分支。
- **#94⑩ server participant model replacement 命名與 API**：rename green `23088ff`，follow-up red `5a43955` → final green `14af025`；Reviewer Mendel 審查 `349a7c9..14af025`，`pass`；main merge `5e3a756`。`replaceServerParticipantModels` 只接收 server participants，frontend unit **165/165**、focused helper **16/16**、build／diff check 綠，舊名稱無 live source 引用。

本批主線目前 HEAD 為 `d9ce06e`（implementation merge `5e3a756` 加 closeout docs）。未驗證範圍：本批純前端 helper／unit／呈現修正未重跑完整 Chromium E2E、完整 backend suite、實體輔助科技測試；不影響 Gate B verdict 與 Human Owner 已完成的本批驗收。

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

**#103 Slice 3 Executor implementation（2026-08-10）**：以固定 base `521d6c1398da449ed1fa2920aae62cb49e5785d7` 在 `.worktrees/chatroom-explicit-sources-slice3` 實作 source projection、chat sources API、canonical attachment/evidence refs、mirror suppression、same-label retention、kind-specific readability、Host ACL marker persistence/fallback、send-time source validation、bounded `chatroom-source-context/v1` metadata and prompt excerpts、optional `chat-message/v1.attachment_refs` validation，以及 composer `#` autocomplete／citation chip presentation。Tasks 3.1–3.6 已在本分支標記完成；3.7 reader activation／historical unavailable UI 的完整瀏覽器驗證與 3.8 end-to-end regression 尚未完成，未宣告 Gate B 或 acceptance。Focused backend source/routing/runner tests **41 passed**；frontend unit **172 passed**；production build、OpenSpec strict validation、`git diff --check` 通過。Full backend suite、focused Chromium E2E、direct browser smoke 與獨立 Gate B review 尚未執行。

**#103 Slice 3 continuation（2026-08-10）**：承接 partial HEAD `38aa81e`，保留並先執行新增 red source projection tests，完成 linked evidence active/ACL inheritance、invalid explicit Host marker rejection、deterministic relevant-segment retrieval、per-invocation budget consumption、frozen snapshot citation allow-list／parse-retry diagnostics、public source autocomplete insertion and keyboard seams、historical citation unavailable/read-target highlighting，以及 exact emoji + `@顧問` + `#待辦總覽.md` Chromium test。Relevant backend API/case-material/runner suite **318 passed**；frontend unit **178 passed**；production build、OpenSpec strict、diff check passed. The focused Chromium test is listed and type-valid but not executed because this worktree has no browser binary and the bounded local Chromium download stalled at 10%; therefore 3.7/3.8 remain unchecked and this is only a Gate-B candidate, not Gate B or Human acceptance.
