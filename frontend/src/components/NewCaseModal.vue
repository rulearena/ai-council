<script setup lang="ts">
// Two-step New Case flow (spec.md 16.6): (1) browse the mode catalog, (2) confirm
// participants and the topic. Which cards are actually selectable is data-driven
// (`mode.available`, sourced from GET /modes - see modes.ts's refreshModeCatalog): as of
// slice C that's every backend-supported mode, including parallel modes. Choosing red-blue
// and creating still ends up calling createNewMeeting() the same way the old flat form did,
// so a user who never looks at the mode picker gets today's behavior unchanged.
import { computed, inject, ref, watch } from 'vue'
import { getCaseFileLimits, type CaseFileLimits } from '../api'
import { councilKey, roleIcon } from '../composables/useCouncil'
import { DEFAULT_MODE_ID, modeCatalog, type ModeDefinition } from '../modes'
import Modal from './Modal.vue'
import ModeCard from './ModeCard.vue'
import RoleSilhouette from './RoleSilhouette.vue'
import { modelDisplayLabel } from '../providers'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const store = inject(councilKey)!
const {
  title,
  goal,
  models,
  loading,
  meetingCreationError,
  createNewMeeting,
  clearMeetingCreationError,
} = store

type Step = 'mode' | 'participants'
type DraftCaseFile = {
  title: string
  content: string
  visibleRoles: string[]
}

const step = ref<Step>('mode')
const selectedModeId = ref<string>(DEFAULT_MODE_ID)
const selectedMode = computed<ModeDefinition>(
  () => modeCatalog.find((mode) => mode.id === selectedModeId.value) ?? modeCatalog[0],
)

// Values for the selected mode's `kind: 'text'` inputs (e.g. debate's position_a/
// position_b - spec.md 16.2), keyed by input id. Parallel persona/member prompts are
// handled by the member editor below.
const inputValues = ref<Record<string, string>>({})
const caseFiles = ref<DraftCaseFile[]>([])
const caseFileLimits = ref<CaseFileLimits | null>(null)
const caseFileLimitsLoading = ref(false)
const caseFileLimitsError = ref('')
let caseFileLimitsRequestGeneration = 0
const parallelMemberCount = ref(2)
const parallelMembers = ref<Array<{ displayName: string; instancePrompt: string }>>([])
const draftModelAssignments = ref<Record<string, string>>({})
const textInputs = computed(() => selectedMode.value.inputs.filter((input) => input.kind === 'text'))
const hasEmptyRequiredInput = computed(() =>
  textInputs.value.some((input) => !(inputValues.value[input.id] ?? '').trim()),
)
const hasIncompleteCaseFile = computed(() =>
  caseFiles.value.some(
    (file) => !file.title.trim() || !file.content.trim() || file.visibleRoles.length === 0,
  ),
)
const totalCaseFileChars = computed(() =>
  caseFiles.value.reduce((total, file) => total + codePointLength(file.content), 0),
)
const hasOversizedCaseFile = computed(() =>
  caseFileLimits.value
    ? caseFiles.value.some(
        (file) => codePointLength(file.content) > caseFileLimits.value!.per_file_chars,
      )
    : false,
)
const hasOversizedCaseFileTotal = computed(
  () =>
    caseFileLimits.value !== null &&
    totalCaseFileChars.value > caseFileLimits.value.total_chars,
)
const estimatedCaseFileTokens = computed(() => {
  const codePoints = Array.from(caseFiles.value.map((file) => file.content).join(''))
  const conservativeScript = /[\p{Script_Extensions=Han}\p{Script_Extensions=Hiragana}\p{Script_Extensions=Katakana}\p{Script_Extensions=Hangul}\u30fc]/u
  const cjkCount = codePoints.filter((character) => conservativeScript.test(character)).length
  const otherNonWhitespaceCount = codePoints.filter(
    (character) => !conservativeScript.test(character) && !/\s/u.test(character),
  ).length
  return cjkCount + Math.ceil(otherNonWhitespaceCount / 4)
})

function codePointLength(value: string) {
  return Array.from(value).length
}

function hasFixedParallelRoster(mode: ModeDefinition) {
  return mode.category === 'parallel' && mode.roles.some((role) => role.kind === 'member')
}

