<script setup lang="ts">
import { inject } from 'vue'
import { councilKey } from '../composables/useCouncil'

const store = inject(councilKey)!
const { selectedMeeting, meetingIdCopied, copyMeetingId } = store

defineEmits<{
  'open-settings': []
  'open-past-topics': []
  'open-new-case': []
  'open-records': []
}>()
</script>

<template>
  <header class="top-bar">
    <div class="top-bar-left">
      <h1>AI 眾議院</h1>
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
    </div>
    <div class="top-bar-right">
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        data-testid="records-button"
        :disabled="!selectedMeeting"
        @click="$emit('open-records')"
      >
        議事紀錄
      </button>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        data-testid="settings-button"
        @click="$emit('open-settings')"
      >
        Settings
      </button>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        data-testid="past-topics-button"
        @click="$emit('open-past-topics')"
      >
        Past Topics
      </button>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        data-testid="new-case-button"
        @click="$emit('open-new-case')"
      >
        New Case
      </button>
    </div>
  </header>
</template>
