<script setup lang="ts">
import { computed, inject } from 'vue'
import { councilKey } from '../composables/useCouncil'

const { selectedMeeting, meetingInfoCopied, copyMeetingInfo } = inject(councilKey)!

defineEmits<{
  'open-settings': []
  'open-meeting-settings': []
  'open-past-topics': []
  'open-new-case': []
  'open-mode-help': []
}>()
</script>

<template>
  <header class="top-bar">
    <div class="top-bar-left">
      <h1>AI 眾議院</h1>
      <template v-if="selectedMeeting">
        <span class="meeting-title-pill" data-testid="meeting-title-display">{{ selectedMeeting.title }}</span>
        <button type="button" class="btn btn-ghost btn-sm btn-icon meeting-edit-title-button" data-testid="meeting-settings-button" aria-label="會議設定" @click="$emit('open-meeting-settings')">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
            <path d="m15 5 4 4" />
          </svg>
        </button>
        <button type="button" class="btn btn-secondary btn-sm copy-meeting-info-button" data-testid="copy-meeting-id-button" :aria-label="meetingInfoCopied ? '已複製會議資訊' : '複製會議資訊（包含會議 ID）'" @click="copyMeetingInfo(selectedMeeting)">
          {{ meetingInfoCopied ? '已複製' : '複製名稱與 ID' }}
        </button>
      </template>
    </div>
    <div class="top-bar-right">
      <button type="button" class="btn btn-ghost btn-sm btn-icon mode-help-button" data-testid="mode-help-button" aria-label="會議模式說明" @click="$emit('open-mode-help')">?</button>
      <button type="button" class="btn btn-secondary btn-sm" data-testid="settings-button" @click="$emit('open-settings')">系統設定</button>
      <button type="button" class="btn btn-secondary btn-sm" data-testid="past-topics-button" @click="$emit('open-past-topics')">歷史會議</button>
      <button type="button" class="btn btn-primary btn-sm" data-testid="new-case-button" @click="$emit('open-new-case')">新增會議</button>
    </div>
  </header>
</template>
