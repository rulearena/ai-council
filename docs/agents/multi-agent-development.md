# 多代理自主開發規範

本流程由 Human Owner、Orchestrator、Executor、Reviewer 四個角色組成。需求達成共同理解後，代理團隊應持續自主開發至完成，不要求 Human Owner 逐步確認。

預設模型：

- Orchestrator：Codex `gpt-5.6-sol`，reasoning effort `high`
- Executor：Codex `gpt-5.6-luna`
- Reviewer：Codex `gpt-5.6-terra`

模型不可用時可使用能力相近的替代模型，但 Executor 與 Reviewer 必須保持獨立，並在完成報告揭露替代情況。

## Human Owner — 需求與驗收

- 提出產品需求、目標、優先順序、限制條件與期待成果。
- 新功能、跨模組變更、資料格式或使用者流程改動，可要求 Orchestrator 使用 `$grill-me` 釐清方向。
- Grilling 一次處理一項決策；可從程式碼查證的事實由 Orchestrator 自行調查。
- Orchestrator 必須為每個問題提出建議答案、理由與主要取捨，最終產品決策由 Human Owner 做出。
- 確認雙方達成共同理解後，授權代理團隊開始自主開發。
- 一次核准整批 backlog 後，代理團隊可依順序連續完成，不需逐項重新取得授權。
- 完成後由 Human Owner 進行最終功能驗收。
- 驗收失敗視為原需求尚未完成，自動進入修正循環；只有需求本身改變時才重新 grilling。

## Orchestrator — 設計與整合

- 閱讀 AGENTS、handoff、spec、架構文件、程式碼及現有測試。
- 負責架構決策、相容性規則、模組責任、命名慣例、資料模型及 migration 策略。
- 將 slice 拆成可獨立測試、commit 與 review 的 bite-sized tasks。
- 每張工單提供目標、行為契約、相關檔案、相依關係、禁止事項、TDD 案例與驗收條件。
- 只有接口或架構必須固定時才提供程式碼骨架。
- 記錄 main 測試基線、必要 regression tests、瀏覽器情境及不可破壞的相容性規則。
- 仲裁 review findings，將 Blocking/Major 路由回 Executor，決定 Minor 立即修正或列入 backlog。
- 負責整合、merge conflict、完整驗收、merge main、文件更新與 worktree 清理。
- 原則上不實作功能；可處理整合問題、測試基礎設施、純文件及明確低風險修正。
- 開發期間提供不需 Human Owner 回覆的簡短里程碑更新，流程不得因此停下。

## Executor — TDD 實作

- 每個 task 原則上使用一個新的 Executor agent。
- 嚴格依工單實作，不擅自擴大公開行為、資料格式或架構範圍。
- 採 TDD：先建立原因明確的 failing test，再完成最小實作，最後重構。
- 執行 targeted tests，並依範圍執行 lint、type check、build、局部 e2e 或真瀏覽器驗證。
- 建立單一目的的小步 commit，回報 commit SHA、變更摘要、測試指令及實際結果。
- 工單外問題應回報並記入 backlog，不順手修改無關程式碼。
- 只有疑問會改變公開行為、資料格式、相容性、架構或工單範圍時才回報 Orchestrator。
- Review 退件由原 Executor 優先續修；無法恢復原 agent 時，以工單、commit 與 findings 重建上下文。

## Reviewer — 獨立審查

Reviewer 不採信 Executor 自述，必須逐行閱讀 diff、檢查相關資料流並獨立執行驗證。

審查分成兩道關卡：

1. Spec 合規：確認完整符合工單，沒有缺漏、偏離或未授權擴張。
2. 程式品質：檢查正確性、邊界條件、相容性、效能、安全性、測試有效性與註解品質。

固定輸出格式：

```text
Verdict: pass | needs-fixes

Spec findings:
- Blocking / Major / Minor

Quality findings:
- Blocking / Major / Minor / Nit

Independent verification:
- 執行指令
- 實際結果
- 未驗證範圍
```

Blocking/Major 必須修復；Minor 由 Orchestrator 決定立即處理或加入 backlog；Nit 不阻擋 merge。

## 退件與升級

- 前兩次退件交回原 Executor 修復，再由 Reviewer 獨立複驗。
- 同一問題退件兩次後，由 Orchestrator 判斷是規格、架構或實作品質問題。
- Orchestrator 可指定 Reviewer 模型擔任 escalation fixer，但不得讓它審查自己的修正。
- Escalation fixer 的變更由 Orchestrator 或另一個獨立 Reviewer 複驗。
- 審查意見有爭議時，由 Orchestrator 依 spec、測試證據、既有慣例與相容性要求裁決。

## Worktree 與範圍

- 所有功能在 repository 內指定的 `.worktrees/<slice>` 開發。
- 預設一個 slice 一個 worktree，tasks 串行執行。
- 平行 tasks 必須互不相依、檔案範圍清楚分離，並各自使用獨立 worktree 與 branch。
- 不得覆寫、清除或回退來源不明的既有變更。
- 相鄰問題原則上加入 backlog；只有不修就無法完成需求、會造成安全問題或破壞相容性時才能納入目前 slice。

## 驗收與完成

- Task 關卡：targeted tests 與相關 build、lint、局部 e2e 通過，commit 完整。
- Slice 關卡：完整 backend tests、frontend build、完整 e2e 及必要瀏覽器 smoke test 通過。
- 驗收數字以開始開發時的 main 為基線，不得新增失敗，新增測試必須全部通過。
- 若既有 flake 或環境問題阻擋驗收，只有在相同環境的 main 可重現、targeted tests 通過且沒有新增失敗時才可 merge，並須揭露證據與未驗證範圍。
- 無法證明失敗與本次變更無關時不得 merge，應回報 Human Owner。
- 自動驗收與 merge 完成後標記 `implemented / awaiting acceptance`。
- Human Owner 驗收通過後標記 `accepted / done`；驗收失敗則重新開啟。
- 最終更新 spec、backlog、handoff，merge 回 main、清理 branch/worktree，並提交成果、驗證證據、已知限制與驗收方式。
- 純文件、拼字及明確低風險修正可由 Orchestrator 直接完成；涉及執行行為、設定語意、API、測試邏輯或使用者流程時，必須走完整代理流程。

除非出現需求矛盾、重大產品決策、範圍擴張、外部權限、破壞性操作或無法自行排除的阻塞，代理團隊從開發開始後應持續工作，直到整批核准項目完成並交付 Human Owner 驗收。
