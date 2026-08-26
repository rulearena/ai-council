[English](#contributing) | [繁體中文](#貢獻指南)

# 貢獻指南 / Contributing

歡迎對 AI Council 提交貢獻！以下為建議流程。

## 開始之前 / Before You Start

- 請先閱讀 `README.md` 或 `README.zh-TW.md` 了解專案架構與本地開發方式。
- 若要提交重大變更，建議先開 issue 討論方向。

## 開發流程 / Development Workflow

1. Fork 並建立功能分支（例如 `feature/add-new-mode`）。
2. 在 `backend/` 使用 `uv sync --extra dev`，在 `frontend/` 使用 `npm install`。
3. 維持測試通過：`scripts/test_all.sh`（必要時加上 `RUN_E2E=1`）。
4. 保持提交訊息清楚，並在 PR 說明改動原因與測試方式。

## 品質要求 / Quality Expectations

- 盡量補充或更新相關文件。
- 若涉及模型連接器或 UI 行為，建議附上截圖或 log 說明。
- 不要提交敏感金鑰或 token。

## 行為準則 / Code of Conduct

請遵守 `CODE_OF_CONDUCT.md`。

## 安全問題 / Security Issues

若發現安全問題，請勿公開揭露，改以 `SECURITY.md` 方式回報。
