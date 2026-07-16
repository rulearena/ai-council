<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { activeMode, councilKey, formatDateTime, roleClass, roleColor, roleColorVars, roleIcon } from '../composables/useCouncil'
import Drawer from './Drawer.vue'
import RoleSilhouette from './RoleSilhouette.vue'
import { getDeliberations, getTranscript, promoteMessageToCaseNote, transcriptDownloadUrl } from '../api'
import type { Deliberations, MeetingEvent } from '../api'
import { nextHistorySelection } from '../meetingWorkspace'
import { eventRoleDisplayName, roleDisplayName, statusDisplayLabel, stepDisplayLabel } from '../presentation'

const props = defineProps<{ show: boolean }>()
defineEmits<{ close: [] }>()

const store = inject(councilKey)!
const {
  selectedMeeting,
  events,
  selectedEvent,
  transcript,
  devMode,
  loading,
  canRun,
  isTerminalMeeting,
  retrySelectedStep,
  correctSelectedMessage,
  openMeeting,
  runAction,
} = store

type RecordsTab = 'timeline' | 'transcript' | 'debug'
const activeTab = ref<RecordsTab>('timeline')
const copiedDiagnosticEventId = ref<string | null>(null)
const copyDiagnosticErrorEventId = ref<string | null>(null)
const deliberations = ref<Deliberations | null>(null)
const selectedEpochId = ref('')
const historyTranscript = ref('')
let historyMeetingId: string | null = null
let historyGeneration = 0
const promotionEvent = ref<MeetingEvent | null>(null)
const promotionTitle = ref('')
const promotionVisibleRoles = ref<string[]>([])
const browsingCurrent = computed(() => selectedEpochId.value === deliberations.value?.active_epoch_id)
const shownTranscript = computed(() => browsingCurrent.value ? transcript.value : historyTranscript.value)
const participants = computed(() => selectedMeeting.value?.participants ?? [])
const displayRole = (event: MeetingEvent) => eventRoleDisplayName(activeMode.value, participants.value, event)
const displayStep = (event: MeetingEvent) => stepDisplayLabel(activeMode.value, participants.value, event)
const displayParticipantRole = (role: string) => roleDisplayName(activeMode.value, participants.value, role)

const diagnosticKeys = [
  'event_id',
  'meeting_id',
  'step_id',
  'base_step_id',
  'round',
  'role',
  'attempt',
  'status',
  'failure_kind',
  'model_config_id',
  'adapter',
  'prompt_messages',
  'raw_output',
  'parsed_output',
  'token_usage',
  'started_at',
  'completed_at',
  'duration_ms',
  'retry_scheduled',
  'result_discarded',
  'error',
  'adapter_stdout_excerpt',
  'adapter_stderr_excerpt',
] as const

function hasAttemptDiagnostics(event: MeetingEvent) {
  return Boolean(event.failure_kind || event.adapter || event.started_at)
}

function diagnosticBundle(event: MeetingEvent) {
  return Object.fromEntries(
    diagnosticKeys.flatMap((key) => (event[key] === undefined ? [] : [[key, event[key]]])),
  )
}

async function copyAttemptDiagnostics(event: MeetingEvent) {
  copiedDiagnosticEventId.value = null
  copyDiagnosticErrorEventId.value = null
  try {
    await navigator.clipboard.writeText(JSON.stringify(diagnosticBundle(event), null, 2))
    copiedDiagnosticEventId.value = event.event_id
  } catch {
    copyDiagnosticErrorEventId.value = event.event_id
  }
}

function copyDiagnosticLabel(event: MeetingEvent) {
  if (copiedDiagnosticEventId.value === event.event_id) return '已複製'
  if (copyDiagnosticErrorEventId.value === event.event_id) return '複製失敗'
  return '複製診斷 JSON'
}

function copyDiagnosticStatus(event: MeetingEvent) {
  if (copiedDiagnosticEventId.value === event.event_id) return '已複製'
  if (copyDiagnosticErrorEventId.value === event.event_id) return '複製失敗'
  return ''
}

watch([() => props.show, () => selectedMeeting.value?.meeting_id], async ([show, meetingId]) => {
  const generation = ++historyGeneration
  deliberations.value = null
  historyTranscript.value = ''
  promotionEvent.value = null
  if (!show || !meetingId) return
  const previousMeetingId = historyMeetingId
  const response = await getDeliberations(meetingId)
  if (generation !== historyGeneration || selectedMeeting.value?.meeting_id !== meetingId || !props.show) return
  deliberations.value = response
  selectedEpochId.value = nextHistorySelection(
    previousMeetingId,
    meetingId,
    selectedEpochId.value,
    deliberations.value.active_epoch_id,
  )
  historyMeetingId = meetingId
}, { immediate: true })

watch(selectedEpochId, async (epochId) => {
  const meetingId = selectedMeeting.value?.meeting_id
  const generation = ++historyGeneration
  if (!meetingId || !epochId || epochId === deliberations.value?.active_epoch_id) {
    historyTranscript.value = ''
    return
  }
  const response = await getTranscript(meetingId, epochId)
  if (generation !== historyGeneration || selectedMeeting.value?.meeting_id !== meetingId || selectedEpochId.value !== epochId || !props.show) return
  historyTranscript.value = response
  activeTab.value = 'transcript'
})

