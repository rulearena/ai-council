# Issue tracker 與 OpenSpec

`spec.md` §15 是唯一 canonical product backlog Source of Record（SoR）。OpenSpec 與 `.scratch/` 都是執行 artifacts，不得自行新增或擴張產品 backlog；`docs/HANDOFF.md` 只記錄當前狀態、驗收基線與已核准批次。

## 新工作使用哪一種 artifacts

- 新能力、跨模組架構、資料格式或 product-surface change：使用 `openspec/changes/<change-name>/`。
- 小型 bugfix、acceptance fix、純文件或不需要完整 proposal/design/spec/tasks 的 scoped change：可使用 `.scratch/<feature>/`。
- 既有 `.scratch/` 是歷史執行紀錄，不搬移、不回填、不批次轉換成 OpenSpec。
- Deferred product work 必須先記錄在 `spec.md` §15；Human Owner 核准後才能建立 OpenSpec change 或 `.scratch` artifacts。

## OpenSpec change lifecycle

1. Human Owner 核准 `spec.md` §15 的範圍。
2. Implementer 使用 `scripts/openspec-local new change <name>` 或 `/opsx-propose` 建立 proposal、delta specs、design、tasks。
3. 提交 artifacts commit，停止；Codex Reviewer 執行 Gate A。
4. Gate A `ready` 後，Implementer 才可在隔離 worktree執行 `/opsx-apply`。
5. Implementation、tests、docs、tasks 與完整 gates 完成後，Codex Reviewer 執行 Gate B。
6. Gate B `ready` 後由 Implementer merge exact reviewed HEAD。
7. Human Owner 驗收通過後，Implementer 從最新 main 建立獨立 `.worktrees/<change>-acceptance-closeout`，在同一 closeout chain 中把 `spec.md` §15 標記 `accepted / done`、sync main specs、archive change 並提交。
8. 不同 Codex session 以 closeout base 與 HEAD 執行固定 diff review；`ready` 後由 Implementer fast-forward merge exact reviewed HEAD，只做 read-only post-merge checks，然後清理 closeout worktree／branch。任何 closeout 修改都不得直接寫 main，Review 後變更亦須重審。

OpenSpec 的「apply-ready」只表示 schema artifacts 齊全，不代表本專案 Gate A 已通過。OpenSpec 的「tasks complete」也不代表可 merge 或 archive。

## OpenSpec 執行規則

- 一律透過 `scripts/openspec-local` 呼叫 CLI；wrapper 會停用 telemetry，把 HOME、全部 XDG runtime directories 與 TMPDIR 固定在目前 checkout 的 `.scratch/openspec-runtime/`，anchor 至 wrapper 所在 checkout，並拒絕 `--force`。
- 禁止直接呼叫裸 `openspec`，禁止 `--force`，禁止使用 workspace 外 config/cache。
- `openspec update` 可能覆寫生成的 agent commands/skills；執行前必須獲得 Human Owner 明確授權，執行後整個治理 diff 必須重新 review。
- `openspec/changes/archive/` 只保存 Human Owner 已驗收的 change。
- `openspec/specs/` 是已驗收 capability contracts 的投影，不取代 `spec.md` §15 backlog。

## Existing `.scratch/` conventions

- One scoped fix per directory: `.scratch/<feature-slug>/`
- PRD: `.scratch/<feature-slug>/PRD.md`
- Issues: `.scratch/<feature-slug>/issues/<NN>-<slug>.md`
- Comments append under `## Comments`; status remains local execution state。

Skills 若要求「publish to issue tracker」，先確認工作是否為 OpenSpec-sized change。大型 change 寫入 `openspec/changes/`；小型 scoped fix 才使用 `.scratch/`。兩者都不得繞過 `spec.md` §15 與 Human Owner approval。

## Wayfinding operations

`/wayfinder` 仍使用 `.scratch/<effort>/map.md` 與 `.scratch/<effort>/issues/` 作為調查 map。Wayfinding 結論若形成可實作產品工作，仍須先進 `spec.md` §15，再依規模建立 OpenSpec change 或 scoped fix artifacts。
