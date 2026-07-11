<script setup lang="ts">
import { inject, ref } from 'vue'
import { councilKey, formatDateTime, roleClass, roleIcon } from '../composables/useCouncil'
import Drawer from './Drawer.vue'
import { transcriptDownloadUrl } from '../api'

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
