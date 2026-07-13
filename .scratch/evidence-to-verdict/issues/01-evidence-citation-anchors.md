# 證據編號與引用錨點

Status: ready-for-agent
Blocked by: none

## Goal

完成 backlog 80。每份 Case File 具有穩定、可見、可在模型輸出中引用的錨點；角色使用案卷主張時，prompt 明確要求附錨點。

## Behavior contract

- 新建 meeting 的案卷按 request 順序取得 `evidence_index`（從 1 開始）與衍生 `citation_anchor`，顯示格式為 `[證物一]`、`[證物二]`……。
- `POST /meetings`、`GET /meetings/{id}` 與 metadata manifest 投影 index/anchor。
- 舊 `case_files.json` 或 metadata manifest 缺少新欄位時，read projection 依現有順序衍生，不改寫來源檔。
- role-scoped prompt block 標題包含 anchor，例如 `### [證物一] 事故時間軸`。
- 所有使用 `{{ case_files }}` 的角色 prompt 都有共通引用指示：引用案卷中的事實或主張時必須帶對應 `[證物…]`；不可假造不存在的錨點。
- 前端案卷建立區與 meeting data type 可顯示/承接 anchor；不要求讓使用者編輯編號。

## Files likely involved

- `backend/ai_council/api.py`
- `backend/tests/test_api.py`
- `frontend/src/api.ts`
- `frontend/src/components/NewCaseModal.vue`
- `frontend/tests/e2e/control-flow.spec.ts`
- `prompts/*.md`

## Forbidden

- 不改既有 case file `id`。
- 不更改案卷可見角色或大小限制語意。
- 不做 RAG、全文索引或 citation correctness 的 LLM 二次驗證。
- 不改 output schema。

## TDD cases

1. API 建立兩份案卷後回傳固定 literal anchors `[證物一]`、`[證物二]`，stored manifest/full file 保有 index。
2. 將 fixture 中新欄位移除後，GET 仍衍生相同 anchors。
3. 執行 role-scoped meeting，completed prompt 只含該角色可見案卷及其正確 anchor，且含引用指示。
4. Frontend e2e 建立兩份案卷時顯示唯讀證物標籤，建立後 API 投影一致。

## Acceptance

- targeted backend API tests green。
- frontend build green。
- targeted case-file e2e green。
- Reviewer verdict pass。

## Comments
