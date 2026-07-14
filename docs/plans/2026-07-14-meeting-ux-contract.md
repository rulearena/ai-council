# Meeting title/goal、中文呈現與定向追問實作計畫

**Goal:** 完成 spec.md §15 #86，消除 meeting 識別／AI 任務混用、內部 ID 外洩與無問題內容的定向回應。

**Architecture:** metadata 的新 Source of Truth 為 `title + goal`。API projection 對 legacy topic 只提供 migration view，不提供執行 fallback；一個 details update interface 負責單場原子遷移。Runner 與 PromptRenderer 只接收 goal。前端以集中式 presentation module 將 mode catalog/participant/event 轉成人類 label，避免散落 mapping。定向追問由 runner 保存 targeted Human instruction，再以專用通用 prompt 產生可追溯角色回應。

**Baseline:** main `5f342e8`；backend 291 passed、frontend unit 12 passed、build 通過、Chromium 69 passed。main 的 `config/models.yaml.example` 有 Human Owner 將 Claude timeout 改成 900 秒的未提交變更，本 branch 不碰該檔。

## Pre-agreed TDD seams

1. Backend HTTP interface：meeting create/read/details migration/gates/directed instruction。
2. Runner public interface：goal prompt isolation、targeted Human event + linked role response。
3. Frontend pure presentation interface：role/step/interaction/decision 中文 label。
4. Browser interface：新建、legacy migration、頂欄／copy、中文輸出、定向追問。
5. Transcript download interface：title 與中文固定欄位。

## Delivery order

1. Ticket 01：一個 HTTP test → 一個最小 implementation 的垂直 TDD，完成 metadata contract、migration gate、prompt goal rename；targeted backend tests + build/type checks；commit。
2. Ticket 02：先 pure presentation unit tests，再接 TopBar/Meetings/NewCase/RoleDrawer/CouncilStage/ActionBar 與 transcript；局部 Playwright；commit。
3. Ticket 03：先 runner/API failing tests，完成 instruction event/linkage/generic prompt，再接 role drawer composer；局部 Playwright；commit。
4. Executor 執行 backend full、frontend unit、build、Chromium full 與 workspace-local browser smoke；不得使用 `/tmp`，e2e model config 必須複製到 `.scratch/<unique-runtime>`。
5. Orchestrator 固定 merge-base 後啟動獨立 Standards/Spec reviewers；Blocking/Major 回原 Executor TDD 修復，直到雙軸 pass。
6. 更新 spec #86、PRD/tickets、HANDOFF；確認 merge tree 等同 reviewed tree，合併 main，保留 Human Owner 的 models example 變更並清理 branch/worktree/runtime。

## Browser acceptance script

1. 建立法院 meeting：名稱「土地糾紛案」、目標「判斷被告是否構成無權占有」。頂欄只顯示名稱；複製同時得到名稱與 ID。
2. 確認席位／抽屜顯示檢察官、辯護律師、法官；輸出區塊與步驟無 `Defense`、`courtroom-defense`、`Role Outputs`、`Arguments`。
3. 建立 legacy fixture（metadata 只有 topic），開啟後必須補 goal；保存前開始／追問不可用，保存後重整仍為 title/goal 新契約且 events 未改。
4. 在辯護律師抽屜輸入「請針對遺產稅因果關係補充答辯」並送出；確認 targeted Human instruction 與 linked response，UI 顯示「辯護律師回應主席追問」。
5. 下載逐字稿，確認標題為 meeting title、固定章節中文化，raw 診斷仍可在 Records 查看。
