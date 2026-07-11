<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import roleBlueIcon from './assets/roles/blue.png'
import roleRedIcon from './assets/roles/red.png'
import roleJudgeIcon from './assets/roles/judge.png'
import {
  addMeetingMessage,
  cancelMeeting,
  closeMeeting,
  correctMeetingMessage,
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
  updateMeetingPinned,
  updateMeetingTags,
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

const councilRoles: CouncilRole[] = ['Blue', 'Red', 'Judge']

// Backend fixed round flow (backend/ai_council/meetings/runner.py STEPS): retrying a
// failed step re-runs it plus every step after it, in the same synchronous call.
const FIXED_ROUND_STEP_ROLES: Record<string, CouncilRole[]> = {
  'blue-propose': ['Blue', 'Red', 'Blue', 'Judge'],
  'red-critique': ['Red', 'Blue', 'Judge'],
  'blue-revise': ['Blue', 'Judge'],
  'judge-decide': ['Judge'],
}

type RoleCardStatus = 'waiting' | 'thinking' | 'completed' | 'failed'

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
const transcriptSearchQuery = ref('')
const transcriptSearchResults = ref<Meeting[] | null>(null)
const transcript = ref('')
const loading = ref(false)
const error = ref('')
let closeEventStream: (() => void) | null = null

// Roles the backend has been asked to run but hasn't confirmed completed/failed yet.
// The backend only emits completed/failed events (no "running" event), so this queue
// is the sole source of the "thinking" state: pendingRoles[0] is thinking, the rest are queued.
const pendingRoles = ref<CouncilRole[]>([])

const meetingIdCopied = ref(false)
let meetingIdCopiedTimeout: ReturnType<typeof setTimeout> | null = null

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
      const searchable = `${meeting.topic} ${meeting.meeting_id} ${meeting.last_step_id ?? ''} ${meeting.tags.join(' ')}`.toLowerCase()
      return matchesStatus && (!query || searchable.includes(query))
    })
    .sort(
      (left, right) =>
        Number(right.pinned) - Number(left.pinned) ||
        right.updated_at.localeCompare(left.updated_at),
    )
})
const roleOutputEvents = computed(() =>
  events.value.filter((event) => event.parsed_output),
)
const latestRoleEvent = computed<Record<CouncilRole, MeetingEvent | null>>(() => {
  const result: Record<CouncilRole, MeetingEvent | null> = { Blue: null, Red: null, Judge: null }
  for (const event of events.value) {
    if (isCouncilRole(event.role) && (event.status === 'completed' || event.status === 'failed')) {
      result[event.role] = event
    }
  }
  return result
})
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
  await runAction(refreshAll)
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
  // Only reset the queue when actually switching meetings. requestSelectedRoleResponse /
  // requestSelectedRoleSequence / retrySelectedStep call openMeeting on the SAME meeting
  // right after enqueuing roles, so clearing unconditionally would erase what was just pushed.
  if (meetingId !== selectedMeeting.value?.meeting_id) {
    pendingRoles.value = []
    meetingIdCopied.value = false
  }
  selectedMeeting.value = await getMeeting(meetingId)
  selectedEvent.value = selectedMeeting.value.events?.at(-1) ?? null
  transcript.value = await getTranscript(meetingId)
  connectMeetingEvents(meetingId)
}

async function startSelectedMeeting() {
  if (!selectedMeeting.value || !canRun.value) return
  const meetingId = selectedMeeting.value.meeting_id
  pendingRoles.value.push('Blue', 'Red', 'Blue', 'Judge')
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
      applyPendingRoleUpdates(message.events, message.activity_status)
      if (message.events.length) {
        selectedEvent.value = latestEvent ?? null
        void refreshMeetingOutputs(meetingId, message.activity_status)
      }
    },
    () => {
      error.value = 'Meeting event stream disconnected.'
      pendingRoles.value = []
    },
  )
}

