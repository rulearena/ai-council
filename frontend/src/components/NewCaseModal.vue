<script setup lang="ts">
// Two-step New Case flow (spec.md 16.6): (1) browse the mode catalog, (2) confirm
// participants and the topic. Which cards are actually selectable is data-driven
// (`mode.available`, sourced from GET /modes - see modes.ts's refreshModeCatalog): as of
// slice B that's every `relay` mode (red-blue/courtroom/debate), while `parallel` modes
// still render fully (name/tagline/when-to-use/SOP) but stay disabled until slice C wires
// up the parallel executor (spec.md 16.7). Choosing red-blue and creating still ends up
// calling createNewMeeting() the same way the old flat form did, so a user who never
// looks at the mode picker gets today's behavior unchanged.
import { computed, inject, ref, watch } from 'vue'
import { councilKey, roleIcon } from '../composables/useCouncil'
import { modeCatalog, type ModeDefinition } from '../modes'
import Modal from './Modal.vue'
import ModeCard from './ModeCard.vue'
import RoleSilhouette from './RoleSilhouette.vue'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const store = inject(councilKey)!
const { topic, loading, createNewMeeting } = store

type Step = 'mode' | 'participants'
const step = ref<Step>('mode')
const selectedModeId = ref<string>('red-blue')
const selectedMode = computed<ModeDefinition>(
  () => modeCatalog.find((mode) => mode.id === selectedModeId.value) ?? modeCatalog[0],
)

// Values for the selected mode's `kind: 'text'` inputs (e.g. debate's position_a/
// position_b - spec.md 16.2), keyed by input id. `persona-list` inputs don't appear here:
// no mode that carries one is buildable yet (all `category: 'parallel'` modes stay
// `available: false` until slice C), so this form only ever needs to render plain text
// fields.
const inputValues = ref<Record<string, string>>({})
const textInputs = computed(() => selectedMode.value.inputs.filter((input) => input.kind === 'text'))
const hasEmptyRequiredInput = computed(() =>
  textInputs.value.some((input) => !(inputValues.value[input.id] ?? '').trim()),
)

// Reopening the modal always starts over at the mode picker - a half-finished previous
// attempt (e.g. closed after picking a mode but before creating) shouldn't linger.
watch(
  () => props.show,
  (visible) => {
    if (visible) {
      step.value = 'mode'
      inputValues.value = {}
    }
  },
)

function chooseMode(mode: ModeDefinition) {
  if (!mode.available) return
  selectedModeId.value = mode.id
  inputValues.value = {}
  step.value = 'participants'
}

function backToModePicker() {
  step.value = 'mode'
}

async function submit() {
  await createNewMeeting(selectedMode.value.id, { ...inputValues.value })
  emit('close')
}
</script>

<template>
  <Modal :show="show" title="New Case" test-id="new-case-modal" close-test-id="new-case-close-button" @close="$emit('close')">
    <div v-if="step === 'mode'" class="mode-picker" data-testid="mode-picker-step">
      <p class="mode-picker-hint">選擇本次會議的模式 —— 灰階「即將推出」卡片尚未開放建立：</p>
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

      <div class="participant-preview" data-testid="participant-preview">
        <span
          v-for="role in selectedMode.roles"
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
        :disabled="loading || !topic.trim() || hasEmptyRequiredInput"
      >
        建立
      </button>
    </div>
  </Modal>
</template>
