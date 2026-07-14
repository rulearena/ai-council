<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { councilKey } from '../composables/useCouncil'
import { meetingEditPolicy } from '../chairmanActions'

const store = inject(councilKey)!
const {
  selectedMeeting,
  meetingInfoCopied,
  copyMeetingInfo,
  updateSelectedMeetingDetails,
  isMeetingRunning,
  events,
  loading,
} = store
const editingDetails = ref(false)
const editTitle = ref('')
const editGoal = ref('')
const editPolicy = computed(() => meetingEditPolicy({
  modeId: selectedMeeting.value?.mode_id ?? '',
  activityStatus: selectedMeeting.value?.activity_status ?? 'idle',
  courtroomStatus: selectedMeeting.value?.courtroom?.status ?? null,
  hasAiOutput: events.value.some((event) => !['Human', 'System'].includes(event.role) && event.status === 'completed'),
}))

watch(() => selectedMeeting.value?.meeting_id, () => {
  editingDetails.value = false
})

function openDetailsEditor() {
  if (!selectedMeeting.value || !editPolicy.value.canEdit) return
  editTitle.value = selectedMeeting.value.title
  editGoal.value = selectedMeeting.value.goal ?? ''
  editingDetails.value = true
}

async function saveDetails() {
  if (await updateSelectedMeetingDetails(editTitle.value, editGoal.value)) {
    editingDetails.value = false
  }
}

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
        <button
          type="button"
          class="btn btn-secondary btn-sm"
          data-testid="edit-meeting-details-button"
          :disabled="!editPolicy.canEdit"
          :title="isMeetingRunning ? '會議執行中無法修改資訊' : '編輯會議名稱與目標'"
          @click="openDetailsEditor"
        >
          編輯會議資訊
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
        系統設定
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
    <section v-if="editingDetails" class="meeting-details-editor" data-testid="meeting-details-editor">
      <label>
        會議名稱
        <input v-model="editTitle" data-testid="meeting-title-input" :disabled="loading || !editPolicy.canEdit" />
      </label>
      <label>
        AI 最終目標
        <textarea
          v-model="editGoal"
          data-testid="meeting-goal-input"
          :readonly="editPolicy.goalReadonly"
          :disabled="loading || !editPolicy.canEdit"
        />
        <small v-if="editPolicy.goalReadonly">爭點已確認，為保持裁定基準一致，目標已設為唯讀。</small>
        <small v-else-if="editPolicy.confirmGoalChange">修改目標只影響後續 AI 回應，儲存前會再次確認。</small>
      </label>
      <div class="meeting-details-editor-actions">
        <button type="button" class="btn btn-primary btn-sm" data-testid="save-meeting-details-button" :disabled="loading || !editPolicy.canEdit || !editTitle.trim() || !editGoal.trim()" @click="saveDetails">
          儲存會議資訊
        </button>
        <button type="button" class="btn btn-secondary btn-sm" :disabled="loading" @click="editingDetails = false">取消</button>
      </div>
    </section>
  </header>
</template>
