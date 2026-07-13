# Model Config Management（spec §17）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（或 executing-plans）task-by-task 實作本計畫。

**Goal:** 讓使用者從 Settings 的「模型管理」分頁完成模型設定的新增/編輯/刪除/測試，取代手動編輯 `config/models.yaml`（spec.md §17，backlog 19）。

**Architecture:** `config/models.yaml` 仍是唯一真相來源，API 寫入即原子改寫該檔（temp + rename）。後端補齊 CRUD 缺口：`POST /models`（建立）、`PUT /models/{id}` 改為 update-only、422 逐欄驗證、寫入後 status 重設 unknown、DELETE 回傳 warning。前端 SettingsModal 引入分頁結構，新增 ModelManagerPanel（列表 + 動態表單 + 刪除確認）。

**Tech Stack:** FastAPI + PyYAML + pytest（backend）；Vue 3 + TypeScript + Playwright（frontend）。

**執行環境：**
- Worktree：`/Users/chrischiu/SynologyDrive/Project/AI_Council-worktrees/model-config-mgmt`（branch `model-config-mgmt`，基於 e9bcab3——slice B 已合入）
- 後端測試：`cd backend && /Users/chrischiu/SynologyDrive/Project/AI_Council/backend/.venv/bin/python -m pytest tests/ -q`（worktree 無 venv，pytest `pythonpath=["."]` 會 import worktree 程式碼）。基線：**158 passed**。
- 前端：`cd frontend && npm install && npm run build`；e2e 基線 **24/24**——起法：隔離 port 起後端（`AI_COUNCIL_DATA_DIR=$(mktemp -d)`、模型設定用 `config/models.yaml.example`——內含 mock-fast/mock-slow/mock-broken）與 vite，`E2E_BASE_URL=http://127.0.0.1:<port> PLAYWRIGHT_BROWSERS_PATH=/Users/chrischiu/SynologyDrive/Project/AI_Council/frontend/.cache/ms-playwright npx playwright test`。主 repo 的 3009/5009 可能被 dev server 佔用，一律用空閒 port。

**與 spec §17 原文的兩個既定偏差（已裁定，照此實作）：**
1. §17.2 說 adapter 限 `mock | openai-compatible-http | subscription-cli`——**過時**。程式碼的 `SUPPORTED_ADAPTERS`（`backend/ai_council/models/config.py:10`）已含 `anthropic-http`、`gemini-http`（§17 定稿後才加入）。驗證以 `SUPPORTED_ADAPTERS` 為準，兩個 http 系 adapter 的必填欄位同 `openai-compatible-http`（`validate_model_config` 已涵蓋）。
2. §17.2 的 DELETE「回應附 warning 欄位」與現行 204 No Content 衝突——DELETE 改回傳 **200 + JSON body** `{"id": ..., "warning": <str|null>}`（更新既有 204 斷言）。

**相容注意：** 現行 `PUT /models/{id}` 是 upsert（不存在就建立）且驗證錯誤回 400（api.py:112-119 有專門把 PUT /models 的 RequestValidationError 降為 400 的 handler）。本計畫把 PUT 改 update-only（未知 id → 404）、驗證錯誤統一 **422 逐欄**（移除該 400 特例）。前端目前沒有任何呼叫 PUT/DELETE /models 的地方（只有 getModels/testModel），破壞面僅限測試檔，一併更新。

---

## Phase 1 — Backend

### Task 1: 原子寫入 `models.yaml`（temp + rename）

**Files:**
- Modify: `backend/ai_council/models/config.py`（`ModelConfigRepository._write_config`，約 line 96-101）
- Test: `backend/tests/test_model_config_repository.py`

**Step 1: 寫 failing test**（沿用該檔既有 fixture 風格，先讀它）：

```python
def test_write_failure_leaves_existing_file_intact(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "models.yaml"
    repository = ModelConfigRepository(config_path)
    repository.save_model(ModelConfig(id="keep-me", adapter="mock"))
    original = config_path.read_text(encoding="utf-8")

    def explode(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("ai_council.models.config.yaml.safe_dump", explode)

    with pytest.raises(RuntimeError):
        repository.save_model(ModelConfig(id="new-one", adapter="mock"))

    assert config_path.read_text(encoding="utf-8") == original
    leftovers = [p for p in tmp_path.iterdir() if p.name != "models.yaml"]
    assert leftovers == []  # 不留半成品 temp 檔


def test_atomic_write_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    repository = ModelConfigRepository(config_path)
    repository.save_model(ModelConfig(id="a", adapter="mock"))
    repository.save_model(ModelConfig(id="b", adapter="mock"))
    assert [m.id for m in repository.list_models()] == ["a", "b"]
```

