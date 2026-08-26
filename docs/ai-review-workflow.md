# AI 眾議院開發工作流

這份文件定義本專案的 AI 協同開發方式。目標是降低使用者介入：使用者負責說清楚產品需求、做必要產品決策、驗收最終成果；拆工、實作、測試、review、修正與文件同步由 agent 主動完成。

本文件描述的是角色責任，不綁死特定工具或廠商。Codex、Claude 或其他 coding agent 都可以扮演不同角色，依當次任務調整。

> **正式規範優先**：本文件是協作角色與交付流程的摘要；涉及執行行為、設定語意、API、測試邏輯或使用者流程時，優先遵循 [`docs/agents/project-development.md`](multi-agent-development.md) 的 Executor/Reviewer、worktree、TDD 與驗收規範。只有純文件、拼字及明確低風險修正可由 Orchestrator 直接完成。

## 1. 核心原則

- 使用者不是 AI 之間的訊息搬運工。
- Agent 預設自己拆工、實作、測試、review、修正到可交付。
- 只有產品 scope、風險接受、重依賴、外部資源、無法本地驗證等決策才詢問使用者。
- 後端核心邏輯預設 TDD。
- 先不做但未來可能有價值的產品項目要記入 `spec.md` §15；明確不做的項目標為 not planned。`.scratch/` 只保存已核准工作的執行資料。
- Codex、Claude 或其他 agent 可以彈性分配角色，但不得以角色分配取代正式規範要求的 Executor/Reviewer 流程。

## 2. 角色

| 角色 | 職責 |
| --- | --- |
| Human | 提出需求、回答產品決策、驗收最終成果 |
| Orchestrator | 讀規格、拆 ticket、排順序、裁決 review findings、整合交付 |
| Executor | 實作 ticket、寫測試、跑驗證、更新必要文件 |
| Reviewer | 獨立檢查設計、程式碼、測試與規格一致性 |

角色不是固定產品名稱。

目前常見組合：

- 純文件或明確低風險修正：Orchestrator 可直接完成並自我檢查。
- 涉及執行行為的工作：依正式規範使用 Orchestrator、Executor、Reviewer 分工與獨立驗證；不因任務大小省略必要關卡。
- Codex 與 Claude 可以互換角色；原則是責任清楚、review 盡量獨立。

如果 Executor 與 Reviewer 是不同 agent，Reviewer finding 預設由 Orchestrator 裁決並派修；只有需要產品決策或風險接受時才問使用者。

## 3. 預設工作流

一般功能開發預設流程：

```text
需求討論
-> 對齊 spec.md §15
-> 核准批次後拆 PRD / tickets 到 .scratch/
-> 從第一張可執行 ticket 開始
-> TDD 實作
-> 跑相關測試
-> self-review diff
-> 依正式規範完成 independent reviewer 與必要複驗
-> 修 findings
-> 文件/backlog 同步檢查
-> 交付使用者驗收
```

Agent 不需要等使用者逐張核准 ticket。只要 ticket 沒有改變 MVP scope、不需要外部資源、不引入重依賴、不要求使用者接受新風險，就直接開始實作。

## 4. 何時問使用者

必須問使用者：

- 改變 `spec.md` 的 MVP scope 或 non-goals
- 新增重大依賴、服務、資料庫或外部系統
- 需要 API key、帳號、雲端資源、私有服務或其他外部授權
- 改變資料持久化策略或可能造成資料遺失
- 需要接受已知風險或已知限制
- 本地無法驗證但想宣稱完成
- 產品行為有多個合理選項，且無法從既有 spec 判斷

不需要問使用者：

- bug 修復
- 測試失敗修正
- 型別、lint、format 問題
- reviewer 指出的實作缺陷
- 文件與 spec 不一致的修正
- 小型重構
- 補必要測試
- 不改 scope 的 backlog 記錄

## 5. Ticket 與執行區

本專案使用 local markdown issue tracker：

