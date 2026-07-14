<script setup lang="ts">
// Model management tab (spec.md §17.2/17.3) - lets a user create/edit/delete/test entries
// in config/models.yaml through the management API instead of hand-editing the file. Reuses useCouncil's `models`
// ref and `refreshModels()` as the single source of truth: every write here calls
// refreshModels() afterward rather than mutating `models` locally, so the role dropdowns in
// SettingsModal's 一般 tab (and the sanitize watch in useCouncil.ts that fallback-clears a
// deleted model's role selections) pick up the change through the exact same path a fresh
// page load would.
import { computed, inject, onBeforeUnmount, ref } from 'vue'
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
  CLI_PRESETS,
  PROVIDERS,
  cliConfigPayload,
  getProvider,
  modelConfigPayloadForProvider,
  modelDisplayLabel,
  providerIdForModel,
  projectCliConfig,
  type CliModelMode,
  type CliPresetId,
  type ProviderId,
} from '../providers'
import { LatestDiscoveryRequest, type DiscoveryEvent } from '../modelDiscovery'

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
  invalidateModelTest(id)
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

type TestFeedback = {
  phase: 'testing' | 'slow' | 'success' | 'error'
  message: string
  status?: ModelConfig['status']
}

const TEST_SLOW_THRESHOLD_MS = 1_000
const testFeedback = ref<Record<string, TestFeedback>>({})
const testGenerations = new Map<string, number>()
const testSlowTimers = new Map<string, ReturnType<typeof setTimeout>>()
let testContextActive = true

function clearTestSlowTimer(id: string) {
  const timer = testSlowTimers.get(id)
  if (timer !== undefined) clearTimeout(timer)
  testSlowTimers.delete(id)
}

function isCurrentModelTest(id: string, generation: number): boolean {
  return testContextActive
    && testGenerations.get(id) === generation
    && models.value.some((model) => model.id === id)
}

function invalidateModelTest(id: string) {
  testGenerations.set(id, (testGenerations.get(id) ?? 0) + 1)
  clearTestSlowTimer(id)
  const next = { ...testFeedback.value }
  delete next[id]
  testFeedback.value = next
}

function invalidatePendingModelTests() {
  for (const [id, feedback] of Object.entries(testFeedback.value)) {
    if (feedback.phase === 'testing' || feedback.phase === 'slow') invalidateModelTest(id)
  }
}

function testIsRunning(id: string): boolean {
  const phase = testFeedback.value[id]?.phase
  return phase === 'testing' || phase === 'slow'
}

function testErrorMessage(caught: unknown): string {
  if (caught instanceof ApiError && typeof caught.detail === 'string') return caught.detail
  return caught instanceof Error ? caught.message : String(caught)
}

async function handleTest(id: string) {
  if (testIsRunning(id)) return
  const generation = (testGenerations.get(id) ?? 0) + 1
  testGenerations.set(id, generation)
  testFeedback.value = {
    ...testFeedback.value,
    [id]: { phase: 'testing', message: '正在測試連線…' },
  }
  clearTestSlowTimer(id)
  testSlowTimers.set(id, setTimeout(() => {
    if (!isCurrentModelTest(id, generation)) return
    testFeedback.value = {
      ...testFeedback.value,
      [id]: { phase: 'slow', message: 'Provider 回應較慢，仍在等待…' },
    }
  }, TEST_SLOW_THRESHOLD_MS))
  try {
    const result = await testModel(id)
    if (!isCurrentModelTest(id, generation)) return
    await refreshModels(() => isCurrentModelTest(id, generation))
    if (!isCurrentModelTest(id, generation)) return
    clearTestSlowTimer(id)
    testFeedback.value = {
      ...testFeedback.value,
      [id]: result.status === 'available'
        ? { phase: 'success', message: '連線成功', status: 'available' }
        : {
            phase: 'error',
            message: `測試失敗：${result.error || 'Provider 回報連線不可用'}`,
            status: 'unavailable',
          },
    }
  } catch (caught) {
    if (!isCurrentModelTest(id, generation)) return
    clearTestSlowTimer(id)
    testFeedback.value = {
      ...testFeedback.value,
      [id]: {
        phase: 'error',
        message: `測試失敗：${testErrorMessage(caught)}`,
        status: 'unavailable',
      },
    }
  } finally {
    if (isCurrentModelTest(id, generation)) clearTestSlowTimer(id)
  }
}

