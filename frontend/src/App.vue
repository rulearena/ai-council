<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  addMeetingMessage,
  cancelMeeting,
  closeMeeting,
  createMeeting,
  getMeeting,
  getMeetings,
  getModels,
  getTranscript,
  requestRoleResponse,
  requestRoleSequence,
  startMeeting,
  testModel,
  transcriptDownloadUrl,
  type Meeting,
  type MeetingEvent,
  type ModelConfig,
} from './api'

type CouncilRole = 'Blue' | 'Red' | 'Judge'
type SequencePreset = {
  id: string
  label: string
  roles: CouncilRole[]
}

const sequencePresets: SequencePreset[] = [
  { id: 'red-blue-judge', label: 'Red -> Blue -> Judge', roles: ['Red', 'Blue', 'Judge'] },
  { id: 'blue-red-judge', label: 'Blue -> Red -> Judge', roles: ['Blue', 'Red', 'Judge'] },
  { id: 'red-blue', label: 'Red -> Blue', roles: ['Red', 'Blue'] },
  { id: 'judge-only', label: 'Judge only', roles: ['Judge'] },
]

const models = ref<ModelConfig[]>([])
const meetings = ref<Meeting[]>([])
const selectedMeeting = ref<Meeting | null>(null)
const selectedEvent = ref<MeetingEvent | null>(null)
const topic = ref('先做後端核心流程')
const selectedModels = ref({ Blue: '', Red: '', Judge: '' })
const modelTestResults = ref<Record<CouncilRole, string>>({
  Blue: 'unknown',
  Red: 'unknown',
  Judge: 'unknown',
})
const chairMessage = ref('')
const selectedSequencePresetId = ref(sequencePresets[0].id)
const transcript = ref('')
const loading = ref(false)
const error = ref('')

const events = computed(() => selectedMeeting.value?.events ?? [])
const isTerminalMeeting = computed(() =>
  events.value.some((event) => event.status === 'closed' || event.status === 'cancelled'),
)
const startButtonLabel = computed(() => (events.value.length ? '繼續討論' : '開始'))
const selectedSequencePreset = computed(
  () => sequencePresets.find((preset) => preset.id === selectedSequencePresetId.value) ?? sequencePresets[0],
)
const canRun = computed(
  () =>
    selectedMeeting.value &&
    !isTerminalMeeting.value &&
    selectedModels.value.Blue &&
    selectedModels.value.Red &&
    selectedModels.value.Judge,
)

onMounted(async () => {
  await refreshAll()
})

async function refreshAll() {
  error.value = ''
  models.value = await getModels()
  meetings.value = await getMeetings()
  const firstModel = models.value[0]?.id ?? ''
  selectedModels.value = {
    Blue: selectedModels.value.Blue || firstModel,
    Red: selectedModels.value.Red || firstModel,
    Judge: selectedModels.value.Judge || firstModel,
  }
  if (selectedMeeting.value) {
    await openMeeting(selectedMeeting.value.meeting_id)
  }
}

async function createNewMeeting() {
  await runAction(async () => {
    const meeting = await createMeeting(topic.value)
    meetings.value = await getMeetings()
    await openMeeting(meeting.meeting_id)
  })
}

async function openMeeting(meetingId: string) {
  selectedMeeting.value = await getMeeting(meetingId)
  selectedEvent.value = selectedMeeting.value.events?.at(-1) ?? null
  transcript.value = await getTranscript(meetingId)
}

async function startSelectedMeeting() {
  if (!selectedMeeting.value || !canRun.value) return
  await runAction(async () => {
    await startMeeting(selectedMeeting.value!.meeting_id, selectedModels.value)
    await openMeeting(selectedMeeting.value!.meeting_id)
  })
}

async function cancelSelectedMeeting() {
  if (!selectedMeeting.value) return
  await runAction(async () => {
    await cancelMeeting(selectedMeeting.value!.meeting_id)
    await openMeeting(selectedMeeting.value!.meeting_id)
  })
}

