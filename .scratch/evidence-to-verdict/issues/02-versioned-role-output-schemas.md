# 版本化角色輸出契約

Status: ready-for-agent
Blocked by: 01

## Goal

完成 backlog 63/64 的基礎能力：runner 能按 mode role 選取 versioned output schema，並在不破壞 `role-output/v1` 或舊事件的前提下保存 schema identity。

## Behavior contract

- 建立單一 schema registry/codec seam；`role-output/v1` 的 JSON schema literal、hash 與 parser 行為保持現況。
- `ModeRole` 增加 optional `output_schema`，缺省解析成 `role-output/v1`；GET `/modes` 投影 resolved schema ID。
- modes.yaml 若引用 registry 不存在的 ID，catalog load 失敗且錯誤指出 mode/role/schema。
- relay、parallel、retry、directed response、role sequence 都按實際 step role 選 schema；required schema prompt、parse codec、event `output_schema_id`/hash 必須一致。
- 舊事件缺少 `output_schema_id` 時 read/transcript/frontend 視為 `role-output/v1`；不 migration rewrite。
- 本 slice 只提供 v1 registry 能力，不新增 rich verdict 行為。

## Files likely involved

- `backend/ai_council/prompting/parser.py`
- 新的 prompting schema module（命名由 Executor 依現有結構選擇）
- `backend/ai_council/meetings/modes.py`
- `backend/ai_council/meetings/runner.py`
- `backend/ai_council/api.py`
- `backend/tests/test_prompting.py`
- `backend/tests/test_mode_catalog.py`
- `backend/tests/test_meeting_runner.py`
- `backend/tests/test_api.py`
- `config/modes.yaml`
- `frontend/src/api.ts`

## Forbidden

- 不更改 `role-output/v1` literal 或既有 `output_schema_hash`。
- 不依 template name 猜 schema。
- 不讓 retry/direct/sequence 使用 hard-coded default 繞過 role schema。
- 不重寫既有 events；不在此 slice 實作 rich verdict UI。

## TDD cases

1. 未宣告 schema 的 mode role resolved 為 `role-output/v1`，既有 hash literal 不變。
2. 未知 schema ID 使 modes catalog public load seam 失敗。
3. relay 與 parallel completed events 具有 `output_schema_id=role-output/v1`，prompt schema/hash 與 parser 相同。
4. directed、sequence、failed retry 走同一 selection；以至少一個非預設 test-only schema 證明不是 hard-coded。
5. 缺少 schema ID 的舊事件仍能由 meeting API 與 transcript 投影。

## Acceptance

- prompting/mode/runner/API targeted tests green。
- backend full pytest green。
- frontend build green。
- Reviewer verdict pass。

## Comments
