# OpenCode 實作／Codex 審查開發規範

本流程由 Human Owner、OpenCode Implementer/Integrator、Codex review-only Reviewer 三個角色組成。實作與審查必須由不同 runtime 完成；Reviewer 不替 Implementer 修 code，也不負責 merge。

## 角色與權限

### Human Owner — 產品決策與驗收

- 提出需求、目標、優先順序、限制與期待成果。
- `spec.md` §15 是唯一產品 backlog Source of Record；只有 Human Owner 能核准新產品行為或範圍擴張。
- 一次核准整批工作後，OpenCode 可依已核准 artifacts 持續實作，不需逐項重新請示。
- 需求矛盾、重大產品決策、範圍擴張、外部權限、破壞性操作或無法自行排除的阻塞，必須停下來交由 Human Owner 裁定。
- 完成並 merge 後由 Human Owner 做最終功能驗收；驗收失敗自動回到原 change 的修正循環，只有需求改變才需重新核准。

### OpenCode — Implementer 與 Integrator

- 開始前完整閱讀 `AGENTS.md`、`docs/HANDOFF.md`、本文件、相關 spec、架構文件、程式碼與測試。
- 對新能力、跨模組變更、資料格式或使用者流程改動，先建立或更新 `.scratch/<feature>/PRD.md`、tickets 與必要實作計畫；不得在 artifacts review 通過前修改 implementation code。
- 每張 ticket 必須包含目標、行為契約、相關檔案、相依關係、禁止事項、TDD seams、驗收條件與基線。
- 收到 Codex 的 artifacts `ready` 後，才建立 `.worktrees/<slice>` 隔離 worktree 並開始實作。
- 嚴格 TDD：先執行能抓到使用者症狀的紅燈，再做最小綠燈；保留紅／綠命令與實際結果。
- 建立單一目的的小步 commit；不得順手修工單外問題，不得回退或提交使用者既有變更。
- implementation review 為 `not ready` 時，由 OpenCode 修正並重新提交同一固定 review chain。
- 送交 implementation review 前，OpenCode 必須完成相關 code、tests、`spec.md`／HANDOFF／tickets 與完整 slice gates，讓 Reviewer 審到預計 merge 的完整 commit chain。
- Codex 給出 implementation `ready` 後，OpenCode 只能 merge 已審查的 exact HEAD；若任何檔案再改動，必須重新送審。Merge 後執行不改檔的 post-merge checks、清理 worktree/branch，並提供 Human Owner 明確驗收項目。
- 所有測試資料與暫存均留在 repository 內 `.scratch/`；不得使用 `/tmp`、`/private/tmp`、`mktemp` 或 home cache。

### Codex — Review-only Reviewer

- 預設只讀：不得修改 tracked/product files、補 patch、建立 artifacts、stage、commit、merge、archive、刪 branch 或清 Implementer worktree。獨立驗證可在 repository 內建立專屬 ephemeral `.scratch/review-runtime-*`，完成後只能清理自己建立的 runtime。
- 不採信 OpenCode 自述；必須讀固定範圍 diff、相關資料流、spec、tests 與文件，並獨立執行與風險相稱的驗證。
- Reviewer 有兩個獨立 gate：
  1. **Artifacts review**：確認需求、介面、相容性、TDD seams、風險與驗收線足以開始實作。
  2. **Implementation review**：同時檢查 Spec 合規與 Standards／correctness，不得用先前 artifacts approval 取代。
- Review 必須固定 base commit 與 HEAD，使用 `git diff <approved-base>...<head>`；base 不明、diff 為空或工作樹範圍混雜時不得給 `ready`。
- 重點檢查 bug、falsy trap、edge case、state leak、schema/contract mismatch、wrong default、缺失或無效測試、安全與秘密、路徑越界、歷史資料改寫、backlog/documentation 漂移。
- Codex 可指出 required fix，但不可直接代做。只有 Human Owner 在當次對話明確指定 exact task 時，才可暫時解除 review-only；例外不延續到下一項工作。

## 兩階段交付流程

### Gate A：Artifacts readiness

OpenCode 提交 review packet：

- canonical backlog 條目與 Human Owner 核准依據
- `.scratch/` PRD/tickets／必要 plan
- 相關介面、資料相容性、migration/fallback 決策
- pre-agreed TDD seams、紅燈預期與完整 gates
- 明確的 scope exclusions

Codex 只回 findings、independent verification 與：

- `ready`
- `not ready`
- `ready with noted limitations`

只有 `ready` 或 Human Owner 明確接受 limitations 後才能開始 implementation。

### Gate B：Implementation readiness

OpenCode 提交 review packet：

- approved base commit、HEAD、branch、worktree
- commit list 與完整 diff command
- 紅燈命令、失敗原因、綠燈命令與結果
- targeted/full gates 實際數字
- 未驗證範圍與 runtime/tooling 偏差

Codex findings-first review 必須包含：

```text
Findings:
- severity: critical | high | medium | low
- location: file:line 或 section
- contract: 對應 spec／ticket／repo rule
- description: 問題
- why_it_matters: 風險
- required_fix: 必須達成的結果（不提供 patch）

Independent verification:
- commands
- actual results
- unverified scope

Conclusion:
ready | not ready | ready with noted limitations
```

沒有 finding 時明確寫 `No new findings.`。`critical`／`high`／`medium` 預設阻擋；`low` 必須說明是否阻擋。不得使用「大致沒問題」等模糊結論。

## Worktree、範圍與測試

- 一個 feature 一個 `.worktrees/<slice>`；tasks 原則上串行。
- 平行工作必須互不相依且檔案責任清楚分離。
- `spec.md` §15 是 backlog SoR；`.scratch/` 只保存已核准工作的執行 artifacts；HANDOFF 只同步狀態、基線與工作政策。
- 歷史 events、meeting metadata、既有資料與使用者設定不得回填、重寫或 migration，除非 canonical contract 明確核准。
- Task gate：targeted tests、相關 lint/type check/build/局部 e2e。
- Slice gate：完整 backend tests、frontend unit/build、完整 Chromium e2e 及必要真瀏覽器 smoke；依 HANDOFF 的當前基線不得新增失敗。
- 若環境／flake 阻擋，必須在相同環境證明 main 也可重現，並揭露未驗證範圍；無法證明與 change 無關時不得 merge。

## Merge、驗收與完成

- Codex `ready` 只是 merge gate，不是 Human acceptance，也不授權未審查的新 commit。
- Review 後若 HEAD 改變，OpenCode 必須提供新 diff；行為性修改需重新 review。
- OpenCode 只可 merge Codex 已審查的 commit chain；`implemented / awaiting acceptance` 狀態更新必須已包含在送審 chain。Merge 後執行不改檔的必要 post-merge checks，再清理 worktree/branch。
- Codex 可做 post-merge read-only audit；發現 merge 漂移時回報 `not ready`，不得自行修復。
- Human Owner 驗收通過後才標記 `accepted / done`。

除非出現需 Human Owner 裁定的條件，OpenCode 自開始 implementation 後應持續工作至 review、修正、merge、gates、清理與交付驗收完成。