const selectedModeParticipants = computed(() => {
  const mode = selectedMode.value
  if (
    mode.category !== 'parallel' ||
    !mode.fanout ||
    !mode.synthesis ||
    hasFixedParallelRoster(mode)
  ) {
    return mode.roles
  }
  const members = Array.from({ length: parallelMemberCount.value }, (_, index) => ({
    id: `${mode.fanout!.role}-${index + 1}`,
    name: parallelMembers.value[index]?.displayName || `委員 ${index + 1}`,
    color: '#4d8dff',
    kind: 'member' as const,
  }))
  const synthesizers = mode.roles.filter((role) => role.kind === 'synthesizer')
  return [...members, ...synthesizers]
})
const hasIncompleteModelAssignment = computed(
  () =>
    models.value.length === 0 ||
    selectedModeParticipants.value.some((participant) => !draftModelAssignments.value[participant.id]),
)

// Reopening the modal always starts over at the mode picker - a half-finished previous
// attempt (e.g. closed after picking a mode but before creating) shouldn't linger.
watch(
  () => props.show,
  (visible) => {
    caseFileLimitsRequestGeneration += 1
    if (visible) {
      selectedModeId.value = DEFAULT_MODE_ID
      step.value = 'mode'
      inputValues.value = {}
      caseFiles.value = []
      clearMeetingCreationError()
      resetParallelMembers(selectedMode.value)
      resetModelAssignments()
      caseFileLimits.value = null
      void refreshCaseFileLimits(caseFileLimitsRequestGeneration)
    } else {
      caseFileLimitsLoading.value = false
    }
  },
)

function retryCaseFileLimits() {
  caseFileLimitsRequestGeneration += 1
  void refreshCaseFileLimits(caseFileLimitsRequestGeneration)
}

async function refreshCaseFileLimits(generation: number) {
  caseFileLimitsLoading.value = true
  caseFileLimitsError.value = ''
  try {
    const limits = await getCaseFileLimits()
    if (generation !== caseFileLimitsRequestGeneration) return
    caseFileLimits.value = limits
  } catch {
    if (generation !== caseFileLimitsRequestGeneration) return
    caseFileLimits.value = null
    caseFileLimitsError.value = '無法載入案卷限制，請重試。'
  } finally {
    if (generation === caseFileLimitsRequestGeneration) {
      caseFileLimitsLoading.value = false
    }
  }
}

watch(
  [title, goal, selectedModeId, inputValues, caseFiles, parallelMemberCount, parallelMembers],
  clearMeetingCreationError,
  { deep: true },
)

function chooseMode(mode: ModeDefinition) {
  if (!mode.available) return
  // Only reset inputValues on an actual mode switch - going back to the mode picker and
  // re-choosing the same mode (e.g. after "← 返回模式選擇") should keep whatever the user
  // already typed. Reopening the modal fresh is still handled by the watch(show) above.
  if (mode.id !== selectedModeId.value) {
    inputValues.value = {}
    caseFiles.value = []
    resetParallelMembers(mode)
  }
  selectedModeId.value = mode.id
  resetModelAssignments()
  step.value = 'participants'
}

function backToModePicker() {
  step.value = 'mode'
}

async function submit() {
  clearMeetingCreationError()
  const created = await createNewMeeting(
    selectedMode.value.id,
    { ...inputValues.value },
    buildParticipants(),
    buildCaseFiles(),
  )
  if (created) emit('close')
}

function resetParallelMembers(mode: ModeDefinition) {
  if (!mode.fanout) {
    parallelMemberCount.value = 2
    parallelMembers.value = []
    return
  }
  parallelMemberCount.value = mode.fanout.minInstances
  parallelMembers.value = Array.from({ length: mode.fanout.minInstances }, (_, index) => ({
    displayName: `委員 ${index + 1}`,
    instancePrompt: '',
  }))
}

function setParallelMemberCount(nextCount: number) {
  const fanout = selectedMode.value.fanout
  if (!fanout) return
  const clamped = Math.min(fanout.maxInstances, Math.max(fanout.minInstances, nextCount))
  parallelMemberCount.value = clamped
  while (parallelMembers.value.length < clamped) {
    const index = parallelMembers.value.length
    parallelMembers.value.push({ displayName: `委員 ${index + 1}`, instancePrompt: '' })
  }
  parallelMembers.value.splice(clamped)
  resetModelAssignments(true)
}

