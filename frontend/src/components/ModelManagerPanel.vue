<script setup lang="ts">
// Model management tab (spec.md §17.2/17.3, docs/plans/2026-07-13-model-config-management.md
// Task 5) - lets a user create/edit/delete/test entries in config/models.yaml through the
// API added in Tasks 1-3 instead of hand-editing the file. Reuses useCouncil's `models`
// ref and `refreshModels()` (Task 4) as the single source of truth: every write here calls
// refreshModels() afterward rather than mutating `models` locally, so the role dropdowns in
// SettingsModal's 一般 tab (and the sanitize watch in useCouncil.ts that fallback-clears a
// deleted model's role selections) pick up the change through the exact same path a fresh
// page load would.
import { inject, ref } from 'vue'
import { councilKey } from '../composables/useCouncil'
import { ApiError, createModel, deleteModel, testModel, updateModel, type ModelConfig, type ModelConfigPayload } from '../api'

const store = inject(councilKey)!
const { models, refreshModels } = store

// Mirrors backend/ai_council/models/config.py's SUPPORTED_ADAPTERS - kept as a literal
// list (not fetched) since the set is small and rarely changes; adding a sixth adapter
// there needs a matching edit here regardless of where the list lives.
const ADAPTERS = ['mock', 'openai-compatible-http', 'anthropic-http', 'gemini-http', 'subscription-cli'] as const
const HTTP_ADAPTERS = new Set(['openai-compatible-http', 'anthropic-http', 'gemini-http'])

function isHttpAdapter(adapter: string): boolean {
  return HTTP_ADAPTERS.has(adapter)
}

function isCliAdapter(adapter: string): boolean {
  return adapter === 'subscription-cli'
}

function modelSummary(model: ModelConfig): string {
  if (isHttpAdapter(model.adapter)) return [model.base_url, model.model].filter(Boolean).join(' / ')
  if (isCliAdapter(model.adapter)) return model.command?.[0] ?? ''
  return ''
}

// -------- delete --------

// Row-level delete removes the row itself, so a per-row inline warning has nowhere to
// live once refreshModels() runs - shown as a panel-level banner instead (still not a
// window.alert, which would block Playwright's automation).
const deleteWarning = ref<string | null>(null)
const deleteError = ref('')
const deletingId = ref<string | null>(null)

async function handleDelete(id: string) {
  if (!window.confirm(`確定刪除模型 ${id}？`)) return
  deleteWarning.value = null
  deleteError.value = ''
  deletingId.value = id
  try {
    const result = await deleteModel(id)
    deleteWarning.value = result.warning
    await refreshModels()
  } catch (caught) {
    deleteError.value = caught instanceof Error ? caught.message : String(caught)
  } finally {
    deletingId.value = null
  }
}

// -------- test --------

const testingId = ref<string | null>(null)
const testErrors = ref<Record<string, string>>({})

async function handleTest(id: string) {
  testingId.value = id
  testErrors.value = { ...testErrors.value, [id]: '' }
  try {
    // Health result lands in the backend's health store; re-fetching models (rather than
    // reading testModel's own response) is what updates this row's status dot, matching
    // GET /models projecting model_health.get(model.id) onto each entry.
    await testModel(id)
    await refreshModels()
  } catch (caught) {
    testErrors.value = { ...testErrors.value, [id]: caught instanceof Error ? caught.message : String(caught) }
  } finally {
    testingId.value = null
  }
}

// -------- create/edit form --------

type FormMode = 'create' | 'edit'
const showForm = ref(false)
const formMode = ref<FormMode>('create')
const formId = ref('')
const formAdapter = ref<string>('mock')
const formBaseUrl = ref('')
const formModel = ref('')
const formApiKeyEnv = ref('')
const formSupportsJsonMode = ref(false)
const formTimeoutSeconds = ref(120)
const formCommandText = ref('')
// Not rendered as inputs (round-trip only, per Task 5's fidelity requirement below) -
// carried through from the model being edited and sent back unchanged on save so a PUT
// from this form never silently drops extra_body/pricing a human hand-edited into
// models.yaml.
const formExtraBody = ref<Record<string, unknown>>({})
const formPricing = ref<ModelConfig['pricing']>(null)

const saving = ref(false)
const fieldErrors = ref<Record<string, string>>({})
const formGeneralError = ref('')

const KNOWN_FIELDS = ['id', 'adapter', 'base_url', 'model', 'command', 'timeout_seconds']

function fieldError(field: string): string {
  return fieldErrors.value[field] ?? ''
}

