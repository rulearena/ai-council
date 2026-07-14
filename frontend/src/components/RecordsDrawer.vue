<script setup lang="ts">
import { inject, ref } from 'vue'
import { councilKey, formatDateTime, roleClass, roleColor, roleColorVars, roleIcon } from '../composables/useCouncil'
import Drawer from './Drawer.vue'
import RoleSilhouette from './RoleSilhouette.vue'
import { transcriptDownloadUrl } from '../api'
import type { MeetingEvent } from '../api'

defineProps<{ show: boolean }>()
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
} = store

type RecordsTab = 'timeline' | 'transcript' | 'debug'
const activeTab = ref<RecordsTab>('timeline')
const copiedDiagnosticEventId = ref<string | null>(null)
const copyDiagnosticErrorEventId = ref<string | null>(null)

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
</script>

<template>
  <Drawer :show="show" title="議事紀錄" test-id="records-drawer" close-test-id="records-close-button" @close="$emit('close')">
    <div class="records-tabs">
      <button
        type="button"
        class="btn btn-ghost btn-sm records-tab"
        :class="{ active: activeTab === 'timeline' }"
        data-testid="records-tab-timeline"
        @click="activeTab = 'timeline'"
      >
        Timeline
      </button>
      <button
        type="button"
        class="btn btn-ghost btn-sm records-tab"
        :class="{ active: activeTab === 'transcript' }"
        data-testid="records-tab-transcript"
        @click="activeTab = 'transcript'"
      >
        Transcript
      </button>
      <button
        v-if="devMode"
        type="button"
        class="btn btn-ghost btn-sm records-tab"
        :class="{ active: activeTab === 'debug' }"
        data-testid="records-tab-debug"
        @click="activeTab = 'debug'"
      >
        Debug
      </button>
    </div>

    <section v-if="activeTab === 'timeline'" class="timeline" data-testid="step-timeline">
      <div class="section-title">
        <h2>{{ selectedMeeting?.topic ?? '尚未選擇會議' }}</h2>
        <em v-if="selectedMeeting" class="status-badge" :data-status="selectedMeeting.status">{{ selectedMeeting.status }}</em>
        <em v-if="selectedMeeting" class="status-badge" :data-status="selectedMeeting.activity_status">{{ selectedMeeting.activity_status }}</em>
      </div>
      <div v-if="!selectedMeeting" class="empty-state">
        <p>從左上角 Past Topics 選擇或建立一場新會議</p>
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
            <img v-if="roleIcon(event.role)" :src="roleIcon(event.role)" class="role-icon" :alt="event.role" />
            <RoleSilhouette v-else-if="roleClass(event.role)" :color="roleColor(event.role)" :size="16" />
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
        <details
          v-if="hasAttemptDiagnostics(event)"
          class="attempt-diagnostics"
          data-testid="meeting-attempt-diagnostics"
        >
          <summary>LLM attempt 診斷</summary>
          <dl class="attempt-diagnostics-fields">
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
        <p>No transcript yet</p>
      </div>
      <pre v-else>{{ transcript }}</pre>
    </section>

    <section v-else-if="activeTab === 'debug'" class="debug" data-testid="debug-panel">
      <h2>Debug</h2>
      <pre>{{ selectedEvent ? JSON.stringify(selectedEvent, null, 2) : 'No event selected' }}</pre>
    </section>
  </Drawer>
</template>