function resetModelAssignments(preserveExisting = false) {
  const firstModelId = models.value[0]?.id ?? ''
  draftModelAssignments.value = Object.fromEntries(
    selectedModeParticipants.value.map((participant) => [
      participant.id,
      preserveExisting ? draftModelAssignments.value[participant.id] || firstModelId : firstModelId,
    ]),
  )
}

function addCaseFile() {
  caseFiles.value.push({ title: '', content: '', visibleRoles: [] })
}

function draftEvidenceAnchor(index: number) {
  const digits = '零一二三四五六七八九'
  const section = (value: number) => {
    let result = ''
    let pendingZero = false
    for (const [divisor, unit] of [
      [1000, '千'],
      [100, '百'],
      [10, '十'],
      [1, ''],
    ] as const) {
      const digit = Math.floor(value / divisor)
      value %= divisor
      if (digit) {
        if (pendingZero && result) result += digits[0]
        if (!(divisor === 10 && digit === 1 && !result)) result += digits[digit]
        result += unit
        pendingZero = false
      } else if (result && value) {
        pendingZero = true
      }
    }
    return result
  }
  const high = Math.floor(index / 10_000)
  const low = index % 10_000
  const numeral = high
    ? `${section(high)}萬${low && low < 1000 ? digits[0] : ''}${low ? section(low) : ''}`
    : section(low)
  return `[證物${numeral}]`
}

function removeCaseFile(index: number) {
  caseFiles.value.splice(index, 1)
}

function toggleCaseFileRole(file: DraftCaseFile, roleId: string) {
  if (file.visibleRoles.includes(roleId)) {
    file.visibleRoles = file.visibleRoles.filter((role) => role !== roleId)
    return
  }
  file.visibleRoles = [...file.visibleRoles, roleId]
}

async function loadCaseFileUpload(file: DraftCaseFile, event: Event) {
  const input = event.target as HTMLInputElement
  const selected = input.files?.[0]
  if (!selected) return
  file.content = await selected.text()
  if (!file.title.trim()) {
    file.title = selected.name.replace(/\.(md|markdown|txt)$/i, '')
  }
  input.value = ''
}

function buildCaseFiles() {
  return caseFiles.value.map((file) => ({
    title: file.title.trim(),
    content: file.content,
    visible_roles: file.visibleRoles,
  }))
}

function buildParticipants() {
  const mode = selectedMode.value
  if (
    mode.category !== 'parallel' ||
    !mode.fanout ||
    !mode.synthesis ||
    hasFixedParallelRoster(mode)
  ) {
    return mode.roles.map((role) => ({
      role_id: role.id,
      model_config_id: draftModelAssignments.value[role.id],
    }))
  }
  const members = Array.from({ length: parallelMemberCount.value }, (_, index) => ({
    role_id: `${mode.fanout!.role}-${index + 1}`,
    model_config_id: draftModelAssignments.value[`${mode.fanout!.role}-${index + 1}`],
    display_name: parallelMembers.value[index]?.displayName || `委員 ${index + 1}`,
    instance_prompt: parallelMembers.value[index]?.instancePrompt || null,
  }))
  return [
    ...members,
    ...mode.roles
      .filter((role) => role.kind === 'synthesizer')
      .map((role) => ({
        role_id: role.id,
        model_config_id: draftModelAssignments.value[role.id],
        display_name: role.name,
      })),
  ]
}
</script>

