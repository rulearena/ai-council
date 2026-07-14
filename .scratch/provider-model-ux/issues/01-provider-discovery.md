# Provider-specific model discovery

Type: task
Status: resolved
Blocked by:

## 目標

讓 Anthropic、Gemini 經既有 discovery HTTP interface 回傳 normalized exact model IDs，並保持 OpenAI-compatible 行為與 secret safety。

## TDD

- 先以 API tests 證明 Anthropic/Gemini preview 與 existing discovery 目前為紅燈。
- 覆蓋 provider headers/query、base URL composition、排序去重、空清單、upstream error、缺 credential env。
- 測試不得連真 provider 或讀 workspace 外環境設定。

## 禁止事項

- 不發 completion、不保存 config、不記錄 API key。
- 不改 meeting/events。

## 驗收

- Targeted backend tests 綠並有 red→green 證據；單一目的 commit。

## 實作結果

- Anthropic discovery 使用 `GET {base_url}/models`、`x-api-key`、固定
  `anthropic-version`，並依 `has_more` / `last_id` 走訪分頁。
- Gemini discovery 使用 `GET {base_url}/models?key=...` 與 `pageToken`，移除
  provider 回傳的 `models/` 前綴，並排除不支援 `generateContent` 的模型。
- 兩者皆經既有 preview / existing endpoints 回傳排序、去重的 exact model IDs；
  空清單、upstream error redaction 與缺 credential env 均有 API regression tests。
- 無 completion、config write、meeting 或 event 變更；所有 HTTP 都以 fake transport。

## Red → Green 證據

- Anthropic preview：新增測試先得 `400 != 200`，實作後 `1 passed`。
- Anthropic existing pagination：新增測試先缺少第二頁 `claude-c`，實作後
  `2 passed`（含 preview regression）。
- Gemini preview pagination：新增測試先得 `400 != 200`，實作後 `1 passed`。
- Gemini existing normalization：新增測試先錯誤包含 embedding-only model，實作後
  `2 passed`（含 preview regression）。
- Targeted discovery：`pytest backend/tests/test_api.py -q -k model_discovery` →
  `18 passed, 103 deselected`。
- API + adapters regression：`pytest backend/tests/test_api.py
  backend/tests/test_model_adapters.py -q` → exit 0；`146 tests collected`。
- 每次 pytest 均設定 `TMPDIR=$WORKTREE/.scratch/pytest-tmp`。
