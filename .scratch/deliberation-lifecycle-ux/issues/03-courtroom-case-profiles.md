# 03 — 民刑事案件 profile 與法院語意

Status: ready-for-agent

Blocked by: 01-deliberation-epochs-restart, 02-versioned-case-materials

Canonical contract: `spec.md` §15 #88；`.scratch/deliberation-lifecycle-ux/PRD.md`

## Outcome

Courtroom 由使用者明示選擇民事或刑事，使用正確角色、三段攻防、法官整理爭點與案件別結果；爭點判斷永遠由主席手動送交法官。

## Public contracts

- 建立 `CourtroomCaseProfile` domain seam，以 `civil|criminal` 集中角色顯示、phase labels、prompt/schema ID、爭點 outcome 與 final renderer。
- internal role IDs 保持 Prosecutor/Defense/Judge；case profile 只負責案件別產品語意。
- 新 courtroom create 必須帶 case type；legacy missing type 可查看，但所有 AI/retry/judgment 前要求明示選型，禁止推論。
- 既有已確認 docket 且缺 type 的 legacy meeting 允許一次明示選型；不修改舊 events。
- 新 events snapshot case type、role display 與 phase display；舊 events 不因後來選型而 retroactive relabel。

## Behaviour

- 民事顯示原告代理人/被告代理人/法官；刑事顯示檢察官/辯護人/法官。
- 民刑事爭點草稿都由 Judge assignment 產生，主席確認；確認前可改 goal/case type，切 type 使整份未確認 draft 失效；確認後唯讀，rebuild 才解鎖。
- 每個爭點固定：主張方陳述 → 答辯方答辯 → 主張方限縮反駁；反駁不得加入新主張/新證據，完成後停在 awaiting judgment。
- sticky 主動作是「請法官判斷此爭點」，不自動裁判；主席可先指定答辯方補充。
- 單一爭點稱「法官判斷」，只有全案稱「最終判決」。
- Criminal final 按指控呈現罪責，不含具體刑期、罰金或刑罰；可列量刑考量。Civil final 呈現請求成立範圍、義務與證據；金額必須有 evidence refs 與 calculation basis，否則拒絕 unsupported value。

## TDD seams

- Case-profile public interface：role/phase/prompt/schema/presentation projection。
- Meeting HTTP interface：create required type、legacy explicit selection、switch/lock/rebuild rules。
- Runner observable prompts/events：Judge draft、三 phase、manual judgment pause、all retry paths use same profile。
- Versioned codecs/renderers：civil and criminal valid/invalid outputs；mock adapter supports both schemas。
- Frontend pure projections：case labels、outcomes、final rendering、sticky CTA。

## Acceptance

- 民事與刑事各能完成一個爭點至全案 final，角色與文案正確。
- awaiting judgment 不會自動前進，主席按 CTA 後才產生 issue judgment。
- legacy missing case type 無法啟動 AI，且 UI 提供明確選型。
- criminal 不產生具體 penalty；civil 不發明未有依據的金額。
- 相關 backend、frontend unit 與 Chromium tests 通過。

## Forbidden

- 不用 title/goal/events 推論 case type。
- 不複製 civil/criminal 成兩個 modes。
- 不改 internal role IDs 或 retroactively relabel 舊 events。
