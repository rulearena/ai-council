# 02 — 版本化案卷、證據與案件備註

Status: ready-for-agent

Blocked by: 01-deliberation-epochs-restart

Canonical contract: `spec.md` §15 #88；`.scratch/deliberation-lifecycle-ux/PRD.md`

## Outcome

同一 meeting 可持續管理證據與案件備註；穩定引用、版本與停用保留完整歷史，任何審議後變更都必須先選擇適當 restart 才能繼續 AI。

## Public contracts

- 建立 case-material domain seam，作為 evidence/case note 內容唯一 SoT；metadata 只保存安全投影。
- Evidence 有 stable ID、不可重用編號/anchor、active/inactive、active version；每版保存內容、visible roles 與 audit metadata。
- Case note 有 stable ID、版本、active/inactive；可由明示操作將主席訊息提升為 note，但不得修改來源 event。
- HTTP interface 支援新增證據、新版本、停用/恢復、新增/更新 note、promote-to-note；所有 mutation 帶 expected revision。
- Legacy flat case files read-time 投影，不寫盤；第一次明示 mutation 才原子升級。

## Behaviour

- restart 不複製案卷 bytes/records；舊輪仍能看到當時使用的 material revision/version references。
- 已有 active AI output 後，任何會進 prompt 的 material 變更都建立 pending impact；所有 start/respond/sequence/retry/issue judgment/final judgment 在 backend gate 被拒絕。
- 主席必須從 restart current issue、all deliberation 或 rebuild issues 中選擇合法範圍；完成 restart 後解除 gate。
- 普通主席訊息不跨輪；只有 case notes 跨輪並進 prompt。
- 無永久刪除功能；停用資料仍可在歷史檢視。

## TDD seams

- Domain public interface：legacy non-writing projection、first mutation upgrade、version/status、anchor uniqueness、visible roles、limits、optimistic conflict。
- HTTP interface：CRUD-like version operations、revision conflict、promote source immutability。
- Runner observable prompt/gates：active evidence/note injection、inactive exclusion、pending impact blocks every AI path。
- Storage contract：restart 前後 evidence count/identity/content hash 不變。

## Acceptance

- 使用者可在已建立 meeting 新增/改版/停用/恢復證據與維護案件備註。
- 證據修改後 UI 清楚要求 restart，且繞過 UI 的 API 也不能繼續 AI。
- 舊 meeting 能讀取；首次修改才升級，且不改歷史 events。
- records 能解釋每輪使用的 material revision。
- 相關 backend、frontend unit 與 Chromium tests 通過。

## Forbidden

- 不把 evidence 內容同時寫 metadata 與 materials file。
- 不因 restart 複製證據。
- 不 hard-delete 或靜默覆寫版本。

