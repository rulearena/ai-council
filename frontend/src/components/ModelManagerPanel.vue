<script setup lang="ts">
// Model management tab (spec.md §17.2/17.3) - lets a user create/edit/delete/test entries
// in config/models.yaml through the management API instead of hand-editing the file. Reuses useCouncil's `models`
// ref and `refreshModels()` as the single source of truth: every write here calls
// refreshModels() afterward rather than mutating `models` locally, so the role dropdowns in
// SettingsModal's 一般 tab (and the sanitize watch in useCouncil.ts that fallback-clears a
// deleted model's role selections) pick up the change through the exact same path a fresh
// page load would.
import { computed, inject, ref } from 'vue'
import { councilKey } from '../composables/useCouncil'
import {
  ApiError,
  createModel,
  deleteModel,
  getAvailableModels,
  previewAvailableModels,
  testModel,
  updateModel,
  type ModelConfig,
  type ModelConfigPayload,
} from '../api'
import {
  PROVIDERS,
  getProvider,
  modelConfigPayloadForProvider,
  modelDisplayLabel,
  providerIdForModel,
  type ProviderId,
} from '../providers'

const store = inject(councilKey)!
const { models, refreshModels } = store

const HTTP_ADAPTERS = new Set(['openai-compatible-http', 'anthropic-http', 'gemini-http'])

function isHttpAdapter(adapter: string): boolean {
  return HTTP_ADAPTERS.has(adapter)
}