**Step 2:** 跑 `pytest tests/test_model_config_repository.py -q` → 第一個測試 FAIL（現在 write_text 直寫，safe_dump 炸掉時檔案雖沒壞，但注意：現行實作 `safe_dump` 在 `write_text` 參數內先執行，所以原檔其實不會壞——**先跑確認實際 fail 形態**；若現行已 pass，改成 monkeypatch `Path.write_text` 於 dump 後失敗的變體來逼出「寫一半」情境，或直接斷言 temp+rename 實作細節：monkeypatch `os.replace` 記錄呼叫。以「測試能區分直寫與原子寫」為準）。

**Step 3: 實作** `_write_config`：

```python
    def _write_config(self, raw_config: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = yaml.safe_dump(raw_config, sort_keys=False, allow_unicode=True)
        temp_path = self.config_path.with_name(f".{self.config_path.name}.tmp")
        try:
            temp_path.write_text(serialized, encoding="utf-8")
            os.replace(temp_path, self.config_path)
        finally:
            temp_path.unlink(missing_ok=True)
```

（頂部 `import os`。）

**Step 4:** 全套 pytest → 綠（158 + 2）。

**Step 5:** `git add -A && git commit -m "feat: atomic write for models.yaml"`（所有 commit 結尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`）

### Task 2: 逐欄驗證 + `POST /models` + `PUT` 改 update-only + status 重設（TDD）

**Files:**
- Modify: `backend/ai_council/models/config.py`（新增 `validate_model_config_fields`）
- Modify: `backend/ai_council/api.py`
- Test: `backend/tests/test_api.py`、`backend/tests/test_model_config_repository.py`

**Step 1: failing tests**（test_api.py 新增；同時更新既有兩個測試——`test_model_config_crud_endpoints_update_models_yaml` 建立改用 POST、`test_model_config_crud_reports_validation_errors` 斷言 400 → 422 逐欄結構）：

```python
def test_post_models_creates_and_resets_status(tmp_path):
    # POST /models {"id": "qwen", "adapter": "openai-compatible-http", base_url, model}
    # → 201；GET /models 含之；再 POST 同 id → 422，detail 內含 {"field": "id", ...}
    # status 重設：先 POST /models/{id}/test 讓 health store 有記錄（available），
    # 再 PUT 更新該 model → 回應 status == "unknown" 且 GET /models 中也是 unknown

def test_post_models_validates_id_format(tmp_path):
    # id "bad id!"（含空白/驚嘆號）→ 422，detail 含 field "id"
    # id "-leading-dash" → 422（regex ^[A-Za-z0-9][A-Za-z0-9_.-]*$）

def test_put_models_is_update_only(tmp_path):
    # PUT /models/never-created {...合法 body...} → 404

def test_model_validation_errors_are_per_field_422(tmp_path):
    # POST {"id": "x", "adapter": "openai-compatible-http"}（缺 base_url/model）
    # → 422，detail 是 list，含 {"field": "base_url", ...} 與 {"field": "model", ...}
    # POST {"id": "y", "adapter": "no-such-adapter"} → 422，field "adapter"
    # POST {"id": "z", "adapter": "subscription-cli"}（缺 command）→ 422，field "command"
```

**Step 2:** 跑 → FAIL。

**Step 3: 實作**：

1. `config.py` 新增（**不動**既有 `validate_model_config`——repository 層仍用它守住手動路徑）：

```python
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def validate_model_config_fields(model: ModelConfig) -> list[dict[str, str]]:
    """Per-field validation for the management API (spec 17.2). Returns [] when valid."""
    errors: list[dict[str, str]] = []
    if not MODEL_ID_PATTERN.match(model.id or ""):
        errors.append({"field": "id", "message": "id must match ^[A-Za-z0-9][A-Za-z0-9_.-]*$"})
    if model.adapter not in SUPPORTED_ADAPTERS:
        errors.append({"field": "adapter", "message": f"Unknown adapter: {model.adapter}"})
    elif model.adapter in {"openai-compatible-http", "anthropic-http", "gemini-http"}:
        if not model.base_url:
            errors.append({"field": "base_url", "message": f"{model.adapter} requires base_url"})
        if not model.model:
            errors.append({"field": "model", "message": f"{model.adapter} requires model"})
    elif model.adapter == "subscription-cli":
        if not model.command:
            errors.append({"field": "command", "message": "subscription-cli requires command"})
        elif not any("{prompt}" in argument for argument in model.command):
            errors.append({"field": "command", "message": "command requires a {prompt} placeholder"})
    if model.pricing is not None:
        if not model.pricing.currency.strip():
            errors.append({"field": "pricing.currency", "message": "currency is required"})
        if model.pricing.input_per_1m_tokens < 0:
            errors.append({"field": "pricing.input_per_1m_tokens", "message": "must be non-negative"})
        if model.pricing.output_per_1m_tokens < 0:
            errors.append({"field": "pricing.output_per_1m_tokens", "message": "must be non-negative"})
    if model.timeout_seconds <= 0:
        errors.append({"field": "timeout_seconds", "message": "must be positive"})
    return errors