function resetFormErrors() {
  fieldErrors.value = {}
  formGeneralError.value = ''
}

function openCreateForm() {
  formMode.value = 'create'
  formId.value = ''
  formAdapter.value = 'mock'
  formBaseUrl.value = ''
  formModel.value = ''
  formApiKeyEnv.value = ''
  formSupportsJsonMode.value = false
  formTimeoutSeconds.value = 120
  formCommandText.value = ''
  formExtraBody.value = {}
  formPricing.value = null
  resetFormErrors()
  showForm.value = true
}

function openEditForm(model: ModelConfig) {
  formMode.value = 'edit'
  formId.value = model.id
  formAdapter.value = model.adapter
  formBaseUrl.value = model.base_url ?? ''
  formModel.value = model.model ?? ''
  formApiKeyEnv.value = model.api_key_env ?? ''
  formSupportsJsonMode.value = model.supports_json_mode
  formTimeoutSeconds.value = model.timeout_seconds
  formCommandText.value = (model.command ?? []).join('\n')
  formExtraBody.value = model.extra_body ?? {}
  formPricing.value = model.pricing ?? null
  resetFormErrors()
  showForm.value = true
}

function closeForm() {
  showForm.value = false
}

function buildPayload(): ModelConfigPayload {
  const payload: ModelConfigPayload = {
    adapter: formAdapter.value,
    timeout_seconds: formTimeoutSeconds.value,
    extra_body: formExtraBody.value,
    pricing: formPricing.value,
  }
  if (isHttpAdapter(formAdapter.value)) {
    payload.base_url = formBaseUrl.value.trim() || null
    payload.model = formModel.value.trim() || null
    payload.api_key_env = formApiKeyEnv.value.trim() || null
    payload.supports_json_mode = formSupportsJsonMode.value
  } else if (isCliAdapter(formAdapter.value)) {
    payload.command = formCommandText.value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
  }
  return payload
}

function applySaveError(caught: unknown) {
  if (caught instanceof ApiError && caught.status === 422 && Array.isArray(caught.detail)) {
    const nextFieldErrors: Record<string, string> = {}
    const general: string[] = []
    for (const item of caught.detail as Array<{ field?: string; message?: string }>) {
      const field = item.field ?? ''
      const message = item.message ?? String(item)
      if (KNOWN_FIELDS.includes(field)) {
        nextFieldErrors[field] = message
      } else {
        general.push(message)
      }
    }
    fieldErrors.value = nextFieldErrors
    formGeneralError.value = general.join('; ')
  } else {
    formGeneralError.value = caught instanceof Error ? caught.message : String(caught)
  }
}

async function saveForm() {
  resetFormErrors()
  saving.value = true
  try {
    const payload = buildPayload()
    if (formMode.value === 'create') {
      await createModel(formId.value.trim(), payload)
    } else {
      await updateModel(formId.value.trim(), payload)
    }
    await refreshModels()
    closeForm()
  } catch (caught) {
    applySaveError(caught)
  } finally {
    saving.value = false
  }
}

</script>

