# 主席操作與逐一爭點法院流程

Status: approved / implementing

Canonical backlog: `spec.md` §15 #87

## 產品價值

讓 Human Owner 以「主席」身分從單一入口控制會議，不必猜測一般發言、指定追問與流程推進的差異；法院模式則以可確認的爭點逐一攻防，避免一次把整案塞給模型而失焦。

## 核准契約

1. 主席 composer 以明確 audience/action 下拉統一補充、全體回應與指定角色回答。
2. title/goal 建立後可編輯；goal 變更只影響未來 prompt，已有 AI output 時需確認並追加 audit event。
3. 「系統設定」與「流程操作」分工；移除模糊且依隱藏狀態變動的「繼續討論」。
4. 法院 meeting 必須先取得、編修並確認爭點清單。
5. 每個爭點依 Prosecutor → Defense → Prosecutor rebuttal 攻防，之後停下等待主席；Judge 只在主席送交後作成 issue ruling。
6. 每個 ruling 後停下，主席手動選擇下一爭點；全部 issue ruled 後才可 final verdict。
7. 舊 courtroom meeting 不改寫歷史，但下一次執行前同樣受 issue setup gate。
8. 非 courtroom modes 行為不變。

## Source of Truth

- `metadata.courtroom_issues`: 主席可編修、排序與確認的 issue definitions。
- `events.jsonl`: issue attack/defense/rebuttal、主席指示、issue ruling、final verdict 與 goal change audit。
- `goal`: 全案最終裁判問題；`current_issue` 只限制當次攻防焦點，不取代 goal。
- final readiness 必須由 confirmed issue roster 與 append-only completed ruling events 投影，不以 frontend memory 判斷。

## 相容與禁止事項

- 不批次回填或重寫舊 metadata/events。
- 不讓 issue draft 自動變成 confirmed roster。
- 不在 chairman note 模式呼叫模型。
- 不讓「全體回應」或 generic start 在 courtroom 繞過 issue gate。
- 不改變非 courtroom mode 的既有 step IDs、runner semantics 或 output schema。
- 所有 runtime/test data 留在 worktree `.scratch/`，不得使用 `/tmp`。

## TDD seams

- HTTP: meeting details、courtroom issue lifecycle、非法 transition、legacy courtroom gate。
- Runner: issue-scoped prompts/events、issue ruling、final verdict gating與 retry linkage。
- Frontend domain: chairman action option/label、courtroom phase/action projection、meeting edit guards。
- Playwright: unified composer、edit title/goal、settings naming、issue draft edit/confirm、逐點停止/next/final、reload recovery。

## 完成條件

- 每張 ticket 以 TDD 完成並有單一目的 commit。
- Standards 與 Spec 兩軸獨立 review 均通過。
- Backend full suite、frontend unit、build、完整 Chromium e2e 與 direct browser smoke 通過。
- merge main 後標記 `implemented / awaiting acceptance` 並清理 worktree/branch/runtime。