```

2. `api.py`：
   - `UpsertModelConfigRequest` 保留；新增 `CreateModelConfigRequest(UpsertModelConfigRequest)` 加 `id: str` 欄位。
   - 共用 helper `save_model_or_422(model: ModelConfig, *, expect_existing: bool | None)`：跑 `validate_model_config_fields` → 非空 raise `HTTPException(422, detail=errors)`；查 `model_repository.list_models()` 判斷存在性——POST 時已存在 → 422 `[{"field": "id", "message": "already exists"}]`；PUT 時不存在 → 404；通過後 `model_repository.save_model(model)`、`model_health.clear(model.id)`、回 `project_model_config(model, None)`（health None → status 取 model.status == "unknown"）。
   - `@app.post("/models", status_code=201)`。
   - `PUT /models/{model_config_id}` 改走同 helper（update-only）。
   - `ModelHealthCheckStore` 加 `clear(model_id)`（with lock, pop）。
   - 移除 api.py:112-119 的 RequestValidationError PUT→400 特例（pydantic body 形狀錯誤回歸 FastAPI 預設 422）；grep 測試中對此行為的斷言一併更新。
   - `save_model` 現在可能 raise `ModelConfigError`（repository 層 validate）——理論上 fields 驗證已擋掉，保留 try/except 轉 422（single-field 未知欄位 fallback：`[{"field": "", "message": str(error)}]`）。

**Step 4:** 全套 pytest → 綠。

**Step 5:** commit：`feat: model management API with per-field validation`

### Task 3: DELETE 引用警告 + 200 JSON 回應（TDD）

**Files:**
- Modify: `backend/ai_council/api.py`（delete_model endpoint）
- Test: `backend/tests/test_api.py`

**Step 1: failing tests**：

```python
def test_delete_model_returns_warning_when_referenced_by_open_meeting(tmp_path):
    # 建 meeting（POST /meetings，red-blue）→ start 用 mock-fast 跑完（wait_for_activity "completed"）
    # → DELETE /models/mock-fast → 200，body["warning"] 非空且含該 meeting_id
    # → GET /models 確認已刪除

def test_delete_model_no_warning_when_meeting_closed(tmp_path):
    # 同上但先 POST /meetings/{id}/close → DELETE → 200，body["warning"] is None

def test_delete_unknown_model_still_404(tmp_path): ...
```

同時更新既有 `test_model_config_crud_endpoints_update_models_yaml` 的 `deleted.status_code == 204` → `200`。

**Step 2:** 跑 → FAIL。

**Step 3: 實作** delete endpoint：

```python
    @app.delete("/models/{model_config_id}")
    def delete_model(model_config_id: str) -> dict[str, Any]:
        if not model_repository.delete_model(model_config_id):
            raise HTTPException(status_code=404, detail=f"Unknown model: {model_config_id}")
        model_health.clear(model_config_id)
        referencing = open_meetings_referencing_model(
            metadata_store, repository, model_config_id
        )
        warning = None
        if referencing:
            warning = (
                f"Model is the latest selection in {len(referencing)} open meeting(s): "
                + ", ".join(referencing[:5])
            )
        return {"id": model_config_id, "warning": warning}
