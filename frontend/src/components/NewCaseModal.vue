<script setup lang="ts">
// Two-step New Case flow (spec.md 16.6): (1) browse the mode catalog, (2) confirm
// participants and the topic. Which cards are actually selectable is data-driven
// (`mode.available`, sourced from GET /modes - see modes.ts's refreshModeCatalog): as of
// slice C that's every backend-supported mode, including parallel modes. Choosing red-blue
// and creating still ends up calling createNewMeeting() the same way the old flat form did,
// so a user who never looks at the mode picker gets today's behavior unchanged.
import { computed, inject, ref, watch } from 'vue'
import { councilKey, roleIcon } from '../composables/useCouncil'
import { DEFAULT_MODE_ID, modeCatalog, type ModeDefinition } from '../modes'
import Modal from './Modal.vue'
import ModeCard from './ModeCard.vue'
import RoleSilhouette from './RoleSilhouette.vue'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const store = inject(councilKey)!
const { topic, loading, createNewMeeting } = store

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
const parallelMemberCount = ref(2)
const parallelMembers = ref<Array<{ displayName: string; instancePrompt: string }>>([])
const textInputs = computed(() => selectedMode.value.inputs.filter((input) => input.kind === 'text'))
const hasEmptyRequiredInput = computed(() =>
  textInputs.value.some((input) => !(inputValues.value[input.id] ?? '').trim()),
)
const hasIncompleteCaseFile = computed(() =>
  caseFiles.value.some(
    (file) => !file.title.trim() || !file.content.trim() || file.visibleRoles.length === 0,
  ),
)
const selectedModeParticipants = computed(() => {
  const mode = selectedMode.value
  if (mode.category !== 'parallel' || !mode.fanout || !mode.synthesis) return mode.roles
  const members = Array.from({ length: parallelMemberCount.value }, (_, index) => ({
    id: `${mode.fanout!.role}-${index + 1}`,
    name: parallelMembers.value[index]?.displayName || `委員 ${index + 1}`,
    color: '#4d8dff',
    kind: 'member' as const,
  }))
  const synthesizers = mode.roles.filter((role) => role.kind === 'synthesizer')
  return [...members, ...synthesizers]
})

// Reopening the modal always starts over at the mode picker - a half-finished previous
// attempt (e.g. closed after picking a mode but before creating) shouldn't linger.
watch(
  () => props.show,
  (visible) => {
    if (visible) {
      step.value = 'mode'
      inputValues.value = {}
      caseFiles.value = []
      resetParallelMembers(selectedMode.value)
    }
  },
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
  step.value = 'participants'
}

function backToModePicker() {
  step.value = 'mode'
}

async function submit() {
  if (
    await createNewMeeting(
      selectedMode.value.id,
      { ...inputValues.value },
      buildParticipants(),
      buildCaseFiles(),
    )
  ) {
    emit('close')
  }
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
}

function addCaseFile() {
  caseFiles.value.push({ title: '', content: '', visibleRoles: [] })
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

function buildCaseFiles() {
  return caseFiles.value.map((file) => ({
    title: file.title.trim(),
    content: file.content,
    visible_roles: file.visibleRoles,
  }))
}

function buildParticipants() {
  const mode = selectedMode.value
  if (mode.category !== 'parallel' || !mode.fanout || !mode.synthesis) return []
  const members = Array.from({ length: parallelMemberCount.value }, (_, index) => ({
    role_id: `${mode.fanout!.role}-${index + 1}`,
    display_name: parallelMembers.value[index]?.displayName || `委員 ${index + 1}`,
    instance_prompt: parallelMembers.value[index]?.instancePrompt || null,
  }))
  return [
    ...members,
    ...mode.roles
      .filter((role) => role.kind === 'synthesizer')
      .map((role) => ({ role_id: role.id, display_name: role.name })),
  ]
}
</script>

<template>
  <Modal :show="show" title="New Case" test-id="new-case-modal" close-test-id="new-case-close-button" @close="$emit('close')">
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
        會議主題
        <input v-model="topic" aria-label="會議主題" />
      </label>

      <label v-for="input in textInputs" :key="input.id" class="topic-input-row">
        {{ input.label }}
        <input
          v-model="inputValues[input.id]"
          :data-testid="`mode-input-${input.id}`"
          :aria-label="input.label"
        />
      </label>

      <section v-if="selectedMode.category === 'parallel' && selectedMode.fanout" class="parallel-member-editor" data-testid="parallel-member-editor">
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
            <strong>案卷 {{ index + 1 }}</strong>
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
      <p class="participant-setup-note">模型可於建立後在 Settings 中為每個角色指派。</p>

      <button
        type="button"
        class="btn btn-primary create-meeting-cta"
        data-testid="create-meeting-button"
        @click="submit"
        :disabled="loading || !topic.trim() || hasEmptyRequiredInput || hasIncompleteCaseFile"
      >
        建立
      </button>
    </div>
  </Modal>
</template>
