# 03 — 帶明確問題的定向角色追問

Status: implemented / awaiting acceptance

Blocked by: 01, 02

## Goal

讓「請角色回應」具有明確對象與問題，不再重跑該角色原本的 phase template。

## Interface

- `POST /meetings/{id}/roles/{role}/respond` body 改為 `{instruction: string}`；空白回 `422`，不接受 models 代替 instruction。
- Runner `respond_as_role` 接收 instruction，先 append Human 定向指示事件：`step_id=human-directed-message`、`interaction_type=directed-role-instruction`、`target_role_id`、content。
- 回應事件保留既有 `directed-N-{role}-response` event step ID，另存 `in_response_to_event_id` 指向 Human 指示。
- 使用共用 `directed_role_response.md`，內容包含 role display name、goal、該角色可見案卷、必要 prior transcript、最新 instruction 與該角色 output schema；不得使用 courtroom_defense/rebuttal/verdict 等 phase template。
- 角色 drawer 提供 textarea 與「請〈中文角色名〉回答」；instruction 必填。一般主席發言仍是 broadcast，兩者不可混淆。
- role sequence 維持既有語意與順序，不在本票改成多 instruction composer。

## TDD seams

- Runner seam：Defense 定向追問的 prompt 含指定 instruction、goal 與可見案卷，且不含 phase-template 專屬 task；兩事件 linkage 正確。
- Backend HTTP seam：空白 instruction 422、未知 role、legacy goal gate、成功 response events。
- Playwright seam：未輸入問題不可送出；送出後 timeline/role output 顯示「辯護律師回應主席追問」，內容針對問題；重整後 instruction/linkage 仍可見。

## Forbidden

- 不改寫舊 directed events。
- 不加入付費呼叫測試；使用 mock adapter。
- 不改 sequence preset 行為。
