# 01 — Enforce workspace-local pytest temp

Type: task
Status: open
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