```text
.scratch/<feature-slug>/PRD.md
.scratch/<feature-slug>/issues/<NN>-<slug>.md
```

規則：

- `spec.md` §15 是唯一的 canonical product backlog SoR；`.scratch/` 不是另一份 backlog。
- `.scratch/` 只收錄已核准工作的 PRD、implementation tickets 與執行紀錄；deferred product work 必須先同步到 `spec.md` §15。
- Agent 可依需求自動建立 PRD 與 implementation tickets。
- 每張 implementation ticket 必須包含目標、範圍、驗收方式、測試策略。
- 後端核心 ticket 預設 TDD。
- Ticket 完成後要更新狀態或留下完成紀錄。
- 現階段不做但未來可能有價值的產品項目先放入 `spec.md` §15，再於獲得核准後建立執行 ticket。
- 明確不做或不符合產品方向的項目標為 not planned，不混入 backlog。

## 6. TDD 規則

本專案預設採 TDD，尤其是後端核心。

必須 test-first 的範圍：

- `MeetingRepository`
- `MeetingRunner`
- `TranscriptProjector`
- `PromptRenderer`
- `ModelConfigRepository`
- `ModelAdapter` contract
- retry / cancel / failed step state transitions
- schema validation
- event log append/read/replay

TDD 節奏：

```text
寫 failing test
-> 最小實作讓測試通過
-> refactor
-> 跑相關測試
-> review
-> 修到測試與 review 都通過
```

前端 MVP 不追求完整測試覆蓋，但必須建立穩定 `data-testid` contract，讓之後 Playwright 或 component tests 能可靠定位。

## 7. Review 規則

Review 採兩層制。

每次交付前必做：

- self-review diff
- 跑相關測試
- 檢查文件/backlog 是否需要同步

涉及執行行為的工作，依正式規範必須完成 independent reviewer；以下情況特別需要逐項檢查：

- 後端核心狀態機、persistence、retry、cancel
- model adapter、prompt rendering、schema parser
- 可能造成資料遺失或狀態不一致的變更
- 大範圍重構
- 安全、授權、secret、外部服務相關變更
- 使用者明確要求 review

Reviewer finding 預設由 agent 自己修到通過。只有 finding 會改變產品 scope、引入重依賴、需要外部資源、或要求使用者接受風險時，才交給使用者決策。

## 8. 文件同步

每次完成 ticket 前，agent 必須檢查是否需要更新：

- `spec.md`
- `docs/ai-review-workflow.md`
- `spec.md` §15 的 backlog，以及 `.scratch/` 中對應的 PRD / tickets
- `README.md`
- `config/*.example`
- `prompts/*.md`
- 其他與使用方式或架構決策直接相關的文件

不需要每次都改文件；但交付時要說明文件是否已同步，或為什麼不需要同步。

## 9. 交付格式

每次交付給使用者驗收時，用固定格式回報：

```text
完成什麼
怎麼驗收
測試結果
已知限制 / backlog
是否需要使用者決策
```

如果交付的是 web app，另外提供：

```text
本機 URL
主要操作路徑
```

使用者的主要工作是照驗收方式試用成果，而不是判斷 agent 中間每一步流程是否正確。

## 10. Orchestrator / Executor 分工

角色可依任務安排，但不得以 single-session execution 省略正式規範要求的 Executor/Reviewer 流程。

可由 Orchestrator 直接處理：

- 純文件更新
- 拼字修正
- 明確低風險修正

需要完整 orchestrator/executor/reviewer split：

- 涉及執行行為、設定語意、API、測試邏輯或使用者流程的工作
- 其他依正式規範需要 Executor 與 Reviewer 的工作

分工時的責任：

- Orchestrator 不盲信 Executor 自報，必須親自檢查 diff、跑關鍵測試、確認文件與 ticket 狀態。
- Executor 不應自作主張擴 scope；遇到 scope 邊界要回報 Orchestrator。
- Reviewer 不負責改 code，只指出風險、缺陷、遺漏測試與規格不一致。
- Orchestrator 裁決 reviewer findings，能修就派修；需要產品決策才問使用者。