function isCliAdapter(adapter: string): boolean {
  return adapter === 'subscription-cli'
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
const formProvider = ref<ProviderId>('mock')
const formBaseUrl = ref('')
const formModel = ref('')
const formApiKeyEnv = ref('')
const formSupportsJsonMode = ref(false)
const formTimeoutSeconds = ref(120)
const formCommandText = ref('')
// Not rendered as inputs (round-trip only, per the fidelity requirement below) -
// carried through from the model being edited and sent back unchanged on save so a PUT
// from this form never silently drops extra_body/pricing a human hand-edited into
// models.yaml.
const formExtraBody = ref<Record<string, unknown>>({})
const formPricing = ref<ModelConfig['pricing']>(null)
const discoveryModels = ref<string[]>([])
const discoveryLoading = ref(false)
const discoveryMessage = ref('')
const manualModelEntry = ref(true)

const providerDefinition = computed(() => getProvider(formProvider.value))
const formAdapter = computed(() => providerDefinition.value.adapter)
const supportsDiscovery = computed(() => providerDefinition.value.discovery === 'openai-compatible')

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

function resetDiscovery() {
  discoveryModels.value = []
  discoveryMessage.value = ''
  manualModelEntry.value = true
}

function handleProviderChange() {
  const provider = providerDefinition.value
  formBaseUrl.value = provider.defaultBaseUrl ?? ''
  formApiKeyEnv.value = provider.defaultApiKeyEnv ?? ''
  formModel.value = ''
  formCommandText.value = ''
  resetDiscovery()
}

function openCreateForm() {
  formMode.value = 'create'
  formId.value = ''
  formProvider.value = 'mock'
  formBaseUrl.value = ''
  formModel.value = ''
  formApiKeyEnv.value = ''
  formSupportsJsonMode.value = false
  formTimeoutSeconds.value = 120
  formCommandText.value = ''
  formExtraBody.value = {}
  formPricing.value = null
  resetDiscovery()
  resetFormErrors()
  showForm.value = true
}

function openEditForm(model: ModelConfig) {
  formMode.value = 'edit'
  formId.value = model.id
  formProvider.value = providerIdForModel(model) ?? 'custom-openai-compatible'
  formBaseUrl.value = model.base_url ?? ''
  formModel.value = model.model ?? ''
  formApiKeyEnv.value = model.api_key_env ?? ''
  formSupportsJsonMode.value = model.supports_json_mode
  formTimeoutSeconds.value = model.timeout_seconds
  formCommandText.value = (model.command ?? []).join('\n')
  formExtraBody.value = model.extra_body ?? {}
  formPricing.value = model.pricing ?? null
  resetDiscovery()
  resetFormErrors()
  showForm.value = true
}

function closeForm() {
  showForm.value = false
}

function buildPayload(): ModelConfigPayload {
  return modelConfigPayloadForProvider(formProvider.value, {
    base_url: formBaseUrl.value,
    model: formModel.value,
    api_key_env: formApiKeyEnv.value,
    supports_json_mode: formSupportsJsonMode.value,
    command: formCommandText.value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
    timeout_seconds: formTimeoutSeconds.value,
    extra_body: formExtraBody.value,
    pricing: formPricing.value,
  })
}

async function discoverModels() {
  discoveryLoading.value = true
  discoveryMessage.value = ''
  try {
    const result = formMode.value === 'edit'
      ? await getAvailableModels(formId.value)
      : await previewAvailableModels({
          adapter: formAdapter.value,
          base_url: formBaseUrl.value.trim() || null,
          api_key_env: formApiKeyEnv.value.trim() || null,
        })
    discoveryModels.value = result.models
    if (result.models.length) {
      formModel.value = result.models.includes(formModel.value) ? formModel.value : result.models[0]
      manualModelEntry.value = false
    } else {
      discoveryMessage.value = 'Provider 沒有回傳可用模型，請手動輸入 exact model ID。'
      manualModelEntry.value = true
    }
  } catch (caught) {
    discoveryModels.value = []
    const reason = caught instanceof ApiError && typeof caught.detail === 'string'
      ? caught.detail
      : caught instanceof Error
        ? caught.message
        : String(caught)
    discoveryMessage.value = `${reason}；請手動輸入 exact model ID。`
    manualModelEntry.value = true
  } finally {
    discoveryLoading.value = false
  }
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
        <span class="model-manager-provider">{{ modelDisplayLabel(model) }}</span>
        <span class="model-manager-summary">{{ model.base_url ?? model.command?.[0] ?? '' }}</span>
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
        Provider
        <select v-model="formProvider" data-testid="model-form-provider-select" @change="handleProviderChange">
          <option v-for="provider in PROVIDERS" :key="provider.id" :value="provider.id">{{ provider.name }}</option>
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
          Credential 環境變數名稱
          <input v-model="formApiKeyEnv" data-testid="model-form-api-key-env-input" aria-label="api_key_env" />
        </label>
        <p class="model-form-hint" data-testid="model-form-credential-hint">
          此欄位填<strong>環境變數名稱</strong>（如 <code>OPENAI_API_KEY</code>），不是 API 金鑰本身。金鑰請設在後端環境變數中，勿貼在此處。
        </p>
        <div v-if="supportsDiscovery" class="model-discovery-actions">
          <button type="button" class="btn btn-secondary" data-testid="model-form-discover-button" :disabled="discoveryLoading" @click="discoverModels">
            {{ discoveryLoading ? '載入中…' : (discoveryModels.length ? '重新整理可用模型' : '載入可用模型') }}
          </button>
        </div>
        <p v-else class="model-form-hint" data-testid="model-form-discovery-unsupported">
          {{ providerDefinition.name }} 暫不支援自動載入模型，請手動輸入 exact model ID。
        </p>
        <p v-if="discoveryMessage" class="error" data-testid="model-form-discovery-message" role="alert">{{ discoveryMessage }}</p>
        <label v-if="discoveryModels.length && !manualModelEntry" class="topic-input-row">
          Exact model ID
          <select v-model="formModel" data-testid="model-form-discovered-model-select">
            <option v-for="modelId in discoveryModels" :key="modelId" :value="modelId">{{ modelId }}</option>
          </select>
        </label>
        <button
          v-if="discoveryModels.length"
          type="button"
          class="btn btn-ghost btn-sm"
          data-testid="model-form-manual-model-toggle"
          @click="manualModelEntry = !manualModelEntry"
        >{{ manualModelEntry ? '改用已載入模型' : '手動輸入新 model ID' }}</button>
        <label v-if="manualModelEntry" class="topic-input-row">
          Exact model ID
          <input v-model="formModel" data-testid="model-form-model-input" aria-label="model" />
          <em v-if="fieldError('model')" class="model-form-field-error" data-testid="model-form-error-model">{{ fieldError('model') }}</em>
        </label>
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
        <p class="model-form-hint" data-testid="model-form-cli-discovery-unsupported">
          Subscription CLI 不支援自動載入模型；執行型號由 command 決定，請在下方確認命令。
        </p>
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
