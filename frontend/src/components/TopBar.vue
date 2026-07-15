<script setup lang="ts">
import { computed, inject } from 'vue'
import { councilKey } from '../composables/useCouncil'

const { selectedMeeting, meetingInfoCopied, copyMeetingInfo } = inject(councilKey)!
const materialCount = computed(() => selectedMeeting.value?.case_materials?.evidence.filter((item) => item.status === 'active').length
  ?? selectedMeeting.value?.case_files?.length
  ?? 0)

defineEmits<{
  'open-settings': []
  'open-meeting-settings': []
  'open-materials': []
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
    <nav v-if="selectedMeeting" class="meeting-subnav" aria-label="會議工作區">
      <button type="button" class="btn btn-ghost btn-sm" data-testid="meeting-settings-button" @click="$emit('open-meeting-settings')">會議設定</button>
      <button type="button" class="btn btn-ghost btn-sm" data-testid="case-materials-button" @click="$emit('open-materials')">案卷與證據（{{ materialCount }}）</button>
      <button type="button" class="btn btn-ghost btn-sm" data-testid="records-button" @click="$emit('open-records')">議事紀錄</button>
    </nav>
  </header>
</template>