async function closeSelectedMeeting() {
  if (!selectedMeeting.value) return
  await runAction(async () => {
    await closeMeeting(selectedMeeting.value!.meeting_id)
    await openMeeting(selectedMeeting.value!.meeting_id)
  })
}

async function testSelectedModel(role: CouncilRole) {
  const modelId = selectedModels.value[role]
  if (!modelId) return
  await runAction(async () => {
    const result = await testModel(modelId)
    modelTestResults.value[role] = result.error
      ? `${result.status}: ${result.error}`
      : result.status
  })
}

async function sendChairMessage() {
  if (!selectedMeeting.value || !chairMessage.value.trim()) return
  await runAction(async () => {
    await addMeetingMessage(selectedMeeting.value!.meeting_id, chairMessage.value.trim())
    chairMessage.value = ''
    await openMeeting(selectedMeeting.value!.meeting_id)
  })
}

async function requestSelectedRoleResponse(role: CouncilRole) {
  if (!selectedMeeting.value || !canRun.value) return
  await runAction(async () => {
    await requestRoleResponse(selectedMeeting.value!.meeting_id, role, selectedModels.value)
    await openMeeting(selectedMeeting.value!.meeting_id)
  })
}

async function requestSelectedRoleSequence() {
  if (!selectedMeeting.value || !canRun.value) return
  await runAction(async () => {
    await requestRoleSequence(
      selectedMeeting.value!.meeting_id,
      selectedSequencePreset.value.roles,
      selectedModels.value,
    )
    await openMeeting(selectedMeeting.value!.meeting_id)
  })
}

