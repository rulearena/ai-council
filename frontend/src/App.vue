<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  addMeetingMessage,
  cancelMeeting,
  closeMeeting,
  createMeeting,
  deleteMeeting,
  getMeeting,
  getMeetings,
  getModels,
  getTranscript,
  requestRoleResponse,
  requestRoleSequence,
  retryStep,
  startMeeting,
  subscribeMeetingEvents,
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
type ModelTestView = {
  status: 'unknown' | 'available' | 'unavailable'
  testedAt: string
  error: string
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
const modelTestResults = ref<Record<CouncilRole, ModelTestView>>({
  Blue: { status: 'unknown', testedAt: '', error: '' },
  Red: { status: 'unknown', testedAt: '', error: '' },
  Judge: { status: 'unknown', testedAt: '', error: '' },
})
const chairMessage = ref('')
const selectedSequencePresetId = ref(sequencePresets[0].id)
const meetingSearch = ref('')
const statusFilter = ref<'all' | Meeting['status']>('all')
const transcript = ref('')
const loading = ref(false)
const error = ref('')
let closeEventStream: (() => void) | null = null

const events = computed(() => selectedMeeting.value?.events ?? [])
const isTerminalMeeting = computed(() =>
  events.value.some((event) => event.status === 'closed' || event.status === 'cancelled'),
)
const isMeetingRunning = computed(() => selectedMeeting.value?.activity_status === 'running')
const startButtonLabel = computed(() => {
  if (isMeetingRunning.value) return '執行中...'
  return events.value.length ? '繼續討論' : '開始'
})
const selectedSequencePreset = computed(
  () => sequencePresets.find((preset) => preset.id === selectedSequencePresetId.value) ?? sequencePresets[0],
)
const operationStatus = computed(() => {
  if (loading.value) return 'running'
  return selectedMeeting.value?.activity_status ?? 'idle'
})
const filteredMeetings = computed(() => {
  const query = meetingSearch.value.trim().toLowerCase()
  return meetings.value
    .filter((meeting) => {
      const matchesStatus = statusFilter.value === 'all' || meeting.status === statusFilter.value
      const searchable = `${meeting.topic} ${meeting.meeting_id} ${meeting.last_step_id ?? ''}`.toLowerCase()
      return matchesStatus && (!query || searchable.includes(query))
    })
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
})
const roleOutputEvents = computed(() =>
  events.value.filter((event) => event.parsed_output),
)
const canRun = computed(
  () =>
    selectedMeeting.value &&
    !isTerminalMeeting.value &&
    !isMeetingRunning.value &&
    selectedModels.value.Blue &&
    selectedModels.value.Red &&
    selectedModels.value.Judge,
)

onMounted(async () => {
  await refreshAll()
})

onUnmounted(() => closeEventStream?.())

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
  connectMeetingEvents(meetingId)
}

async function startSelectedMeeting() {
  if (!selectedMeeting.value || !canRun.value) return
  const meetingId = selectedMeeting.value.meeting_id
  connectMeetingEvents(meetingId)
  await runAction(async () => {
    await startMeeting(meetingId, selectedModels.value)
    if (selectedMeeting.value?.meeting_id === meetingId) {
      selectedMeeting.value = { ...selectedMeeting.value, activity_status: 'running' }
    }
  })
}

function connectMeetingEvents(meetingId: string) {
  closeEventStream?.()
  closeEventStream = subscribeMeetingEvents(
    meetingId,
    (message) => {
      if (selectedMeeting.value?.meeting_id !== meetingId) return
      const currentEvents = message.type === 'snapshot' ? [] : (selectedMeeting.value.events ?? [])
      const nextEvents = [...currentEvents, ...message.events]
      const latestEvent = nextEvents.at(-1)
      selectedMeeting.value = {
        ...selectedMeeting.value,
        events: nextEvents,
        activity_status: message.activity_status,
        last_step_id: latestEvent?.step_id ?? null,
        updated_at: latestEvent?.created_at ?? selectedMeeting.value.updated_at,
      }
      if (message.events.length) {
        selectedEvent.value = latestEvent ?? null
        void refreshMeetingOutputs(meetingId, message.activity_status)
      }
    },
    () => {
      error.value = 'Meeting event stream disconnected.'
    },
  )
}

