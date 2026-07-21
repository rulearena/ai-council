# 多代理自主開發規範

本流程由 Human Owner、Orchestrator、Executor、Reviewer 四個角色組成。需求達成共同理解後，代理團隊應持續自主開發至完成，不要求 Human Owner 逐步確認。

## 角色綁定（廠商解耦）

本文件與 `docs/agent-prompts/` 只描述角色，不指名任何 AI 廠商或模型。哪個 AI 執行哪個角色，由 Human Owner 在該工具的視窗啟動 session 時明確指定（例如開頭直接說「你現在是 reviewer」），並提供對應的角色 prompt。

角色不得從 `AGENTS.md`、runtime 名稱、模型身份或工具可用性自行推斷；未指定角色時一律維持唯讀並詢問 Human Owner。Executor 與 Reviewer 必須保持獨立（不同 agent session），並在完成報告揭露任何執行者替代情況。某個角色的執行者不可用（額度、故障）時，由 Human Owner 決定等待、換綁定或親自處理，其他角色不得自行頂替。

## 角色總覽

各角色的完整職責、邊界與輸出格式住在各自的 prompt 檔，本文件不重複：

| 角色 | 一句話職責 | 角色 prompt |
|---|---|---|
| Human Owner | 提出需求、做產品決策、最終驗收 | 無（人類） |
| Orchestrator | 需求討論、登錄 backlog、設計切工單、仲裁 findings、整合與 merge | `docs/agent-prompts/orchestrator.md` |
| Executor | 依工單建立 artifacts、TDD 實作、依 review 修正 | `docs/agent-prompts/executor.md` |
| Reviewer | 獨立審查 Gate A／Gate B／Closeout，輸出 Verdict | `docs/agent-prompts/reviewer.md` |

## Human Owner — 需求與驗收

- 提出產品需求、目標、優先順序、限制條件與期待成果。
- 新功能、跨模組變更、資料格式或使用者流程改動，可要求 Orchestrator 進行需求釐清（先探索式討論、後逐項 grilling；細節見 orchestrator prompt）。
- 最終產品決策由 Human Owner 做出；確認雙方達成共同理解後，授權代理團隊開始自主開發。
- 一次核准整批 backlog 後，代理團隊可依順序連續完成，不需逐項重新取得授權。
- 完成後由 Human Owner 進行最終功能驗收；驗收失敗視為原需求尚未完成，自動進入修正循環；只有需求本身改變時才重新 grilling。

## 開發流程

1. **需求討論**：Human Owner ↔ Orchestrator 釐清與壓力測試，收斂後由 Orchestrator 登錄 `spec.md` §15（唯一產品 backlog Source of Record）。
2. **Artifacts（大型 change）**：Executor 建立 OpenSpec proposal、delta specs、design、tasks，提交 artifacts commit 後停止；小型 scoped fix 走 `.scratch/` 工單。
3. **Gate A**：Reviewer 審查 artifacts，回覆 Verdict；`pass` 前 Executor 不得寫 implementation code。
4. **實作**：Executor 在指定 worktree 依 tasks 嚴格 TDD，小步 commit，逐 task 回報 Orchestrator。
5. **Gate B**：全部 tasks 與 slice gates 完成後，Executor 備妥 review packet，Reviewer 對固定 base...HEAD 審查，回覆 Verdict。
6. **Merge**：Gate B `pass` 後由 Orchestrator merge exact reviewed HEAD 到 main，執行 post-merge checks，標記 `implemented / awaiting acceptance`。
7. **驗收**：Orchestrator 向 Human Owner 列出可操作的驗收項目；Human Owner 驗收。
8. **Closeout**：驗收通過標記 `accepted / done` 後，Executor 建立獨立 closeout worktree 執行 sync 與 archive；另一個獨立 Reviewer session 做 closeout review；`pass` 後由 Orchestrator fast-forward merge。

Verdict 的固定格式與各 gate 的檢查細項見 reviewer prompt；review packet 的內容要求見 executor prompt。

## 退件與升級

- Blocking/Major findings 必須修復；Minor 由 Orchestrator 決定立即處理或加入 backlog；Nit 不阻擋 merge。
- 前兩次退件交回原 Executor 修復，再由 Reviewer 獨立複驗；無法恢復原 agent 時，以工單、commit 與 findings 重建上下文。
- 同一問題退件兩次後，由 Orchestrator 判斷是規格、架構或實作品質問題。
- Orchestrator 可指定 Reviewer 的執行者擔任 escalation fixer，但不得讓它審查自己的修正；escalation fixer 的變更由 Orchestrator 或另一個獨立 Reviewer 複驗。
- 審查意見有爭議時，由 Orchestrator 依 spec、測試證據、既有慣例與相容性要求裁決。

## Worktree 與範圍

- 所有功能在 repository 內指定的 `.worktrees/<slice>` 開發。
- 預設一個 slice 一個 worktree，tasks 串行執行。
- 平行 tasks 必須互不相依、檔案範圍清楚分離，並各自使用獨立 worktree 與 branch。
- 不得覆寫、清除或回退來源不明的既有變更。
- 歷史 events、meeting metadata、既有資料與使用者設定不得回填、重寫或 migration，除非 canonical contract 明確核准。
- 相鄰問題原則上加入 backlog；只有不修就無法完成需求、會造成安全問題或破壞相容性時才能納入目前 slice。
- 所有 OpenSpec CLI 必須透過 `scripts/openspec-local`；不得直接呼叫裸 `openspec`、不得使用 `--force`。OpenSpec 與 `.scratch/` 都不是新增需求來源。

## 驗收與完成

- Task 關卡：targeted tests 與相關 build、lint、局部 e2e 通過，commit 完整。
- Slice 關卡：完整 backend tests、frontend build、完整 e2e 及必要瀏覽器 smoke test 通過。
- 驗收數字以開始開發時的 main 為基線，不得新增失敗，新增測試必須全部通過。
- 若既有 flake 或環境問題阻擋驗收，只有在相同環境的 main 可重現、targeted tests 通過且沒有新增失敗時才可 merge，並須揭露證據與未驗證範圍。
- 無法證明失敗與本次變更無關時不得 merge，應回報 Human Owner。
- OpenSpec 預設允許帶 warning archive 的行為在本專案一律禁止；archive 必須留到 Human Owner 驗收通過（`accepted / done`）之後。
- 最終更新 spec、backlog、handoff，清理 branch/worktree，並提交成果、驗證證據、已知限制與驗收方式。

除非出現需求矛盾、重大產品決策、範圍擴張、外部權限、破壞性操作或無法自行排除的阻塞，代理團隊從開發開始後應持續工作，直到整批核准項目完成並交付 Human Owner 驗收。
