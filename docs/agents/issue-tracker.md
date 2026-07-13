# Issue tracker: Local Markdown

`spec.md` §15 是唯一的 canonical product backlog Source of Record（SoR）。`.scratch/` 是已核准工作的 PRD/ticket 執行區，不是另一份產品 backlog；`docs/HANDOFF.md` 只記錄當前狀態、驗收基線與目前已核准批次。

任何 deferred product work 若仍可能實作，必須先同步記錄到 `spec.md` §15，再建立或更新 `.scratch/` 下對應的 PRD/ticket。執行完成後，狀態可在 ticket 留下完成紀錄，產品 backlog 的完成標記仍回寫 `spec.md` §15。

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The PRD is `.scratch/<feature-slug>/PRD.md`
- Implementation issues are `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is recorded as a `Status:` line near the top of each issue file (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

確認工作已在 `spec.md` §15 被選定或核准後，建立新檔於 `.scratch/<feature-slug>/`（必要時建立目錄）。不要把 `.scratch/` 檔案當成產品 backlog 的新增來源。

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` - the Notes / Decisions-so-far / Fog body.
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