async function refreshMeetingOutputs(meetingId: string, activityStatus: Meeting['activity_status']) {
  try {
    transcript.value = await getTranscript(meetingId)
    if (activityStatus !== 'running') {
      meetings.value = await getMeetings()
    }
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : String(caught)
  }
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

async function deleteExistingMeeting(meeting: Meeting) {
  if (!window.confirm(`確定刪除「${meeting.topic}」？此操作無法復原。`)) return
  await runAction(async () => {
    await deleteMeeting(meeting.meeting_id)
    if (selectedMeeting.value?.meeting_id === meeting.meeting_id) {
      closeEventStream?.()
      closeEventStream = null
      selectedMeeting.value = null
      selectedEvent.value = null
      transcript.value = ''
    }
    meetings.value = await getMeetings()
  })
}

async function testSelectedModel(role: CouncilRole) {
  const modelId = selectedModels.value[role]
  if (!modelId) return
  await runAction(async () => {
    const result = await testModel(modelId)
    modelTestResults.value[role] = {
      status: result.status,
      testedAt: result.tested_at,
      error: result.error ?? '',
    }
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

async function retrySelectedStep(event: MeetingEvent) {
  if (!selectedMeeting.value || !canRun.value || event.status !== 'failed') return
  await runAction(async () => {
    await retryStep(selectedMeeting.value!.meeting_id, event.step_id, selectedModels.value)
    await openMeeting(selectedMeeting.value!.meeting_id)
  })
}

function formatDateTime(value: string | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
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
      <div class="meeting-filters" data-testid="meeting-filters">
        <input
          v-model="meetingSearch"
          aria-label="搜尋會議"
          placeholder="搜尋會議..."
          data-testid="meeting-search-input"
        />
        <select v-model="statusFilter" data-testid="meeting-status-filter">
          <option value="all">全部</option>
          <option value="open">open</option>
          <option value="closed">closed</option>
          <option value="cancelled">cancelled</option>
        </select>
      </div>
      <div
        v-for="meeting in filteredMeetings"
        :key="meeting.meeting_id"
        class="meeting-row"
        data-testid="meeting-list-item"
      >
        <button
          type="button"
          class="meeting-item"
          :class="{ active: selectedMeeting?.meeting_id === meeting.meeting_id }"
          @click="openMeeting(meeting.meeting_id)"
        >
          <span>{{ meeting.topic }}</span>
          <em class="status-badge">{{ meeting.status }}</em>
          <strong>{{ meeting.activity_status }}</strong>
          <small>更新 {{ formatDateTime(meeting.updated_at) }}</small>
          <small>{{ meeting.meeting_id }}</small>
        </button>
        <button
          type="button"
          class="delete-meeting-button"
          data-testid="delete-meeting-button"
          :aria-label="`刪除 ${meeting.topic}`"
          :disabled="loading || meeting.activity_status === 'running'"
          @click="deleteExistingMeeting(meeting)"
        >
          刪除
        </button>
      </div>
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
        <span>
          Blue: {{ modelTestResults.Blue.status }}
          <small v-if="modelTestResults.Blue.testedAt">測試 {{ formatDateTime(modelTestResults.Blue.testedAt) }}</small>
          <em v-if="modelTestResults.Blue.error">{{ modelTestResults.Blue.error }}</em>
        </span>
        <span>
          Red: {{ modelTestResults.Red.status }}
          <small v-if="modelTestResults.Red.testedAt">測試 {{ formatDateTime(modelTestResults.Red.testedAt) }}</small>
          <em v-if="modelTestResults.Red.error">{{ modelTestResults.Red.error }}</em>
        </span>
        <span>
          Judge: {{ modelTestResults.Judge.status }}
          <small v-if="modelTestResults.Judge.testedAt">測試 {{ formatDateTime(modelTestResults.Judge.testedAt) }}</small>
          <em v-if="modelTestResults.Judge.error">{{ modelTestResults.Judge.error }}</em>
        </span>
      </section>

      <section class="operation-status" data-testid="operation-status">
        <span>狀態：{{ operationStatus }}</span>
        <span v-if="selectedMeeting?.last_step_id">最後步驟：{{ selectedMeeting.last_step_id }}</span>
        <span v-if="selectedMeeting">更新：{{ formatDateTime(selectedMeeting.updated_at) }}</span>
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
            <em v-if="selectedMeeting" class="status-badge">{{ selectedMeeting.activity_status }}</em>
          </div>
          <div
            v-for="event in events"
            :key="event.event_id"
            class="timeline-row"
          >
            <button type="button" class="timeline-main" @click="selectedEvent = event">
              <span>{{ event.role }}</span>
              <strong>{{ event.step_id }}</strong>
              <em>{{ event.status }}</em>
              <small>{{ formatDateTime(event.created_at) }}</small>
            </button>
            <button
              v-if="event.status === 'failed'"
              type="button"
              class="retry-button"
              data-testid="retry-step-button"
              @click="retrySelectedStep(event)"
              :disabled="loading || !canRun"
            >
              Retry
            </button>
          </div>
        </section>

        <section class="debug" data-testid="debug-panel">
          <h2>Debug</h2>
          <pre>{{ selectedEvent ? JSON.stringify(selectedEvent, null, 2) : 'No event selected' }}</pre>
        </section>
      </div>

      <section class="role-output-panel" data-testid="role-output-panel">
        <h2>Role Outputs</h2>
        <div v-if="roleOutputEvents.length" class="role-output-grid">
          <article
            v-for="event in roleOutputEvents"
            :key="`${event.event_id}:output`"
            class="role-output-card"
          >
            <header>
              <strong>{{ event.role }}</strong>
              <span>{{ event.step_id }}</span>
            </header>
            <p>{{ event.parsed_output?.summary }}</p>
            <h3>Arguments</h3>
            <ul>
              <li v-for="argument in event.parsed_output?.arguments" :key="argument.title">
                <strong>{{ argument.title }}</strong>
                <span>{{ argument.detail }}</span>
              </li>
            </ul>
            <h3>Risks</h3>
            <ul>
              <li v-for="risk in event.parsed_output?.risks" :key="risk.title">
                <strong>{{ risk.title }}</strong>
                <span>{{ risk.detail }}</span>
              </li>
            </ul>
            <h3>Recommendation</h3>
            <p>{{ event.parsed_output?.recommendation }}</p>
          </article>
        </div>
        <p v-else>No role output yet</p>
      </section>

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