```

helper（module-level 純函式，比照 api.py 慣例）：「最近選擇」定義 = open meeting 中**每個 role 最後一個帶 `model_config_id` 的事件**，或 metadata participants 存的 `model_config_id`：

```python
def open_meetings_referencing_model(
    metadata_store: MeetingMetadataStore,
    repository: MeetingRepository,
    model_config_id: str,
) -> list[str]:
    referencing: list[str] = []
    for metadata in metadata_store.list():
        meeting_id = metadata["meeting_id"]
        events = repository.read_events(meeting_id)
        if project_meeting_status(events) != "open":
            continue
        stored = {
            item.get("model_config_id")
            for item in (metadata.get("participants") or [])
            if isinstance(item, dict)
        }
        latest_by_role: dict[str, Any] = {}
        for event in events:
            if isinstance(event.get("model_config_id"), str):
                latest_by_role[str(event.get("role"))] = event["model_config_id"]
        if model_config_id in stored or model_config_id in latest_by_role.values():
            referencing.append(meeting_id)
    return referencing
```

**Step 4:** 全套 pytest → 綠。

**Step 5:** commit：`feat: delete model warns when referenced by open meetings`

## Phase 2 — Frontend

### Task 4: api.ts CRUD functions + useCouncil 模型清單 sanitize

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/composables/useCouncil.ts`

1. api.ts（先讀既有 `ModelConfig` 型別與 postJson/getJson helper；缺 put/delete helper 就比照補 `putJson`/`deleteJson`）：

```ts
export type ModelConfigPayload = {
  adapter: string
  base_url?: string | null
  model?: string | null
  api_key_env?: string | null
  supports_json_mode?: boolean
  extra_body?: Record<string, unknown>
  pricing?: { currency: string; input_per_1m_tokens: number; output_per_1m_tokens: number } | null
  command?: string[] | null
  timeout_seconds?: number
}

export async function createModel(id: string, payload: ModelConfigPayload): Promise<ModelConfig> {
  return postJson('/models', { id, ...payload })
}
export async function updateModel(id: string, payload: ModelConfigPayload): Promise<ModelConfig> {
  return putJson(`/models/${id}`, payload)
}
export async function deleteModel(id: string): Promise<{ id: string; warning: string | null }> {
  return deleteJson(`/models/${id}`)
}
```

注意錯誤處理：422 的 `detail` 是 `[{field, message}]` 陣列——確認既有 fetch helper 拋錯時保留 response body（讀 helper 現況，必要時讓錯誤物件帶 `detail`，供表單顯示逐欄錯誤）。

2. useCouncil.ts：
   - 抽出/確認 `refreshModels()`（重抓 GET /models 更新 `models` ref）供管理面板寫入成功後呼叫（现有初始載入邏輯重用，不要複製貼上）。
   - **選擇 sanitize**：models 變動後，`selectedModels` 中指向已不存在 id 的 role fallback 到清單第一個模型（§17.3）。現有 watch 只補空 key 不清 stale id——擴充：

```ts
watch([councilRoles, models], ([roles]) => {
  const first = models.value[0]?.id ?? ''
  const valid = new Set(models.value.map((m) => m.id))
  selectedModels.value = Object.fromEntries(
    roles.map((role) => {
      const current = selectedModels.value[role]
      return [role, current && valid.has(current) ? current : first]
    }),
  )
  // modelTestResults 補齊維持既有邏輯
}, { immediate: true })
```

（以現檔實際結構為準融合，不要留兩個重疊 watcher。）

**驗證：** `npm run build` 綠。**Commit:** `feat: frontend api client for model management`

### Task 5: SettingsModal 分頁化 + ModelManagerPanel（列表/表單/刪除）

**Files:**
- Modify: `frontend/src/components/SettingsModal.vue`
- Create: `frontend/src/components/ModelManagerPanel.vue`
- Modify: `frontend/src/styles.css`（分頁與表單樣式，沿用既有 design tokens）