function applyPendingRoleUpdates(newEvents: MeetingEvent[], activityStatus: Meeting['activity_status']) {
  for (const event of newEvents) {
    if (!isCouncilRole(event.role)) continue
    if (event.status !== 'completed' && event.status !== 'failed') continue
    const queueIndex = pendingRoles.value.indexOf(event.role)
    if (queueIndex === -1) continue
    if (event.status === 'failed') {
      // A failed step halts every remaining step in the same batch on the backend
      // (fixed round / role sequence / retry all stop after the first failure).
      pendingRoles.value = []
    } else {
      pendingRoles.value.splice(queueIndex, 1)
    }
  }
  if (activityStatus === 'closed' || activityStatus === 'cancelled') {
    pendingRoles.value = []
  }
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
      pendingRoles.value = []
    }
    meetings.value = await getMeetings()
    if (transcriptSearchResults.value) {
      transcriptSearchResults.value = transcriptSearchResults.value.filter(
        (candidate) => candidate.meeting_id !== meeting.meeting_id,
      )
    }
  })
}

async function editMeetingTags(meeting: Meeting) {
  const input = window.prompt('編輯標籤（用逗號分隔）：', meeting.tags.join(', '))
  if (input === null) return
  const tags = input
    .split(',')
    .map((tag) => tag.trim())
    .filter((tag) => tag.length > 0)
  await runAction(async () => {
    await updateMeetingTags(meeting.meeting_id, tags)
    meetings.value = await getMeetings()
    if (selectedMeeting.value?.meeting_id === meeting.meeting_id) {
      selectedMeeting.value = meetings.value.find((m) => m.meeting_id === meeting.meeting_id) ?? null
    }
  })
}

async function toggleMeetingPinned(meeting: Meeting) {
  await runAction(async () => {
    await updateMeetingPinned(meeting.meeting_id, !meeting.pinned)
    meetings.value = await getMeetings()
    if (selectedMeeting.value?.meeting_id === meeting.meeting_id) {
      selectedMeeting.value = meetings.value.find((m) => m.meeting_id === meeting.meeting_id) ?? null
    }
  })
}