<template>
  <Modal :show="show" title="New Case" test-id="new-case-modal" close-test-id="new-case-close-button" @close="$emit('close')">
    <p
      v-if="caseFileLimitsLoading"
      class="case-file-cost-note"
      data-testid="case-file-limits-status"
      role="status"
    >
      正在載入案卷限制…
    </p>
    <div
      v-else-if="caseFileLimitsError"
      class="error case-file-limits-error"
      data-testid="case-file-limits-error"
      role="alert"
    >
      <span>{{ caseFileLimitsError }}</span>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        data-testid="retry-case-file-limits-button"
        @click="retryCaseFileLimits"
      >
        重試
      </button>
    </div>
    <div v-if="step === 'mode'" class="mode-picker" data-testid="mode-picker-step">
      <p class="mode-picker-hint">選擇本次會議的模式：</p>
      <div class="mode-card-grid">
        <ModeCard
          v-for="mode in modeCatalog"
          :key="mode.id"
          :mode="mode"
          test-id-prefix="mode-select-card"
          @choose="chooseMode(mode)"
        />
      </div>
    </div>

    <div v-else class="participant-setup" data-testid="participant-setup-step">
      <button
        type="button"
        class="btn btn-ghost btn-sm back-to-mode-picker-button"
        data-testid="back-to-mode-picker-button"
        @click="backToModePicker"
      >
        ← 返回模式選擇
      </button>

      <h3 class="participant-setup-title">{{ selectedMode.name }}</h3>
      <p class="participant-setup-tagline">{{ selectedMode.tagline }}</p>

      <label class="topic-input-row">
        名稱
        <input v-model="title" aria-label="名稱" />
      </label>

      <label class="topic-input-row">
        目標
        <textarea v-model="goal" aria-label="目標" />
      </label>

      <label v-for="input in textInputs" :key="input.id" class="topic-input-row">
        {{ input.label }}
        <input
          v-model="inputValues[input.id]"
          :data-testid="`mode-input-${input.id}`"
          :aria-label="input.label"
        />
      </label>

      <section
        v-if="selectedMode.category === 'parallel' && selectedMode.fanout && !hasFixedParallelRoster(selectedMode)"
        class="parallel-member-editor"
        data-testid="parallel-member-editor"
      >
        <div class="parallel-member-count-row">
          <span>成員數</span>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            data-testid="parallel-member-decrement"
            @click="setParallelMemberCount(parallelMemberCount - 1)"
            :disabled="parallelMemberCount <= selectedMode.fanout.minInstances"
          >
            -
          </button>
          <strong data-testid="parallel-member-count">{{ parallelMemberCount }}</strong>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            data-testid="parallel-member-increment"
            @click="setParallelMemberCount(parallelMemberCount + 1)"
            :disabled="parallelMemberCount >= selectedMode.fanout.maxInstances"
          >
            +
          </button>
        </div>

        <label v-for="(_, index) in parallelMemberCount" :key="index" class="parallel-member-row">
          <span>{{ selectedMode.fanout.role }}-{{ index + 1 }}</span>
          <input
            v-model="parallelMembers[index].displayName"
            :data-testid="`parallel-member-${index + 1}-name`"
            :aria-label="`成員 ${index + 1} 名稱`"
          />
          <textarea
            v-if="selectedMode.fanout.instancePrompt"
            v-model="parallelMembers[index].instancePrompt"
            :data-testid="`parallel-member-${index + 1}-prompt`"
            :aria-label="`成員 ${index + 1} 視角`"
          />
        </label>
      </section>

      <section class="case-file-editor" data-testid="case-file-editor">
        <div class="case-file-editor-header">
          <div>
            <h4>案卷</h4>
            <p>建立時附加純文字或 Markdown，並指定可見角色。</p>
          </div>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            data-testid="add-case-file-button"
            @click="addCaseFile"
          >
            新增案卷
          </button>
        </div>

        <article
          v-for="(file, index) in caseFiles"
          :key="index"
          class="case-file-card"
          :data-testid="`case-file-${index + 1}`"
        >
          <div class="case-file-card-header">
            <strong>
              案卷 {{ index + 1 }}
              <span
                class="case-file-evidence-anchor"
                :data-testid="`case-file-${index + 1}-evidence-anchor`"
              >
                {{ draftEvidenceAnchor(index + 1) }}
              </span>
            </strong>
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              :data-testid="`remove-case-file-${index + 1}-button`"
              @click="removeCaseFile(index)"
            >
              移除
            </button>
          </div>
          <label class="topic-input-row">
            標題
            <input
              v-model="file.title"
              :data-testid="`case-file-${index + 1}-title`"
              :aria-label="`案卷 ${index + 1} 標題`"
            />
          </label>
          <label class="topic-input-row">
            內容
            <textarea
              v-model="file.content"
              :data-testid="`case-file-${index + 1}-content`"
              :aria-label="`案卷 ${index + 1} 內容`"
              :aria-invalid="
                caseFileLimits !== null &&
                codePointLength(file.content) > caseFileLimits.per_file_chars
              "
              :aria-describedby="
                caseFileLimits !== null &&
                codePointLength(file.content) > caseFileLimits.per_file_chars
                  ? `case-file-${index + 1}-char-count case-file-${index + 1}-limit-error`
                  : caseFileLimits
                    ? `case-file-${index + 1}-char-count`
                    : undefined
              "
            />
            <span
              v-if="caseFileLimits"
              :id="`case-file-${index + 1}-char-count`"
              class="case-file-char-count"
              :data-testid="`case-file-${index + 1}-char-count`"
            >
              {{ codePointLength(file.content) }} / {{ caseFileLimits.per_file_chars }} 字元
            </span>
            <span
              v-if="
                caseFileLimits &&
                codePointLength(file.content) > caseFileLimits.per_file_chars
              "
              :id="`case-file-${index + 1}-limit-error`"
              class="case-file-limit-error"
              :data-testid="`case-file-${index + 1}-limit-error`"
              role="alert"
            >
              案卷 {{ index + 1 }} 超過單份上限 {{ caseFileLimits.per_file_chars }} 字元
            </span>
          </label>
          <label class="case-file-upload">
            <span>匯入 .txt / .md</span>
            <input
              type="file"
              accept=".txt,.md,.markdown,text/plain,text/markdown"
              :data-testid="`case-file-${index + 1}-upload`"
              @change="loadCaseFileUpload(file, $event)"
            />
          </label>
          <fieldset class="case-file-visibility">
            <legend>可見角色</legend>
            <label
              v-for="role in selectedModeParticipants"
              :key="role.id"
              class="case-file-role-toggle"
              :style="{ '--role-color': role.color }"
            >
              <input
                type="checkbox"
                :checked="file.visibleRoles.includes(role.id)"
                :data-testid="`case-file-${index + 1}-role-${role.id}`"
                @change="toggleCaseFileRole(file, role.id)"
              />
              <span>{{ role.name }}</span>
            </label>
          </fieldset>
        </article>
        <p
          v-if="caseFiles.length && caseFileLimits"
          class="case-file-cost-note"
          data-testid="case-file-cost-note"
        >
          案卷全文會加入 prompt 並計入模型成本；目前 {{ totalCaseFileChars }} /
          {{ caseFileLimits.total_chars }} 字元，粗估約 {{ estimatedCaseFileTokens }} tokens。
          大型案卷可能超出模型 context window。
        </p>
        <p
          v-if="hasOversizedCaseFileTotal"
          class="case-file-limit-error"
          data-testid="case-file-total-limit-error"
          role="alert"
        >
          全部案卷超過總量上限 {{ caseFileLimits?.total_chars }} 字元
        </p>
      </section>

      <div class="participant-preview" data-testid="participant-preview">
        <span
          v-for="role in selectedModeParticipants"
          :key="role.id"
          class="participant-chip"
          :style="{ '--role-color': role.color }"
        >
          <img v-if="roleIcon(role.id)" :src="roleIcon(role.id)" class="role-icon" :alt="role.name" />
          <RoleSilhouette v-else :color="role.color" :size="16" />
          {{ role.name }}
        </span>
      </div>
      <section class="settings-role-grid" data-testid="new-case-model-assignments">
        <label
          v-for="participant in selectedModeParticipants"
          :key="participant.id"
          class="model-slot"
        >
          <span>{{ participant.name }}</span>
          <select
            v-model="draftModelAssignments[participant.id]"
            :data-testid="`new-case-${participant.id.toLowerCase()}-model-select`"
          >
            <option v-for="model in models" :key="model.id" :value="model.id">{{ modelDisplayLabel(model) }}</option>
          </select>
        </label>
      </section>
      <p v-if="models.length === 0" class="error" data-testid="new-case-model-error" role="alert">
        沒有可用模型，請先在 Settings 建立模型設定。
      </p>

      <p
        v-if="meetingCreationError"
        class="error"
        data-testid="new-case-server-error"
        role="alert"
      >
        {{ meetingCreationError }}
      </p>

      <button
        type="button"
        class="btn btn-primary create-meeting-cta"
        data-testid="create-meeting-button"
        @click="submit"
        :disabled="loading || caseFileLimitsLoading || !caseFileLimits || !title.trim() || !goal.trim() || hasEmptyRequiredInput || hasIncompleteModelAssignment || hasIncompleteCaseFile || hasOversizedCaseFile || hasOversizedCaseFileTotal"
      >
        建立
      </button>
    </div>
  </Modal>
</template>
