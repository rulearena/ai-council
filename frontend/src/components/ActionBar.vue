<script setup lang="ts">
import { inject, ref } from 'vue'
import { councilKey, formatDateTime, sequencePresets } from '../composables/useCouncil'

const store = inject(councilKey)!
const {
  chairMessage,
  selectedMeeting,
  isTerminalMeeting,
  loading,
  canRun,
  startButtonLabel,
  selectedSequencePresetId,
  error,
  operationStatus,
  showContinueHint,
  sendChairMessage,
  startOrContinueMeeting,
  cancelSelectedMeeting,
  closeSelectedMeeting,
  requestSelectedRoleSequence,
} = store

const advancedOpen = ref(false)

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') advancedOpen.value = false
}
</script>

<template>
  <footer class="action-bar" @keydown="onKeydown">
    <p v-if="error" class="error" data-testid="app-error">{{ error }}</p>

    <div class="action-bar-status" data-testid="operation-status">
      <span><i class="status-dot" :data-status="operationStatus" aria-hidden="true"></i>狀態：{{ operationStatus }}</span>
      <span v-if="selectedMeeting?.last_step_id">最後步驟：{{ selectedMeeting.last_step_id }}</span>
      <span v-if="selectedMeeting">更新：{{ formatDateTime(selectedMeeting.updated_at) }}</span>
    </div>

    <div class="action-bar-row">
      <textarea
        v-model="chairMessage"
        data-testid="chair-message-input"
        aria-label="主席發言"
        placeholder="向議會提問或補充限制…"
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
      <span v-if="showContinueHint" class="continue-hint" data-testid="continue-hint">請議會回應 →</span>
      <button
        type="button"
        class="btn btn-primary action-bar-cta"
        :class="{ 'action-bar-cta-hint': showContinueHint }"
        data-testid="start-meeting-button"
        @click="startOrContinueMeeting"
        :disabled="loading || !canRun"
      >
        {{ startButtonLabel }}
      </button>
      <div class="advanced-options">
        <button
          type="button"
          class="btn btn-ghost btn-icon"
          aria-label="進階選項"
          data-testid="advanced-options-button"
          @click="advancedOpen = !advancedOpen"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
        <div v-if="advancedOpen" class="advanced-options-panel" data-testid="advanced-options-panel">
          <section class="sequence-panel" data-testid="role-sequence-controls">
            <label>
              自動接續
              <select v-model="selectedSequencePresetId" data-testid="sequence-preset-select">
                <option v-for="preset in sequencePresets" :key="preset.id" :value="preset.id">
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
          <div class="advanced-options-actions">
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
        </div>
      </div>
    </div>
  </footer>
</template>
