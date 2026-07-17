# Pytest workspace temporary-directory guard

Status: implemented / awaiting acceptance

## 目的

所有 repository pytest 執行都必須把 Python tempfile 與 pytest `tmp_path` 放在目前 repo／worktree 的 `.scratch/pytest-runtime/`；不得再依賴 macOS 系統 `/tmp` 或 `/private/var/folders/...`。

## 行為契約

- 未傳 `--basetemp` 時，自動使用目前 checkout 的 `.scratch/pytest-runtime/cases`。
- pytest process 內的 `TMPDIR`／`tempfile.gettempdir()` 使用目前 checkout 的 `.scratch/pytest-runtime/system`。
- 明確傳入 checkout 內的 `--basetemp` 時保留該選擇。
- 明確傳入 checkout 外的 `--basetemp` 時，在 collection／建立目錄前拒絕並顯示清楚錯誤。
- main 與每個 worktree 各自解析自己的 repository root，不得共用 temp root。
- runtime path 必須被 git ignore；不改 production application startup。

## 驗證

- CLI/default probe 驗證 `tmp_path`、`TMPDIR`、`tempfile.gettempdir()` 都在 checkout 內。
- CLI/external basetemp red-green probe 使用 Human Owner 已授權的確切外部 pytest temp path，guard 必須拒絕且路徑保持不存在。
- 完整 backend suite 通過，且未顯式設定 TMPDIR 時仍不建立 workspace 外 pytest artifacts。