async function searchTranscripts() {
  const query = transcriptSearchQuery.value.trim()
  if (!query) return
  await runAction(async () => {
    transcriptSearchResults.value = await getMeetings(query)
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

async function correctSelectedMessage(event: MeetingEvent) {
  if (!selectedMeeting.value) return
  const corrected = window.prompt('修正主席發言：', event.content ?? '')
  if (corrected === null) return
  const trimmed = corrected.trim()
  if (!trimmed || trimmed === event.content) return
  await runAction(async () => {
    await correctMeetingMessage(selectedMeeting.value!.meeting_id, event.event_id, trimmed)
    await openMeeting(selectedMeeting.value!.meeting_id)
  })
}

async function requestSelectedRoleResponse(role: CouncilRole) {
  if (!selectedMeeting.value || !canRun.value) return
  pendingRoles.value.push(role)
  await runAction(async () => {
    await requestRoleResponse(selectedMeeting.value!.meeting_id, role, selectedModels.value)
    await openMeeting(selectedMeeting.value!.meeting_id)
  })
}

async function requestSelectedRoleSequence() {
  if (!selectedMeeting.value || !canRun.value) return
  pendingRoles.value.push(...selectedSequencePreset.value.roles)
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
  const baseStepId = event.base_step_id ?? event.step_id
  const remainingRoles = FIXED_ROUND_STEP_ROLES[baseStepId] ?? (isCouncilRole(event.role) ? [event.role] : [])
  pendingRoles.value.push(...remainingRoles)
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

async function copyMeetingId(meetingId: string) {
  try {
    await navigator.clipboard.writeText(meetingId)
    meetingIdCopied.value = true
    if (meetingIdCopiedTimeout) clearTimeout(meetingIdCopiedTimeout)
    meetingIdCopiedTimeout = setTimeout(() => {
      meetingIdCopied.value = false
    }, 1500)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : String(caught)
  }
}

const ROLE_ICONS: Partial<Record<string, string>> = {
  Blue: roleBlueIcon,
  Red: roleRedIcon,
  Judge: roleJudgeIcon,
}

const ROLE_CLASSES: Partial<Record<string, string>> = {
  Blue: 'role-blue',
  Red: 'role-red',
  Judge: 'role-judge',
}

function roleIcon(role: string): string | undefined {
  return ROLE_ICONS[role]
}

function roleClass(role: string): string {
  return ROLE_CLASSES[role] ?? ''
}

function isCouncilRole(role: string): role is CouncilRole {
  return role === 'Blue' || role === 'Red' || role === 'Judge'
}

function roleQueueIndex(role: CouncilRole): number {
  return pendingRoles.value.indexOf(role)
}

function roleCardStatus(role: CouncilRole): RoleCardStatus {
  const queueIndex = roleQueueIndex(role)
  if (queueIndex === 0) return 'thinking'
  if (queueIndex > 0) return 'waiting'
  const latest = latestRoleEvent.value[role]
  if (latest) return latest.status === 'failed' ? 'failed' : 'completed'
  return 'waiting'
}

function roleCardLabel(role: CouncilRole): string {
  const queueIndex = roleQueueIndex(role)
  if (queueIndex === 0) return '思考中…'
  if (queueIndex > 0) return '排隊中'
  const latest = latestRoleEvent.value[role]
  if (latest) return latest.status === 'failed' ? '失敗' : '已完成'
  return '等待中'
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
        <button
          type="button"
          class="btn btn-ghost btn-icon"
          aria-label="重新整理"
          title="重新整理"
          @click="runAction(refreshAll)"
          :disabled="loading"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" :class="{ 'icon-spin': loading }">
            <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
            <path d="M21 3v5h-5" />
            <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
            <path d="M3 21v-5h5" />
          </svg>
        </button>
      </div>
      <div class="create-box">
        <input v-model="topic" aria-label="會議主題" />
        <button
          type="button"
          class="btn btn-primary"
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
          :data-status="meeting.status"
          @click="openMeeting(meeting.meeting_id)"
        >
          <span class="meeting-item-title">
            <svg v-if="meeting.pinned" class="pin-indicator" viewBox="0 0 24 24" width="12" height="12" fill="currentColor" aria-hidden="true">
              <path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" />
            </svg>
            {{ meeting.topic }}
          </span>
          <em class="status-badge" :data-status="meeting.status">{{ meeting.status }}</em>
          <strong>{{ meeting.activity_status }}</strong>
          <small>更新 {{ formatDateTime(meeting.updated_at) }}</small>
          <small class="meeting-id-text">{{ meeting.meeting_id }}</small>
          <span class="meeting-tags" data-testid="meeting-tags">
            <em v-for="tag in meeting.tags" :key="tag" class="tag-badge">{{ tag }}</em>
          </span>
        </button>
        <button
          type="button"
          class="btn btn-icon pin-meeting-button"
          data-testid="pin-meeting-button"
          :class="{ active: meeting.pinned }"
          :aria-label="`${meeting.pinned ? '取消釘選' : '釘選'} ${meeting.topic}`"
          :disabled="loading"
          @click="toggleMeetingPinned(meeting)"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" :fill="meeting.pinned ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true">
            <path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" />
          </svg>
        </button>
        <button
          type="button"
          class="btn btn-secondary btn-sm edit-tags-button"
          data-testid="edit-tags-button"
          :aria-label="`編輯 ${meeting.topic} 的標籤`"
          :disabled="loading"
          @click="editMeetingTags(meeting)"
        >
          標籤
        </button>
        <button
          type="button"
          class="btn btn-danger btn-sm delete-meeting-button"
          data-testid="delete-meeting-button"
          :aria-label="`刪除 ${meeting.topic}`"
          :disabled="loading || meeting.activity_status === 'running'"
          @click="deleteExistingMeeting(meeting)"
        >
          刪除
        </button>
      </div>
    </aside>

    <aside class="transcript-search-panel" data-testid="transcript-search">
      <input
        v-model="transcriptSearchQuery"
        aria-label="搜尋逐字稿內容"
        placeholder="搜尋逐字稿內容...（含主席發言、角色回應、標籤）"
        data-testid="transcript-search-input"
        @keyup.enter="searchTranscripts"
      />
      <button
        type="button"
        class="btn btn-secondary"
        data-testid="transcript-search-button"
        :disabled="loading || !transcriptSearchQuery.trim()"
        @click="searchTranscripts"
      >
        搜尋
      </button>
      <ul
        v-if="transcriptSearchResults !== null"
        class="transcript-search-results"
        data-testid="transcript-search-results"
      >
        <li v-if="transcriptSearchResults.length === 0">沒有符合的會議</li>
        <li v-for="meeting in transcriptSearchResults" :key="meeting.meeting_id">
          <button type="button" class="btn btn-ghost" @click="openMeeting(meeting.meeting_id)">
            {{ meeting.topic }} <small>{{ meeting.meeting_id }}</small>
          </button>
        </li>
      </ul>
    </aside>

    <section class="workspace">
      <header class="toolbar">
        <label class="model-slot" :class="roleClass('Blue')">
          <span class="role-badge role-blue" data-testid="role-badge">
            <img :src="roleIcon('Blue')" class="role-icon" alt="Blue" />
            Blue
          </span>
          <span class="model-control">
            <select v-model="selectedModels.Blue" data-testid="blue-model-select">
              <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
            </select>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              data-testid="test-blue-model-button"
              @click="testSelectedModel('Blue')"
              :disabled="loading || !selectedModels.Blue"
            >
              Test
            </button>
          </span>
        </label>
        <label class="model-slot" :class="roleClass('Red')">
          <span class="role-badge role-red" data-testid="role-badge">
            <img :src="roleIcon('Red')" class="role-icon" alt="Red" />
            Red
          </span>
          <span class="model-control">
            <select v-model="selectedModels.Red" data-testid="red-model-select">
              <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
            </select>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              data-testid="test-red-model-button"
              @click="testSelectedModel('Red')"
              :disabled="loading || !selectedModels.Red"
            >
              Test
            </button>
          </span>
        </label>
        <label class="model-slot" :class="roleClass('Judge')">
          <span class="role-badge role-judge" data-testid="role-badge">
            <img :src="roleIcon('Judge')" class="role-icon" alt="Judge" />
            Judge
          </span>
          <span class="model-control">
            <select v-model="selectedModels.Judge" data-testid="judge-model-select">
              <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
            </select>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              data-testid="test-judge-model-button"
              @click="testSelectedModel('Judge')"
              :disabled="loading || !selectedModels.Judge"
            >
              Test
            </button>
          </span>
        </label>
        <div class="toolbar-actions">
          <button
            type="button"
            class="btn btn-primary"
            data-testid="start-meeting-button"
            @click="startSelectedMeeting"
            :disabled="loading || !canRun"
          >
            {{ startButtonLabel }}
          </button>
          <button
            type="button"
            class="btn btn-secondary"
            data-testid="cancel-meeting-button"
            @click="cancelSelectedMeeting"
            :disabled="loading || !selectedMeeting || isTerminalMeeting"
          >
            取消
          </button>
          <button
            type="button"
            class="btn btn-secondary"
            data-testid="close-meeting-button"
            @click="closeSelectedMeeting"
            :disabled="loading || !selectedMeeting || isTerminalMeeting"
          >
            結案
          </button>
        </div>
      </header>

      <p v-if="error" class="error" data-testid="app-error">{{ error }}</p>

      <section class="model-test-status" data-testid="model-test-status">
        <span>
          <i class="status-dot" :data-status="modelTestResults.Blue.status" aria-hidden="true"></i>
          Blue: {{ modelTestResults.Blue.status }}
          <small v-if="modelTestResults.Blue.testedAt">測試 {{ formatDateTime(modelTestResults.Blue.testedAt) }}</small>
          <em v-if="modelTestResults.Blue.error">{{ modelTestResults.Blue.error }}</em>
        </span>
        <span>
          <i class="status-dot" :data-status="modelTestResults.Red.status" aria-hidden="true"></i>
          Red: {{ modelTestResults.Red.status }}
          <small v-if="modelTestResults.Red.testedAt">測試 {{ formatDateTime(modelTestResults.Red.testedAt) }}</small>
          <em v-if="modelTestResults.Red.error">{{ modelTestResults.Red.error }}</em>
        </span>
        <span>
          <i class="status-dot" :data-status="modelTestResults.Judge.status" aria-hidden="true"></i>
          Judge: {{ modelTestResults.Judge.status }}
          <small v-if="modelTestResults.Judge.testedAt">測試 {{ formatDateTime(modelTestResults.Judge.testedAt) }}</small>
          <em v-if="modelTestResults.Judge.error">{{ modelTestResults.Judge.error }}</em>
        </span>
      </section>

      <section class="operation-status" data-testid="operation-status">
        <span><i class="status-dot" :data-status="operationStatus" aria-hidden="true"></i>狀態：{{ operationStatus }}</span>
        <span v-if="selectedMeeting?.last_step_id">最後步驟：{{ selectedMeeting.last_step_id }}</span>
        <span v-if="selectedMeeting">更新：{{ formatDateTime(selectedMeeting.updated_at) }}</span>
      </section>

      <section class="role-status-row" data-testid="role-status-row">
        <article
          v-for="role in councilRoles"
          :key="role"
          class="role-status-card"
          :class="roleClass(role)"
          :data-testid="`role-status-card-${role.toLowerCase()}`"
          :data-status="roleCardStatus(role)"
        >
          <header class="role-status-card-header">
            <span class="role-badge" :class="roleClass(role)" data-testid="role-badge">
              <img :src="roleIcon(role)" class="role-icon" :alt="role" />
              {{ role }}
            </span>
            <span class="role-status-pill" :data-status="roleCardStatus(role)">
              <span v-if="roleCardStatus(role) === 'thinking'" class="spinner" aria-hidden="true"></span>
              <svg
                v-else-if="roleCardStatus(role) === 'completed'"
                class="pill-check-icon"
                viewBox="0 0 24 24"
                width="12"
                height="12"
                fill="none"
                stroke="currentColor"
                stroke-width="3"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
              {{ roleCardLabel(role) }}
            </span>
          </header>
          <div class="role-status-card-body">
            <template v-if="roleCardStatus(role) === 'completed'">
              <p class="role-status-summary">{{ latestRoleEvent[role]?.parsed_output?.summary }}</p>
              <p v-if="latestRoleEvent[role]?.parsed_output?.recommendation" class="role-status-recommendation">
                <strong>建議：</strong>{{ latestRoleEvent[role]?.parsed_output?.recommendation }}
              </p>
              <small class="role-status-time">完成於 {{ formatDateTime(latestRoleEvent[role]?.created_at) }}</small>
            </template>
            <template v-else-if="roleCardStatus(role) === 'failed'">
              <p class="role-status-error">{{ latestRoleEvent[role]?.error || '執行失敗，請重試' }}</p>
              <button
                type="button"
                class="btn btn-danger btn-sm"
                data-testid="role-status-retry-button"
                :disabled="loading || !canRun"
                @click="latestRoleEvent[role] && retrySelectedStep(latestRoleEvent[role]!)"
              >
                重試
              </button>
            </template>
            <template v-else-if="roleCardStatus(role) === 'thinking'">
              <p class="role-status-placeholder">正在產生回應…</p>
            </template>
            <template v-else>
              <p class="role-status-placeholder">
                {{ pendingRoles.includes(role) ? '排隊等待發言' : '尚無回應，等待啟動討論' }}
              </p>
            </template>
          </div>
        </article>
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
          class="btn btn-primary"
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
          class="btn btn-secondary"
          data-testid="request-blue-response-button"
          @click="requestSelectedRoleResponse('Blue')"
          :disabled="loading || !canRun"
        >
          請 Blue 回應
        </button>
        <button
          type="button"
          class="btn btn-secondary"
          data-testid="request-red-response-button"
          @click="requestSelectedRoleResponse('Red')"
          :disabled="loading || !canRun"
        >
          請 Red 回應
        </button>
        <button
          type="button"
          class="btn btn-secondary"
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
          class="btn btn-secondary"
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
            <template v-if="selectedMeeting">
              <span class="meeting-id-pill" data-testid="meeting-id-display">{{ selectedMeeting.meeting_id }}</span>
              <button
                type="button"
                class="btn btn-secondary btn-sm copy-meeting-id-button"
                data-testid="copy-meeting-id-button"
                :aria-label="meetingIdCopied ? '已複製會議 ID' : '複製會議 ID'"
                @click="copyMeetingId(selectedMeeting.meeting_id)"
              >
                <svg v-if="!meetingIdCopied" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <rect x="9" y="9" width="11" height="11" rx="2" />
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
                <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M20 6 9 17l-5-5" />
                </svg>
                {{ meetingIdCopied ? '已複製' : '複製' }}
              </button>
            </template>
            <em v-if="selectedMeeting" class="status-badge" :data-status="selectedMeeting.status">{{ selectedMeeting.status }}</em>
            <em v-if="selectedMeeting" class="status-badge" :data-status="selectedMeeting.activity_status">{{ selectedMeeting.activity_status }}</em>
          </div>
          <div v-if="!selectedMeeting" class="empty-state">
            <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
            </svg>
            <p>從左側清單選擇或建立一場新會議</p>
          </div>
          <div
            v-for="event in events"
            :key="event.event_id"
            class="timeline-row"
            :class="roleClass(event.role)"
          >
            <button type="button" class="timeline-main" @click="selectedEvent = event">
              <span class="role-badge" :class="roleClass(event.role)" data-testid="role-badge">
                <img v-if="roleIcon(event.role)" :src="roleIcon(event.role)" class="role-icon" :alt="event.role" />
                {{ event.role }}
              </span>
              <strong>{{ event.step_id }}</strong>
              <em class="status-badge" :data-status="event.status">{{ event.status }}</em>
              <small>{{ formatDateTime(event.created_at) }}</small>
            </button>
            <button
              v-if="event.status === 'failed'"
              type="button"
              class="btn btn-danger btn-sm retry-button"
              data-testid="retry-step-button"
              @click="retrySelectedStep(event)"
              :disabled="loading || !canRun"
            >
              Retry
            </button>
            <button
              v-if="event.role === 'Human' && event.step_id === 'human-message' && !event.corrects_event_id"
              type="button"
              class="btn btn-secondary btn-sm edit-message-button"
              data-testid="edit-message-button"
              @click="correctSelectedMessage(event)"
              :disabled="loading || isTerminalMeeting"
            >
              編輯
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
            :class="roleClass(event.role)"
          >
            <header>
              <strong class="role-badge" :class="roleClass(event.role)" data-testid="role-badge">
                <img v-if="roleIcon(event.role)" :src="roleIcon(event.role)" class="role-icon" :alt="event.role" />
                {{ event.role }}
              </strong>
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
        <div v-else class="empty-state">
          <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M9 12h6M9 16h6M9 8h6M5 3h10l4 4v14H5z" />
          </svg>
          <p>No role output yet</p>
        </div>
      </section>

      <section class="transcript" data-testid="transcript-preview">
        <div class="transcript-header">
          <h2>Transcript</h2>
          <a
            v-if="selectedMeeting"
            class="btn btn-secondary btn-sm"
            :href="transcriptDownloadUrl(selectedMeeting.meeting_id)"
            target="_blank"
            rel="noreferrer"
          >
            下載 Markdown
          </a>
        </div>
        <div v-if="!transcript" class="empty-state">
          <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M6 3h9l5 5v13H6zM15 3v5h5M9 13h6M9 17h6" />
          </svg>
          <p>No transcript yet</p>
        </div>
        <pre v-else>{{ transcript }}</pre>
      </section>
    </section>
  </main>
</template>
