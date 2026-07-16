# 04 — 會議工作區資訊架構與整合體驗

Status: implemented / awaiting acceptance

Blocked by: 01-deliberation-epochs-restart, 02-versioned-case-materials, 03-courtroom-case-profiles

Canonical contract: `spec.md` §15 #88；`.scratch/deliberation-lifecycle-ux/PRD.md`

## Outcome

全域設定、會議資料、案卷、議事紀錄與流程操作各有清楚入口；會議設定以右側抽屜原子儲存，法院下一步與 restart 風險一眼可見。

## Public contracts

- 單一 atomic meeting-settings HTTP interface，payload 含 expected revision、title、goal、case type、scene 與完整 participant model assignments；先全量驗證再一次寫入。
- Frontend meeting-settings draft 是純狀態 seam：hydrate、edit、dirty、validation、locked fields、atomic payload、save/discard/meeting-switch guards。
- Records history selection 與 live meeting state 分離；查看舊 epoch 不得替換 WebSocket/live projection。
- Scene 持久化為 meeting-scoped；legacy 無值 read-time 使用 mode default。

## Behaviour

- TopBar 只顯示會議 title，複製動作可包含 ID；移除橫向 inline editor。
- 全域「系統設定」只保留 Provider/模型管理與進階「顯示事件原始資料」，後者預設 off 並清楚標示只影響畫面。
- Meeting 次導覽：會議設定、案卷與證據（count）、議事紀錄。
- 會議設定使用右抽屜、垂直分組、本地草稿、sticky 儲存/放棄；dirty close、切換 meeting 或新 request 前確認。
- Title 在非執行中可改；goal/case type 在爭點確認前可改，之後唯讀；rebuild 解鎖。
- Workflow operations 收納 restart/rebuild/sequence/cancel/close/reopen，不與系統設定重複。
- Evidence impact UI 解釋三種 restart 的後果；法院 awaiting judgment 顯示 sticky primary CTA。
- 375px 與桌面寬度均可操作，不重現整頁橫幅設定表單。

## TDD seams

- Meeting settings HTTP：atomic success、validation failure no partial write、revision conflict、lock rules。
- Frontend pure state：dirty close、atomic payload、reload/switch isolation、case lock、records/live isolation。
- Playwright：settings IA、evidence count/version/impact、records epochs、普通 restart、法院三 restart、民刑事 flow、sticky judgment、375px。
- Direct browser：非 test runner 驗證 restart 不複製證據、民事角色與 sticky CTA。

## Acceptance

- 系統設定與會議設定不再混用，頂部 UI 不被 editor 撐開。
- 一次儲存不會產生 title/goal/model 的半套狀態；reload/switch 保持各 meeting 設定。
- 使用者可找到案卷、歷史輪次、流程 restart 與等待法官的下一步。
- Advanced 原始事件預設關閉且不影響 AI。
- 相關 frontend unit、build、Chromium、direct browser 與 backend regression 全部通過。

## Forbidden

- 不用多個 immediate-save requests 模擬 atomic save。
- 不讓 history browsing 污染 live state。
- 不把 meeting-scoped 選項留在全域系統設定。