async function runAction(action: () => Promise<void>) {
  loading.value = true
  error.value = ''
  try {
    await action()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : String(caught)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="app-shell">
    <aside class="sidebar" data-testid="meeting-list">
      <div class="sidebar-header">
        <h1>AI 眾議院</h1>
        <button type="button" @click="refreshAll" :disabled="loading">↻</button>
      </div>
      <div class="create-box">
        <input v-model="topic" aria-label="會議主題" />
        <button
          type="button"
          data-testid="create-meeting-button"
          @click="createNewMeeting"
          :disabled="loading || !topic.trim()"
        >
          建立
        </button>
      </div>
      <button
        v-for="meeting in meetings"
        :key="meeting.meeting_id"
        type="button"
        class="meeting-item"
        :class="{ active: selectedMeeting?.meeting_id === meeting.meeting_id }"
        @click="openMeeting(meeting.meeting_id)"
      >
        <span>{{ meeting.topic }}</span>
        <em class="status-badge">{{ meeting.status }}</em>
        <small>{{ meeting.meeting_id }}</small>
      </button>
    </aside>

    <section class="workspace">
      <header class="toolbar">
        <label>
          Blue
          <span class="model-control">
            <select v-model="selectedModels.Blue" data-testid="blue-model-select">
              <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
            </select>
            <button
              type="button"
              data-testid="test-blue-model-button"
              @click="testSelectedModel('Blue')"
              :disabled="loading || !selectedModels.Blue"
            >
              Test
            </button>
          </span>
        </label>
        <label>
          Red
          <span class="model-control">
            <select v-model="selectedModels.Red" data-testid="red-model-select">
              <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
            </select>
            <button
              type="button"
              data-testid="test-red-model-button"
              @click="testSelectedModel('Red')"
              :disabled="loading || !selectedModels.Red"
            >
              Test
            </button>
          </span>
        </label>
        <label>
          Judge
          <span class="model-control">
            <select v-model="selectedModels.Judge" data-testid="judge-model-select">
              <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
            </select>
            <button
              type="button"
              data-testid="test-judge-model-button"
              @click="testSelectedModel('Judge')"
              :disabled="loading || !selectedModels.Judge"
            >
              Test
            </button>
          </span>
        </label>
        <button
          type="button"
          data-testid="start-meeting-button"
          @click="startSelectedMeeting"
          :disabled="loading || !canRun"
        >
          {{ startButtonLabel }}
        </button>
        <button
          type="button"
          data-testid="cancel-meeting-button"
          @click="cancelSelectedMeeting"
          :disabled="loading || !selectedMeeting || isTerminalMeeting"
        >
          取消
        </button>
        <button
          type="button"
          data-testid="close-meeting-button"
          @click="closeSelectedMeeting"
          :disabled="loading || !selectedMeeting || isTerminalMeeting"
        >
          結案
        </button>
      </header>

      <p v-if="error" class="error">{{ error }}</p>

      <section class="model-test-status" data-testid="model-test-status">
        <span>Blue: {{ modelTestResults.Blue }}</span>
        <span>Red: {{ modelTestResults.Red }}</span>
        <span>Judge: {{ modelTestResults.Judge }}</span>
      </section>

      <section class="chair-panel">
        <textarea
          v-model="chairMessage"
          data-testid="chair-message-input"
          aria-label="主席發言"
          placeholder="主席發言或補充限制..."
          :disabled="loading || !selectedMeeting || isTerminalMeeting"
        />
        <button
          type="button"
          data-testid="send-chair-message-button"
          @click="sendChairMessage"
          :disabled="loading || !selectedMeeting || isTerminalMeeting || !chairMessage.trim()"
        >
          送出主席發言
        </button>
      </section>

      <section class="role-actions" data-testid="role-response-actions">
        <button
          type="button"
          data-testid="request-blue-response-button"
          @click="requestSelectedRoleResponse('Blue')"
          :disabled="loading || !canRun"
        >
          請 Blue 回應
        </button>
        <button
          type="button"
          data-testid="request-red-response-button"
          @click="requestSelectedRoleResponse('Red')"
          :disabled="loading || !canRun"
        >
          請 Red 回應
        </button>
        <button
          type="button"
          data-testid="request-judge-response-button"
          @click="requestSelectedRoleResponse('Judge')"
          :disabled="loading || !canRun"
        >
          請 Judge 回應
        </button>
      </section>

      <section class="sequence-panel" data-testid="role-sequence-controls">
        <label>
          自動接續
          <select v-model="selectedSequencePresetId" data-testid="sequence-preset-select">
            <option
              v-for="preset in sequencePresets"
              :key="preset.id"
              :value="preset.id"
            >
              {{ preset.label }}
            </option>
          </select>
        </label>
        <button
          type="button"
          data-testid="run-sequence-button"
          @click="requestSelectedRoleSequence"
          :disabled="loading || !canRun"
        >
          執行序列
        </button>
      </section>

      <div class="main-grid">
        <section class="timeline" data-testid="step-timeline">
          <div class="section-title">
            <h2>{{ selectedMeeting?.topic ?? '尚未選擇會議' }}</h2>
            <em v-if="selectedMeeting" class="status-badge">{{ selectedMeeting.status }}</em>
          </div>
          <button
            v-for="event in events"
            :key="event.event_id"
            type="button"
            class="timeline-row"
            @click="selectedEvent = event"
          >
            <span>{{ event.role }}</span>
            <strong>{{ event.step_id }}</strong>
            <em>{{ event.status }}</em>
          </button>
        </section>

        <section class="debug" data-testid="debug-panel">
          <h2>Debug</h2>
          <pre>{{ selectedEvent ? JSON.stringify(selectedEvent, null, 2) : 'No event selected' }}</pre>
        </section>
      </div>

      <section class="transcript" data-testid="transcript-preview">
        <div class="transcript-header">
          <h2>Transcript</h2>
          <a
            v-if="selectedMeeting"
            :href="transcriptDownloadUrl(selectedMeeting.meeting_id)"
            target="_blank"
            rel="noreferrer"
          >
            下載 Markdown
          </a>
        </div>
        <pre>{{ transcript || 'No transcript yet' }}</pre>
      </section>
    </section>
  </main>
</template>
