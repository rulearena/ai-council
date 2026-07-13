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
79. 案卷 Phase 2（僅在卷宗量超出 context window 才做）：檢索/摘要層（RAG）。Phase 1 刻意不做——個人使用量級全文注入即可，先上 RAG 是過度工程
80. 證據編號引用：案卷文件賦予「證物一/證物二」式編號，prompt 要求角色引用時帶錨點——與 backlog 65（豐富裁決結構）銜接，依賴 78（已完成 2026-07-13）
81. **案卷容量限制設定化與建立前提示**：單份/總量 hard limit 改由環境變數設定，預設提高為 50,000/120,000 字元；後端公開實際限制，New Case 顯示每份與總量、粗估 token/context 風險，超限時 inline 阻擋並保留後端 detail。仍採全文注入，不包含 RAG（2026-07-13 已核准）

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
