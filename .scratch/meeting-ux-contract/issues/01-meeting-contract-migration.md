# 01 — Meeting title/goal contract 與明示遷移

Status: ready-for-agent

Blocked by: none

## Goal

建立 title/goal 新契約，讓 title 永不充當 AI 目標，並使舊 meeting 在使用者保存 goal 前不可產生新 AI event。

## Interface

- `POST /meetings`：必填非空白 `title`、`goal`；舊 `topic` 不再是建立契約。
- metadata：新 meeting 保存 `title`、`goal`，不保存 `topic`。
- read model：回傳 `title`、`goal: string | null`、`requires_goal: boolean`。舊 metadata 可將 `topic` 投影成 title 供使用者確認，但 goal 必須為 null。
- `PUT /meetings/{id}/details`：必填非空白 title/goal；單一原子 metadata update，成功後移除 legacy topic。
- start/retry/respond/sequence：metadata 缺 goal 時回 `409`，不得新增 AI event。取消、結案、重新開啟、讀取與刪除不受此 gate 影響。
- Runner/PromptRenderer：公開任務參數改為 goal；所有 prompt 使用 `{{ goal }}`。title 僅用於列表、搜尋與 transcript 標題，不注入角色 prompt。

## Migration rules

- 禁止啟動時、列表讀取時或批次 script 靜默改寫舊 metadata。
- 只有使用者呼叫 details update 才遷移該 meeting。
- 不修改任何 events/case_files。
- 若 metadata 同時存在新欄位與 legacy topic，以完整非空白 title/goal 為權威；成功 update 後刪 topic。

## TDD seams

- Backend HTTP seam：create/get/list/update details，以及四個執行 endpoint 的 409 gate。
- Runner seam：已知 title/goal 不同時，保存的 prompt 包含 goal、不含 title。
- Frontend Playwright seam：新建兩欄必填；開啟 legacy meeting 顯示補目標 UI、執行按鈕停用、保存後可執行且重整仍有效。

## Forbidden

- 不以 `goal = topic` fallback。
- 不改歷史 events。
- 不碰 model config 或 assignment contract。