onBeforeUnmount(() => {
  testContextActive = false
  for (const id of testSlowTimers.keys()) clearTestSlowTimer(id)
  testGenerations.clear()
})

// -------- create/edit form --------

type FormMode = 'create' | 'edit'
type DiscoveryConnection = {
  adapter: string
  baseUrl: string | null
  apiKeyEnv: string | null
}
const showForm = ref(false)
const formMode = ref<FormMode>('create')
const formId = ref('')
const formProvider = ref<ProviderId>('mock')
const formBaseUrl = ref('')
const formModel = ref('')
const formApiKeyEnv = ref('')
const formSupportsJsonMode = ref(false)
const formTimeoutSeconds = ref(120)
const formCliPreset = ref<CliPresetId>('claude')
const formCliModelMode = ref<CliModelMode>('default')
const formCliExactModelId = ref('')
const formPreserveCliProviderMarker = ref(false)
const formCliExactModelError = ref('')
const formCommandText = ref('')
// Not rendered as inputs (round-trip only, per the fidelity requirement below) -
// carried through from the model being edited and sent back unchanged on save so a PUT
// from this form never silently drops extra_body/pricing a human hand-edited into
// models.yaml.
const formExtraBody = ref<Record<string, unknown>>({})
const formPricing = ref<ModelConfig['pricing']>(null)
const discoveryModels = ref<string[]>([])
const discoveryQuery = ref('')
const discoveryLoading = ref(false)
const discoveryMessage = ref('')
const manualModelEntry = ref(true)
const originalDiscoveryConnection = ref<DiscoveryConnection | null>(null)
const discoveryRequest = new LatestDiscoveryRequest()

const providerDefinition = computed(() => getProvider(formProvider.value))
const formAdapter = computed(() => providerDefinition.value.adapter)
const supportsDiscovery = computed(() => providerDefinition.value.discovery !== 'manual-only')
const filteredDiscoveryModels = computed(() => {
  const query = discoveryQuery.value.trim().toLocaleLowerCase()
  if (!query) return discoveryModels.value
  return discoveryModels.value.filter((modelId) => modelId.toLocaleLowerCase().includes(query))
})

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
  formCliExactModelError.value = ''
}

function resetDiscovery() {
  discoveryRequest.invalidate()
  discoveryModels.value = []
  discoveryQuery.value = ''
  discoveryLoading.value = false
  discoveryMessage.value = ''
  manualModelEntry.value = true
}

function handleManualModelInput() {
  discoveryRequest.manualModelEdited()
  discoveryModels.value = []
  discoveryQuery.value = ''
  discoveryLoading.value = false
  discoveryMessage.value = ''
  manualModelEntry.value = true
}

function handleDiscoveredModelChange() {
  discoveryRequest.invalidate()
  discoveryLoading.value = false
  discoveryMessage.value = ''
}

function handleProviderChange() {
  const provider = providerDefinition.value
  formBaseUrl.value = provider.defaultBaseUrl ?? ''
  formApiKeyEnv.value = provider.defaultApiKeyEnv ?? ''
  formModel.value = ''
  formCliPreset.value = 'claude'
  formCliModelMode.value = 'default'
  formCliExactModelId.value = ''
  formPreserveCliProviderMarker.value = false
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
  formCliPreset.value = 'claude'
  formCliModelMode.value = 'default'
  formCliExactModelId.value = ''
  formPreserveCliProviderMarker.value = false
  formCommandText.value = ''
  formExtraBody.value = {}
  formPricing.value = null
  originalDiscoveryConnection.value = null
  resetDiscovery()
  resetFormErrors()
  showForm.value = true
}