function beginPromotion(event: MeetingEvent) {
  promotionEvent.value = event
  promotionTitle.value = event.content?.slice(0, 24) || '主席備註'
  promotionVisibleRoles.value = participants.value.map((participant) => participant.role_id)
}

async function promoteToCaseNote() {
  const meeting = selectedMeeting.value
  const event = promotionEvent.value
  if (!meeting || !event || !promotionTitle.value.trim() || !promotionVisibleRoles.value.length) return
  const meetingId = meeting.meeting_id
  const generation = ++historyGeneration
  await runAction(async () => {
    await promoteMessageToCaseNote(
      meetingId,
      event.event_id,
      meeting.case_materials?.revision ?? 0,
      promotionTitle.value.trim(),
      [...promotionVisibleRoles.value],
    )
    if (generation !== historyGeneration || selectedMeeting.value?.meeting_id !== meetingId) return
    await openMeeting(meetingId)
    if (generation === historyGeneration && selectedMeeting.value?.meeting_id === meetingId) promotionEvent.value = null
  })
}
</script>

<template>
  <Drawer :show="show" title="議事紀錄" test-id="records-drawer" close-test-id="records-close-button" @close="$emit('close')">
    <label v-if="deliberations && deliberations.epochs.length" class="epoch-picker">審議輪次
      <select v-model="selectedEpochId" data-testid="records-epoch-select">
        <option v-for="epoch in deliberations.epochs" :key="epoch.id" :value="epoch.id">第 {{ epoch.number }} 輪{{ epoch.id === deliberations.active_epoch_id ? '（目前）' : '（已封存）' }} · {{ epoch.event_count }} 筆</option>
      </select>
    </label>
    <p v-if="!browsingCurrent" class="archive-notice">正在查看封存輪次。這裡只能閱讀或下載，不會替換目前會議，也不能編輯或重試。</p>
    <form v-if="promotionEvent" class="material-form" data-testid="promote-case-note-form" @submit.prevent="promoteToCaseNote">
      <h3>轉為案件備註</h3>
      <label>備註標題<input v-model="promotionTitle" data-testid="promote-case-note-title" :disabled="loading" /></label>
      <fieldset><legend>可見角色</legend><label v-for="participant in participants" :key="participant.role_id"><input v-model="promotionVisibleRoles" type="checkbox" :value="participant.role_id" :disabled="loading" />{{ displayParticipantRole(participant.role_id) }}</label></fieldset>
      <div><button type="submit" class="btn btn-primary" data-testid="confirm-promote-case-note" :disabled="loading || !promotionTitle.trim() || !promotionVisibleRoles.length">建立備註</button><button type="button" class="btn btn-secondary" :disabled="loading" @click="promotionEvent = null">取消</button></div>
    </form>
    <div class="records-tabs">
      <button
        type="button"
        class="btn btn-ghost btn-sm records-tab"
        :class="{ active: activeTab === 'timeline' }"
        data-testid="records-tab-timeline"
        @click="activeTab = 'timeline'"
      >
        時間軸
      </button>
      <button
        type="button"
        class="btn btn-ghost btn-sm records-tab"
        :class="{ active: activeTab === 'transcript' }"
        data-testid="records-tab-transcript"
        @click="activeTab = 'transcript'"
      >
        逐字稿
      </button>
      <button
        v-if="devMode"
        type="button"
        class="btn btn-ghost btn-sm records-tab"
        :class="{ active: activeTab === 'debug' }"
        data-testid="records-tab-debug"
        @click="activeTab = 'debug'"
      >
        開發診斷
      </button>
    </div>

    <section v-if="activeTab === 'timeline' && browsingCurrent" class="timeline" data-testid="step-timeline">
      <div class="section-title">
        <h2>{{ selectedMeeting?.title ?? '尚未選擇會議' }}</h2>
        <em v-if="selectedMeeting" class="status-badge" :data-status="selectedMeeting.status">{{ statusDisplayLabel(selectedMeeting.status) }}</em>
        <em v-if="selectedMeeting" class="status-badge" :data-status="selectedMeeting.activity_status">{{ statusDisplayLabel(selectedMeeting.activity_status) }}</em>
      </div>
      <div v-if="!selectedMeeting" class="empty-state">
        <p>請從右上角「歷史會議」選擇，或建立一場新會議</p>
      </div>
      <div
        v-for="event in events"
        :key="event.event_id"
        class="timeline-row"
        :class="roleClass(event.role)"
        :style="roleColorVars(event.role)"
      >
        <button type="button" class="timeline-main" @click="selectedEvent = event">
          <span class="role-badge" :class="roleClass(event.role)" :style="roleColorVars(event.role)" data-testid="role-badge">
            <img v-if="roleIcon(event.role)" :src="roleIcon(event.role)" class="role-icon" :alt="displayRole(event)" />
            <RoleSilhouette v-else-if="roleClass(event.role)" :color="roleColor(event.role)" :size="16" />
            {{ displayRole(event) }}
          </span>
          <strong>{{ displayStep(event) }}</strong>
          <em class="status-badge" :data-status="event.status">{{ statusDisplayLabel(event.status) }}</em>
          <small>{{ formatDateTime(event.created_at) }}</small>
          <p v-if="event.role === 'Human' && event.content" class="timeline-content">{{ event.content }}</p>
        </button>
        <button
          v-if="event.status === 'failed'"
          type="button"
          class="btn btn-danger btn-sm retry-button"
          data-testid="retry-step-button"
          @click="retrySelectedStep(event)"
          :disabled="loading || !canRun"
        >
          重試
        </button>
        <button
          v-if="event.role === 'Human' && event.step_id === 'human-message' && !event.corrects_event_id"
          type="button"
          class="btn btn-secondary btn-sm"
          data-testid="promote-case-note-button"
          :disabled="loading || isTerminalMeeting"
          @click="beginPromotion(event)"
        >轉為案件備註</button>
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
        <details
          v-if="hasAttemptDiagnostics(event)"
          class="attempt-diagnostics"
          data-testid="meeting-attempt-diagnostics"
        >
          <summary>LLM attempt 診斷</summary>
          <dl class="attempt-diagnostics-fields">
            <div><dt>內部步驟代碼</dt><dd>{{ event.step_id }}</dd></div>
            <div><dt>分類</dt><dd>{{ event.failure_kind ?? 'completed' }}</dd></div>
            <div><dt>模型</dt><dd>{{ event.model_config_id ?? '—' }}</dd></div>
            <div><dt>Adapter</dt><dd>{{ event.adapter ?? '—' }}</dd></div>
            <div><dt>Attempt</dt><dd>{{ event.attempt }}</dd></div>
            <div><dt>開始</dt><dd>{{ event.started_at ?? '—' }}</dd></div>
            <div><dt>完成</dt><dd>{{ event.completed_at ?? '—' }}</dd></div>
            <div><dt>耗時</dt><dd>{{ event.duration_ms == null ? '—' : `${event.duration_ms} ms` }}</dd></div>
            <div><dt>自動重試</dt><dd>{{ event.retry_scheduled == null ? '—' : event.retry_scheduled ? '是' : '否' }}</dd></div>
          </dl>
          <div v-if="event.error" class="attempt-diagnostics-block">
            <strong>Error</strong>
            <pre>{{ event.error }}</pre>
          </div>
          <div v-if="event.raw_output" class="attempt-diagnostics-block">
            <strong>Raw output</strong>
            <pre>{{ event.raw_output }}</pre>
          </div>
          <div v-if="event.adapter_stdout_excerpt" class="attempt-diagnostics-block">
            <strong>Adapter stdout（尾端）</strong>
            <pre>{{ event.adapter_stdout_excerpt }}</pre>
          </div>
          <div v-if="event.adapter_stderr_excerpt" class="attempt-diagnostics-block">
            <strong>Adapter stderr（尾端）</strong>
            <pre>{{ event.adapter_stderr_excerpt }}</pre>
          </div>
          <div v-if="event.prompt_messages" class="attempt-diagnostics-block">
            <strong>Prompt messages</strong>
            <pre>{{ JSON.stringify(event.prompt_messages, null, 2) }}</pre>
          </div>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            data-testid="copy-attempt-diagnostics"
            @click="copyAttemptDiagnostics(event)"
          >
            {{ copyDiagnosticLabel(event) }}
          </button>
          <span
            class="visually-hidden"
            role="status"
            aria-live="polite"
            aria-atomic="true"
            data-testid="copy-attempt-diagnostics-status"
          >{{ copyDiagnosticStatus(event) }}</span>
        </details>
      </div>
    </section>

    <section v-else-if="activeTab === 'transcript'" class="transcript" data-testid="transcript-preview">
      <div class="transcript-header">
        <h2>逐字稿</h2>
        <a
          v-if="selectedMeeting"
          class="btn btn-secondary btn-sm"
          :href="transcriptDownloadUrl(selectedMeeting.meeting_id, selectedEpochId || 'current')"
          target="_blank"
          rel="noreferrer"
        >
          下載 Markdown
        </a>
        <a
          v-if="selectedMeeting"
          class="btn btn-secondary btn-sm"
          data-testid="download-all-epochs"
          :href="transcriptDownloadUrl(selectedMeeting.meeting_id, 'all')"
          target="_blank"
          rel="noreferrer"
        >下載全部輪次</a>
      </div>
      <div v-if="!shownTranscript" class="empty-state">
        <p>尚無逐字稿</p>
      </div>
      <pre v-else>{{ shownTranscript }}</pre>
    </section>

    <section v-else-if="activeTab === 'debug'" class="debug" data-testid="debug-panel">
      <h2>開發診斷</h2>
      <pre>{{ selectedEvent ? JSON.stringify(selectedEvent, null, 2) : '尚未選擇事件' }}</pre>
    </section>
  </Drawer>
</template>
