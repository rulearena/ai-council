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
- external-to-checkout rejection probe 必須完全留在真 workspace 內，以 nested fake
  checkout 驗證 containment，不得保存或引用任何個人系統路徑。
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
  三個 CLI regression tests 通過。持久化 rejection test 在真 worktree 內建立 nested
  fake checkout，並將 candidate 放在 fake checkout 外、真 worktree 內；CLI 在
  collection 前回傳 UsageError，candidate 前後皆不存在，不引用 workspace 外路徑。
- Checkout isolation：runtime root 由目前 conftest 實體路徑解析，因此 worktree
  probe 寫入該 worktree 自己的 `.scratch/pytest-runtime/`。
- Full gate：`600 passed`（原基線 597 + 新增 3）。
- Safety incident：首次 red subprocess 雖設定 local `TMPDIR`，但 driver 尚未先建立
  該目錄，Python 因而 fallback 到 system-managed external temp。Executor 未讀取、
  列出或刪除該未授權內容；已向 Orchestrator 揭露，並修正 driver 在每次 subprocess
  前建立 local system temp。後續所有 probe 均保持 checkout-local。
- Independent review：Standards PASS、Spec PASS；Reviewer 的 unset
  `TMPDIR`／`TMP`／`TEMP`、default、explicit-inside 與 repo-root cwd probes 均解析
  到目前 worktree。Portable nested-checkout rejection probe 複驗通過，repository
  不保存 username、個人外部路徑或淘汰 probe 描述。工具無 Terra selector，使用
  assigned runtime。
- Post-merge：main 未設定 `TMPDIR`／`--basetemp` 直接執行完整 backend；第一次為
  既有 0.5 秒 startup health-check 負載門檻單一失敗，該案例單跑通過，第二次完整
  suite `600 passed`。實際 pytest runtime 全部位於 main `.scratch/pytest-runtime/`，
  完成後已精確清理；feature worktree／branch 亦已移除。
