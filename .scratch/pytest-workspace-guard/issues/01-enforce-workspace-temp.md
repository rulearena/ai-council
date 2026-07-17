# 01 — Enforce workspace-local pytest temp

Type: task
Status: implemented / awaiting acceptance
Blocked by: none

## TDD seams

1. `python -m pytest` CLI default temp resolution。
2. `--basetemp` CLI validation。
3. main/worktree checkout-root isolation。

## 禁止事項

- 不讀取、列出或建立其他 workspace 外路徑。
- external rejection probe 只可引用 Human Owner 已授權並已刪除的確切路徑：
  `/private/var/folders/6_/g4v6317d6j5djb3gdllp9_nm0000gn/T/pytest-of-chrischiu/`。
- 不以 agent 記憶或文件提醒作為唯一防護。
- 不改 application runtime 的 tempfile policy。
- 不修改 `config/models.yaml.example`。

## 完成條件

- 先證明現況 default 會使用 workspace 外 temp 或允許 external basetemp。
- guard 後 default／explicit inside 通過，explicit outside 在建立前拒絕。
- backend full、雙軸 review、main merge、post-merge probe、worktree cleanup。

## Executor notes（2026-07-17）

- Red：repository default 未指定 `--basetemp` 時，沒有固定使用 checkout-local
  `cases`；external `--basetemp` 在 collect-only CLI probe 以 exit 0 被接受。
- Green：`backend/conftest.py` 的 `pytest_configure(tryfirst=True)` 在 builtin
  tmpdir factory 設定前完成路徑驗證，default／explicit inside／external rejection
  三個 CLI regression tests 通過。外部 rejection 在 collection 前回傳 UsageError，
  且已授權 exact path 在 probe 前後皆不存在。
- Checkout isolation：runtime root 由目前 conftest 實體路徑解析，因此 worktree
  probe 寫入該 worktree 自己的 `.scratch/pytest-runtime/`。
- Full gate：`600 passed`（原基線 597 + 新增 3）。
- Safety incident：首次 red subprocess 雖設定 local `TMPDIR`，但 driver 尚未先建立
  該目錄，Python 因而 fallback 到 `/private/tmp/pytest-of-chrischiu/`。Executor
  未讀取、列出或刪除該未授權路徑；已向 Orchestrator 揭露，並修正 driver 在每次
  subprocess 前建立 local system temp。後續所有 probe 均保持 checkout-local。
- Independent review：Standards PASS、Spec PASS；Reviewer 的 unset
  `TMPDIR`／`TMP`／`TEMP`、default、explicit-inside 與 repo-root cwd probes 均解析
  到目前 worktree。工具無 Terra selector，使用 assigned runtime。