## 11. Local LLM Executor Canary

本專案可以測試本地 LLM 作為 Executor，但必須先用受控 canary 驗證，不直接讓模型改主 workspace。

候選 local executors：

| id | host | base_url | model |
| --- | --- | --- | --- |
| `qwen27` | `srv-vm` | `http://192.168.50.80:8487/v1` | `bartowski/Qwen_Qwen3.6-27B-GGUF` |
| `ornith` | `srv-nas1` | `http://192.168.50.81:8488/v1` | `deepreinforce-ai/Ornith-1.0-35B-GGUF` |

兩者都是 llama.cpp OpenAI-compatible API，呼叫 `/v1/chat/completions` 時 `model` 欄位必須填上表對應的 model id。

實測注意事項：

- 兩個 endpoint 都可正常回應 `/v1/chat/completions`。
- 如果不關閉 thinking，回應會落在 `reasoning_content`，`content` 可能是空字串。
- 呼叫時應帶 `chat_template_kwargs: { enable_thinking: false }`。不要依賴 `/no_think`，它在先前 benchmark 中被證實不可靠。
- 兩個 endpoint 實測可接受 `response_format: { "type": "json_object" }` 並回傳可解析 JSON。

Canary 規則：

- 同一張小 ticket 可由 `qwen27` 與 `ornith` 平行實作。
- 每個 executor 必須使用獨立 worktree / sandbox。
- Executor 不准 commit / push。
- Executor 不准讀寫 workspace 外部路徑。
- Executor 只能碰 ticket 指定範圍內的檔案。
- Orchestrator 必須比較兩邊 diff、測試結果、scope discipline、文件同步與完成度。
- 不自動採用任何 executor 結果；最終合併由 Orchestrator 決定。
- 本地模型優先使用 JSON file protocol（模型回傳完整檔案內容，由 harness 寫入檔案）；unified diff protocol 僅作備選，因為本地模型較容易產生 malformed patch。

評分標準：

- 是否符合 `spec.md` 與 ticket
- 是否採 TDD，且測試真的覆蓋目標行為
- diff 是否小而清楚
- 是否亂擴 scope
- 錯誤處理是否合理
- 是否同步必要文件/backlog
- 測試輸出是否可信
- 程式碼可維護性

建議第一張 canary ticket：

```text
backend skeleton + MeetingRepository append/read events tests
```

這張 ticket 小、可測，能快速看出 local executor 是否會讀 spec、寫 pytest、處理 JSONL、控制 scope。

## 12. Goal / 長任務保險絲

一般任務不需要 goal。

只有長時間、多 ticket、可無人看管的**已核准批次**，agent 可以依 `docs/agents/project-development.md` 建議使用 goal。產品批次仍須先從 `spec.md` §15 選定並記入 HANDOFF；只有使用者明確同意或要求時才建立 goal。

## 13. 現階段不作為預設的流程

自 2026-07-20 起，新能力、跨模組架構、資料格式與 product-surface change 已採 OpenSpec 作為執行 artifacts；`spec.md` §15 仍是唯一產品 backlog SoR。OpenSpec 的 apply/archive 必須再受 `docs/agents/project-development.md` 的 Codex review 與 Human acceptance gates 約束。

以下流程不作為本專案目前預設，不代表永久不用：

- 每個變更都開 PR
- branch protection / CI required checks
- 未經 Codex Gate A／Gate B 與 Human acceptance 的 OpenSpec apply/archive
- GitNexus impact graph
- 全域 stop hook 強制 review gate
- Dockerized development workflow
- 額外於正式 Chromium slice gate 之外的跨瀏覽器 Playwright matrix
- 在 Human Owner／Implementer／獨立 Reviewer 正式分工之外，再強制增加第四個以上 agent

如果未來專案進入多人協作、正式 production、或有更高安全/合規需求，可以再把其中一部分升級為標準流程。