function openEditForm(model: ModelConfig) {
  invalidatePendingModelTests()
  invalidateModelTest(model.id)
  formMode.value = 'edit'
  formId.value = model.id
  formProvider.value = providerIdForModel(model) ?? 'custom-openai-compatible'
  formBaseUrl.value = model.base_url ?? ''
  formModel.value = model.model ?? ''
  formApiKeyEnv.value = model.api_key_env ?? ''
  formSupportsJsonMode.value = model.supports_json_mode
  formTimeoutSeconds.value = model.timeout_seconds
  formExtraBody.value = model.extra_body ?? {}
  const cliProjection = projectCliConfig(model)
  formCliPreset.value = cliProjection.presetId
  formCliModelMode.value = cliProjection.modelMode
  formCliExactModelId.value = cliProjection.exactModelId
  formPreserveCliProviderMarker.value = isCliAdapter(model.adapter)
  formCommandText.value = cliProjection.command.join('\n')
  formPricing.value = model.pricing ?? null
  originalDiscoveryConnection.value = {
    adapter: model.adapter,
    baseUrl: model.base_url?.trim() || null,
    apiKeyEnv: model.api_key_env?.trim() || null,
  }
  resetDiscovery()
  resetFormErrors()
  showForm.value = true
}

function closeForm() {
  resetDiscovery()
  showForm.value = false
}

function handleCliPresetChange() {
  formPreserveCliProviderMarker.value = false
  formCliModelMode.value = 'default'
  formCliExactModelId.value = ''
  formCliExactModelError.value = ''
}

function handleCliModelModeChange() {
  formCliExactModelError.value = ''
  if (formCliModelMode.value === 'default') formCliExactModelId.value = ''
}

function buildPayload(): ModelConfigPayload {
  const customCommand = formCommandText.value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  const cliConfig = cliConfigPayload(formCliPreset.value, customCommand, formExtraBody.value, {
    modelMode: formCliModelMode.value,
    exactModelId: formCliExactModelId.value,
    preserveProviderMarker: formPreserveCliProviderMarker.value,
  })
  return modelConfigPayloadForProvider(formProvider.value, {
    base_url: formBaseUrl.value,
    model: formModel.value,
    api_key_env: formApiKeyEnv.value,
    supports_json_mode: formSupportsJsonMode.value,
    command: cliConfig.command,
    timeout_seconds: formTimeoutSeconds.value,
    extra_body: isCliAdapter(formAdapter.value) ? cliConfig.extra_body : formExtraBody.value,
    pricing: formPricing.value,
  })
}

async function discoverModels() {
  const snapshot = {
    mode: formMode.value,
    id: formId.value,
    provider: formProvider.value,
    adapter: formAdapter.value,
    baseUrl: formBaseUrl.value.trim() || null,
    apiKeyEnv: formApiKeyEnv.value.trim() || null,
  }
  const identity = JSON.stringify(snapshot)
  const original = originalDiscoveryConnection.value
  const connectionIsUnchanged = original !== null
    && snapshot.adapter === original.adapter
    && snapshot.baseUrl === original.baseUrl
    && snapshot.apiKeyEnv === original.apiKeyEnv
  const load = snapshot.mode === 'edit' && connectionIsUnchanged
    ? () => getAvailableModels(snapshot.id)
    : () => previewAvailableModels({
        adapter: snapshot.adapter,
        base_url: snapshot.baseUrl,
        api_key_env: snapshot.apiKeyEnv,
      })
  await discoveryRequest.run(identity, load, applyDiscoveryEvent)
}

