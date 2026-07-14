<script setup lang="ts">
import { inject } from 'vue'
import { councilKey } from '../composables/useCouncil'

const store = inject(councilKey)!
const { selectedMeeting, meetingInfoCopied, copyMeetingInfo } = store

defineEmits<{
  'open-settings': []
  'open-past-topics': []
  'open-new-case': []
  'open-records': []
  'open-mode-help': []
}>()
</script>

<template>
  <header class="top-bar">
    <div class="top-bar-left">
      <h1>AI 眾議院</h1>
      <template v-if="selectedMeeting">
        <span class="meeting-title-pill" data-testid="meeting-title-display">{{ selectedMeeting.title }}</span>
        <button
          type="button"
          class="btn btn-secondary btn-sm copy-meeting-info-button"
          data-testid="copy-meeting-id-button"
          :aria-label="meetingInfoCopied ? '已複製會議資訊' : '複製會議資訊（包含會議 ID）'"
          @click="copyMeetingInfo(selectedMeeting)"
        >
          <svg v-if="!meetingInfoCopied" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="9" y="9" width="11" height="11" rx="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
          <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M20 6 9 17l-5-5" />
          </svg>
          {{ meetingInfoCopied ? '已複製' : '複製' }}
        </button>
      </template>
    </div>
    <div class="top-bar-right">
      <button
        type="button"
        class="btn btn-ghost btn-sm btn-icon mode-help-button"
        data-testid="mode-help-button"
        aria-label="會議模式說明"
        @click="$emit('open-mode-help')"
      >
        ?
      </button>
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
        設定
      </button>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        data-testid="past-topics-button"
        @click="$emit('open-past-topics')"
      >
        歷史會議
      </button>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        data-testid="new-case-button"
        @click="$emit('open-new-case')"
      >
        新增會議
      </button>
    </div>
  </header>
</template>
