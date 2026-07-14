# Meeting assignment 後端 Source of Truth

Status: ready-for-agent
Blocked by: none

## Goal

建立集中解析、更新及提供 runner 使用的 meeting model assignment module。

## Required behavior

- 建立 meeting 時 relay、parallel 的完整 roster 必須有 `model_config_id`；缺漏或未知 model 拒絕。
- `PUT /meetings/{id}/participant-models` 接受完整 `{models: Record<role, model_id>}`，精確驗證 roster 後原子更新，保留 display name、instance prompt 等欄位。
- GET meeting/list 投影 effective assignment、source 與 warning。
- 解析順序：有效 metadata → 僅當 metadata 無值時使用該角色最新一筆帶 model id 的 event → models.yaml 第一筆 → unavailable。
- metadata 指向已刪除 model 時直接 default fallback，不回掃更舊 event。
- `start/respond/sequence/retry` 全部使用 resolved meeting assignment；request body 的舊 `models` 欄位可相容接受，但不得覆蓋。
- Runner 啟動後維持已解析 ModelConfig snapshot；更新只影響後續動作。
- Meeting metadata read-modify-write 需 process-safe、temp+rename，assignment 與 tags/pinned 不互相覆蓋。

## Forbidden

- 不修改、追加或回填既有 events。
- 不把 read-time fallback 悄悄保存進 metadata。
- 不改 runner step、retry、prompt 或 event ID 語意。

## TDD seams

- FastAPI public interface：create/get/list/update/start/respond/sequence/retry。
- MeetingRunner observable event seam：event 的 `model_config_id` 證明實際執行選擇。
- 以獨立 literal fixtures 驗證 legacy recovery、刪除 fallback 與 metadata/events 不變。

## Acceptance

- Targeted API/runner tests 綠，commit 單一目的並回報 red/green 證據。
