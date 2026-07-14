<script setup lang="ts">
import { inject } from 'vue'
import { councilKey } from '../composables/useCouncil'
import { formatDateTime } from '../composables/useCouncil'
import Modal from './Modal.vue'

defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const store = inject(councilKey)!
const {
  filteredMeetings,
  selectedMeeting,
  meetingSearch,
  statusFilter,
  loading,
  transcriptSearchQuery,
  transcriptSearchResults,
  openMeeting,
  toggleMeetingPinned,
  editMeetingTags,
  deleteExistingMeeting,
  searchTranscripts,
} = store

async function selectMeeting(meetingId: string) {
  await openMeeting(meetingId)
  emit('close')
}
</script>

<template>
  <Modal :show="show" title="Past Topics" test-id="meetings-modal" close-test-id="meetings-close-button" @close="$emit('close')">
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

    <div class="meeting-list" data-testid="meeting-list">
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
          @click="selectMeeting(meeting.meeting_id)"
        >
          <span class="meeting-item-title">
            <svg v-if="meeting.pinned" class="pin-indicator" viewBox="0 0 24 24" width="12" height="12" fill="currentColor" aria-hidden="true">
              <path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" />
            </svg>
            {{ meeting.title }}
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
          :aria-label="`${meeting.pinned ? '取消釘選' : '釘選'} ${meeting.title}`"
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
          :aria-label="`編輯 ${meeting.title} 的標籤`"
          :disabled="loading"
          @click="editMeetingTags(meeting)"
        >
          標籤
        </button>
        <button
          type="button"
          class="btn btn-danger btn-sm delete-meeting-button"
          data-testid="delete-meeting-button"
          :aria-label="`刪除 ${meeting.title}`"
          :disabled="loading || meeting.activity_status === 'running'"
          @click="deleteExistingMeeting(meeting)"
        >
          刪除
        </button>
      </div>
    </div>

    <div class="transcript-search-panel" data-testid="transcript-search">
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
          <button type="button" class="btn btn-ghost" @click="selectMeeting(meeting.meeting_id)">
            {{ meeting.title }} <small>{{ meeting.meeting_id }}</small>
          </button>
        </li>
      </ul>
    </div>
  </Modal>
</template>