<template>
  <section class="model-manager-panel">
    <p v-if="deleteWarning" class="error" data-testid="delete-model-warning">{{ deleteWarning }}</p>
    <p v-if="deleteError" class="error" data-testid="delete-model-error">{{ deleteError }}</p>

    <div class="model-manager-list" data-testid="model-manager-list">
      <div
        v-for="model in models"
        :key="model.id"
        class="model-manager-row"
        data-testid="model-manager-row"
        :data-model-id="model.id"
      >
        <span class="model-manager-id">
          <i class="status-dot" :data-status="model.status" aria-hidden="true"></i>
          {{ model.id }}
        </span>
        <span class="model-manager-adapter">{{ model.adapter }}</span>
        <span class="model-manager-summary">{{ modelSummary(model) }}</span>
        <em v-if="testErrors[model.id]" class="model-manager-test-error">{{ testErrors[model.id] }}</em>
        <em v-else-if="model.health_error" class="model-manager-test-error">{{ model.health_error }}</em>
        <span class="model-manager-actions">
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            :data-testid="`test-model-button-${model.id}`"
            :disabled="testingId === model.id"
            @click="handleTest(model.id)"
          >
            {{ testingId === model.id ? '測試中…' : 'Test' }}
          </button>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            :data-testid="`edit-model-button-${model.id}`"
            @click="openEditForm(model)"
          >
            編輯
          </button>
          <button
            type="button"
            class="btn btn-danger btn-sm"
            :data-testid="`delete-model-button-${model.id}`"
            :disabled="deletingId === model.id"
            @click="handleDelete(model.id)"
          >
            刪除
          </button>
        </span>
      </div>
      <p v-if="!models.length" class="model-manager-empty">尚無模型設定</p>
    </div>

    <button
      v-if="!showForm"
      type="button"
      class="btn btn-primary"
      data-testid="add-model-button"
      @click="openCreateForm"
    >
      新增模型
    </button>

    <form v-else class="model-form" data-testid="model-form" @submit.prevent="saveForm">
      <h3>{{ formMode === 'create' ? '新增模型' : `編輯模型：${formId}` }}</h3>

      <p v-if="formGeneralError" class="error" data-testid="model-form-error">{{ formGeneralError }}</p>

      <label class="topic-input-row">
        id
        <input
          v-model="formId"
          :readonly="formMode === 'edit'"
          data-testid="model-form-id-input"
          aria-label="模型 id"
        />
        <em v-if="fieldError('id')" class="model-form-field-error" data-testid="model-form-error-id">{{ fieldError('id') }}</em>
      </label>

      <label class="topic-input-row">
        adapter
        <select v-model="formAdapter" data-testid="model-form-adapter-select">
          <option v-for="adapter in ADAPTERS" :key="adapter" :value="adapter">{{ adapter }}</option>
        </select>
        <em v-if="fieldError('adapter')" class="model-form-field-error" data-testid="model-form-error-adapter">{{ fieldError('adapter') }}</em>
      </label>

      <template v-if="isHttpAdapter(formAdapter)">
        <label class="topic-input-row">
          base_url
          <input v-model="formBaseUrl" data-testid="model-form-base-url-input" aria-label="base_url" />
          <em v-if="fieldError('base_url')" class="model-form-field-error" data-testid="model-form-error-base_url">{{ fieldError('base_url') }}</em>
        </label>
        <label class="topic-input-row">
          model
          <input v-model="formModel" data-testid="model-form-model-input" aria-label="model" />
          <em v-if="fieldError('model')" class="model-form-field-error" data-testid="model-form-error-model">{{ fieldError('model') }}</em>
        </label>
        <label class="topic-input-row">
          api_key_env
          <input v-model="formApiKeyEnv" data-testid="model-form-api-key-env-input" aria-label="api_key_env" />
        </label>
        <p class="model-form-hint">
          此欄位填<strong>環境變數名稱</strong>（如 <code>OPENAI_API_KEY</code>），不是 API 金鑰本身。金鑰請設在後端環境變數中，勿貼在此處。
        </p>
        <label class="dev-mode-toggle">
          <input type="checkbox" v-model="formSupportsJsonMode" data-testid="model-form-supports-json-mode-checkbox" />
          supports_json_mode
        </label>
        <label class="topic-input-row">
          timeout_seconds
          <input
            v-model.number="formTimeoutSeconds"
            type="number"
            min="1"
            data-testid="model-form-timeout-input"
            aria-label="timeout_seconds"
          />
          <em v-if="fieldError('timeout_seconds')" class="model-form-field-error" data-testid="model-form-error-timeout_seconds">{{ fieldError('timeout_seconds') }}</em>
        </label>
      </template>

      <template v-else-if="isCliAdapter(formAdapter)">
        <label class="topic-input-row">
          command（一行一個參數，需含 {prompt} 佔位符）
          <textarea
            v-model="formCommandText"
            rows="4"
            data-testid="model-form-command-textarea"
            aria-label="command"
          ></textarea>
          <em v-if="fieldError('command')" class="model-form-field-error" data-testid="model-form-error-command">{{ fieldError('command') }}</em>
        </label>
        <label class="topic-input-row">
          timeout_seconds
          <input
            v-model.number="formTimeoutSeconds"
            type="number"
            min="1"
            data-testid="model-form-timeout-input"
            aria-label="timeout_seconds"
          />
          <em v-if="fieldError('timeout_seconds')" class="model-form-field-error" data-testid="model-form-error-timeout_seconds">{{ fieldError('timeout_seconds') }}</em>
        </label>
      </template>

      <div class="model-form-actions">
        <button type="submit" class="btn btn-primary" data-testid="model-form-save" :disabled="saving">
          {{ saving ? '儲存中…' : '儲存' }}
        </button>
        <button type="button" class="btn btn-ghost" data-testid="model-form-cancel" @click="closeForm">
          取消
        </button>
      </div>
    </form>
  </section>
</template>
