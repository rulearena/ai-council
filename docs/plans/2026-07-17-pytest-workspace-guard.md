# Pytest workspace guard 實作計畫

Fixed point: `bbccf47`

## Slice 1 — CLI red loop

- 以目前 pytest CLI 實際印出 `tmp_path` 與 `tempfile.gettempdir()`。
- 使用已授權確切外部路徑證明現況接受 external `--basetemp`。

## Slice 2 — Repository guard

- 在 pytest root configuration 設定 checkout-local defaults。
- 在 pytest 建立 basetemp 前驗證 resolved path 位於 checkout root。
- `.gitignore` 忽略固定 runtime root。

## Slice 3 — Verification and review

- default／inside／outside／worktree isolation probes。
- backend full。
- Standards／Spec 雙軸獨立 review。
- merge main、post-merge probe、清理所有 repo-local runtime。