1. **SettingsModal 分頁**：頂部兩個 tab 按鈕——「一般」（既有全部內容：場景/角色模型/測試狀態/開發者模式）與「模型管理」（`data-testid="model-manager-tab"`）。`const activeTab = ref<'general' | 'models'>('general')`，modal 重開時重設為 general。tab 按鈕樣式沿用 `btn btn-ghost` 系（讀 styles.css 現況決定，視覺與 modal 內容區隔清楚即可）。
2. **ModelManagerPanel.vue**（inject councilKey 取 `models`、呼叫 api）：
   - **列表**（`data-testid="model-manager-list"`）：每列 id、adapter、`base_url/model`（http 系）或 `command[0]`（cli）摘要、status dot（沿用 `.status-dot[data-status]` 樣式與 `model.status`）、Test 按鈕（呼叫既有 `testModel(id)` api，結果就地顯示在該列）、編輯、刪除（`data-testid="delete-model-button"`，多列時用 `delete-model-button-${id}`——**先確認 e2e 想怎麼選**，統一 per-id testid 較穩）。
   - **新增按鈕**（`data-testid="add-model-button"`）→ 開表單（新增模式）。
   - **表單**（`data-testid="model-form"`）：欄位 id（編輯模式 readonly——spec：id 不可改）、adapter `<select>`（值 = SUPPORTED_ADAPTERS 五種）。依 adapter 動態顯示：mock → 無額外欄位；http 系（openai-compatible-http/anthropic-http/gemini-http）→ base_url、model、api_key_env、supports_json_mode（checkbox）、timeout_seconds；subscription-cli → command（textarea，一行一個 argument，送出時 `split('\n').filter(Boolean)`；載入時 `join('\n')`）、timeout_seconds。
   - `api_key_env` 欄位下方固定顯示安全說明（原文照放）：「此欄位填**環境變數名稱**（如 `OPENAI_API_KEY`），不是 API 金鑰本身。金鑰請設在後端環境變數中，勿貼在此處。」
   - **編輯 round-trip 保真**：開編輯時從 `models` 找到完整物件，把 UI 沒顯示的 `extra_body`/`pricing` 原樣存在表單 state、送 PUT 時帶回——不可默默清掉手動編輯的欄位。
   - **儲存**（`data-testid="model-form-save"`）：新增走 `createModel`、編輯走 `updateModel`；成功 → 關表單 + `refreshModels()`；422 → 逐欄錯誤顯示在對應欄位下（依 `detail[].field` 對應）。
   - **刪除**：`window.confirm('確定刪除模型 ${id}？')` → `deleteModel(id)` → 若回應有 `warning` 就地顯示（inline 警示文字區，**不要用 alert**——瀏覽器 dialog 會擋自動化）→ `refreshModels()`。
3. 角色下拉即時更新由 Task 4 的 sanitize watch 自動達成（同一個 `models` ref）。

**驗證：** `npm run build` 綠 + 真瀏覽器冒煙（隔離 port）：新增一個 mock 模型 → 出現在列表與角色下拉；編輯 timeout；刪除（confirm）→ 從下拉消失且被選中的 role fallback。console 無錯誤。**Commit:** `feat: model manager tab in settings`

### Task 6: e2e（§17.4）

**Files:** Modify `frontend/tests/e2e/control-flow.spec.ts`

新增測試（沿用既有隔離跑法；注意每個 e2e run 的後端 models.yaml 是隔離副本，寫入不會污染 repo）：

1. **CRUD happy path**：Settings → 模型管理 tab → 新增（id `e2e-added-mock`、adapter mock）→ 列表出現 → 「一般」tab 角色下拉含新模型 → 回管理 tab 按該列 Test → status 變 available → 編輯（timeout 改 60）→ 儲存成功 → 刪除（`page.once('dialog', accept)`）→ 列表與角色下拉都消失。
2. **驗證錯誤顯示**：新增 openai-compatible-http 但 base_url/model 留空 → 儲存 → 表單顯示兩個欄位錯誤（斷言錯誤文字可見）、模型未被建立。
3. **刪除 fallback + warning**：把某 role 的選擇改成新增的模型 → （可選：跑一步產生引用）→ 刪除該模型 → 該 role 下拉 fallback 到清單第一個模型。warning 路徑若在 e2e 太重（需跑完會議），後端測試已覆蓋，e2e 斷言 inline warning 區塊存在與否即可視情況納入——以穩定為先，可只驗 fallback。

全套 e2e 綠（24 + 新增 3 = 27 預期）。**Commit:** `test: e2e coverage for model management`

## Phase 3 — 收尾

### Task 7: 全面驗證 + 文件 + review + merge

1. 後端全套 pytest、前端 build、全套 e2e、真瀏覽器冒煙（管理面板 + 既有紅藍/courtroom 流程無回歸）。
2. spec.md §17 開頭狀態行補「——已完成（日期）」；backlog 19 標記完成；README 若提到手動編輯 models.yaml 的說明，補一句 UI 入口。
3. 最終整合審查（Codex `codex exec` 優先，hang 就 fallback Claude reviewer）：範圍 `main...HEAD`，重點——422 契約前後端一致、extra_body/pricing round-trip 不丟資料、原子寫入正確性、與 slice B 功能無互相干擾。
4. Merge 回 main（`--no-ff`）、merge 後在 main 跑全套 pytest、刪 worktree 與 branch（政策：立即 merge 不批次）。