function applyDiscoveryEvent(event: DiscoveryEvent) {
  if (event.type === 'started') {
    discoveryLoading.value = true
    discoveryMessage.value = ''
    return
  }
  if (event.type === 'succeeded') {
    discoveryModels.value = event.models
    if (event.models.length) {
      formModel.value = event.models.includes(formModel.value) ? formModel.value : event.models[0]
      manualModelEntry.value = false
    } else {
      discoveryMessage.value = 'Provider 沒有回傳可用模型，請手動輸入 exact model ID。'
      manualModelEntry.value = true
    }
    return
  }
  if (event.type === 'failed') {
    discoveryModels.value = []
    const reason = event.error instanceof ApiError && typeof event.error.detail === 'string'
      ? event.error.detail
      : event.error instanceof Error
        ? event.error.message
        : String(event.error)
    discoveryMessage.value = `${reason}；請手動輸入 exact model ID。`
    manualModelEntry.value = true
    return
  }
  if (event.type === 'settled') {
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
  if (isCliAdapter(formAdapter.value)
    && formCliPreset.value !== 'custom'
    && formCliModelMode.value === 'exact'
    && !formCliExactModelId.value.trim()) {
    formCliExactModelError.value = '請輸入 exact model ID。'
    return
  }
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
          <i class="status-dot" :data-status="testFeedback[model.id]?.status ?? model.status" aria-hidden="true"></i>
          {{ model.id }}
        </span>
        <span class="model-manager-provider">{{ modelDisplayLabel(model) }}</span>
        <span class="model-manager-summary">{{ model.base_url ?? model.command?.[0] ?? '' }}</span>
        <span
          v-if="testFeedback[model.id]"
          class="model-manager-test-feedback"
          :class="{ 'model-manager-test-error': testFeedback[model.id].phase === 'error' }"
          :data-testid="`model-test-feedback-${model.id}`"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {{ testFeedback[model.id].message }}
        </span>
        <em v-else-if="model.health_error" class="model-manager-test-error">{{ model.health_error }}</em>
        <span class="model-manager-actions">
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            :data-testid="`test-model-button-${model.id}`"
            :disabled="testIsRunning(model.id)"
            @click="handleTest(model.id)"
          >
            <i v-if="testIsRunning(model.id)" class="spinner" aria-hidden="true"></i>
            {{ testIsRunning(model.id) ? '正在測試連線…' : 'Test' }}
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
          <input v-model="formBaseUrl" data-testid="model-form-base-url-input" aria-label="base_url" @input="resetDiscovery" />
          <em v-if="fieldError('base_url')" class="model-form-field-error" data-testid="model-form-error-base_url">{{ fieldError('base_url') }}</em>
        </label>
        <label class="topic-input-row">
          Credential 環境變數名稱
          <input v-model="formApiKeyEnv" data-testid="model-form-api-key-env-input" aria-label="api_key_env" @input="resetDiscovery" />
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
          搜尋已載入模型
          <input
            v-model="discoveryQuery"
            type="search"
            data-testid="model-form-discovery-search"
            aria-label="搜尋已載入模型"
          />
        </label>
        <p
          v-if="discoveryModels.length && !manualModelEntry && discoveryQuery.trim() && !filteredDiscoveryModels.length"
          class="model-form-hint"
          data-testid="model-form-discovery-no-match"
          role="status"
        >找不到符合的模型。</p>
        <label v-if="filteredDiscoveryModels.length && !manualModelEntry" class="topic-input-row">
          Exact model ID
          <select v-model="formModel" data-testid="model-form-discovered-model-select" @change="handleDiscoveredModelChange">
            <option v-for="modelId in filteredDiscoveryModels" :key="modelId" :value="modelId">{{ modelId }}</option>
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
          <input v-model="formModel" data-testid="model-form-model-input" aria-label="model" @input="handleManualModelInput" />
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
        <label class="topic-input-row">
          CLI Provider
          <select v-model="formCliPreset" data-testid="model-form-cli-preset-select" @change="handleCliPresetChange">
            <option v-for="preset in CLI_PRESETS" :key="preset.id" :value="preset.id">{{ preset.name }}</option>
          </select>
        </label>
        <template v-if="formCliPreset !== 'custom'">
          <label class="topic-input-row">
            模型選擇
            <select v-model="formCliModelMode" data-testid="model-form-cli-model-mode-select" @change="handleCliModelModeChange">
              <option value="default">使用 CLI 預設模型</option>
              <option value="exact">指定 exact model ID</option>
            </select>
          </label>
          <p v-if="formCliModelMode === 'default'" class="model-form-hint" data-testid="model-form-cli-model-default">
            使用 CLI 自動選擇模型（推薦）。命令與 prompt 參數會由 preset 安全產生，不需手動輸入。
          </p>
          <label v-else class="topic-input-row">
            Exact model ID
            <input v-model="formCliExactModelId" data-testid="model-form-cli-exact-model-input" aria-label="CLI exact model ID" @input="formCliExactModelError = ''" />
            <em v-if="formCliExactModelError" class="model-form-field-error" data-testid="model-form-cli-exact-model-error">{{ formCliExactModelError }}</em>
          </label>
        </template>
        <p v-else class="model-form-hint" data-testid="model-form-cli-custom-hint">
          Custom CLI 是進階逃生路徑；未知的既有命令會保持原樣，不會自動改寫。
        </p>
        <label v-if="formCliPreset === 'custom'" class="topic-input-row">
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
