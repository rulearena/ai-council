<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { activeMode, councilKey, formatDateTime, sequencePresets } from '../composables/useCouncil'
import { nextMeetingMigrationDraft } from '../meetingMigration'
import { roleDisplayName, stepDisplayLabel } from '../presentation'

const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
defineEmits<{ 'open-materials': [] }>()

const store = inject(councilKey)!
const {
  chairMessage,
  chairmanAction,
  chairmanActionFeedback,
  chairmanOptions,
  chairmanPresentation,
  primaryAction,
  selectedMeeting,
  isTerminalMeeting,
  isMeetingRunning,
  loading,
  canRun,
  startButtonLabel,
  selectedSequencePresetId,
  error,
  operationStatus,
  operationStatusText,
  failedRole,
  currentStepProgress,
  submitChairmanAction,
  startOrContinueMeeting,
  cancelSelectedMeeting,
  closeSelectedMeeting,
  reopenSelectedMeeting,
  restartSelectedDeliberation,
  requestSelectedRoleSequence,
  updateSelectedMeetingDetails,
} = store

const advancedOpen = ref(false)
const migrationTitle = ref('')
const migrationGoal = ref('')
const restartReason = ref('')
const restartScope = ref<'current_issue' | 'all_deliberation' | 'rebuild_issues'>('all_deliberation')
const restartIssueId = ref('')
const restarting = ref(false)

const restartableIssues = computed(() => {
  const courtroom = selectedMeeting.value?.courtroom
  if (!courtroom) return []
  return courtroom.issues.filter((issue) =>
    issue.id === courtroom.current_issue_id || issue.status === 'ruled',
  )
})

async function restartDiscussion() {
  if (!restartReason.value.trim()) return
  restarting.value = true
  const accepted = await restartSelectedDeliberation(
    restartScope.value,
    restartReason.value,
    restartScope.value === 'current_issue' ? restartIssueId.value : undefined,
  )
  if (accepted) {
    restartReason.value = ''
    advancedOpen.value = false
  }
  restarting.value = false
}

watch(
  [
    () => selectedMeeting.value?.meeting_id,
    () => selectedMeeting.value?.requires_goal,
  ],
  ([meetingId, requiresGoal], [previousMeetingId, previousRequiresGoal]) => {
    const meeting = selectedMeeting.value
    const next = nextMeetingMigrationDraft(
      { title: migrationTitle.value, goal: migrationGoal.value },
      { meetingId: previousMeetingId, requiresGoal: previousRequiresGoal },
      meeting
        ? {
            meetingId: meeting.meeting_id,
            requiresGoal: meeting.requires_goal,
            title: meeting.title,
            goal: meeting.goal,
          }
        : null,
    )
    migrationTitle.value = next.title
    migrationGoal.value = next.goal
  },
  { immediate: true },
)

watch(() => selectedMeeting.value?.meeting_id, () => {
  restartScope.value = 'all_deliberation'
  restartReason.value = ''
  restartIssueId.value = ''
})

watch(
  [restartScope, () => selectedMeeting.value?.courtroom?.current_issue_id, restartableIssues],
  ([scope, currentIssueId, issues]) => {
    if (scope !== 'current_issue') return
    if (issues.some((issue) => issue.id === restartIssueId.value)) return
    restartIssueId.value = currentIssueId || issues[0]?.id || ''
  },
  { immediate: true },
)

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') advancedOpen.value = false
}

// "開始新回合" runs the active mode's full step list from the top - describe it with
// that mode's own step labels (spec.md 16.2) instead of a hardcoded red-blue sequence, so
// this stays accurate for courtroom/debate/any future mode.
const roundStepsSummary = computed(() => (activeMode.value.steps ?? []).map((step) => step.label).join(' → '))
const participants = computed(() => selectedMeeting.value?.participants ?? [])
const failedRoleName = computed(() =>
  failedRole.value ? roleDisplayName(activeMode.value, participants.value, failedRole.value) : '',
)
const failedStepTitle = computed(() =>
  failedRole.value ? `${failedRoleName.value}的回應失敗了，請點擊席位重試該步驟` : undefined,
)
const lastStepLabel = computed(() => {
  const meeting = selectedMeeting.value
  const event = meeting?.events?.at(-1)
  return event ? stepDisplayLabel(activeMode.value, participants.value, event) : ''
})
const canSubmitChairman = computed(() => {
  if (!selectedMeeting.value || isTerminalMeeting.value || isMeetingRunning.value || loading.value || !chairMessage.value.trim()) return false
  if (chairmanAction.value === 'note') return true
  if (failedRole.value) return false
  if (chairmanAction.value === 'all') return canRun.value && !primaryAction.value.disabled
  return canRun.value
})
const hasAiOutput = computed(() => selectedMeeting.value?.events?.some(
  (event) => !['Human', 'System'].includes(event.role) && event.status === 'completed',
) ?? false)
const showPrimaryCta = computed(() => (
  selectedMeeting.value?.mode_id !== 'courtroom' && (!props.embedded || !hasAiOutput.value)
))
</script>

<template>
  <footer class="action-bar" :class="{ 'action-bar-embedded': embedded }" @keydown="onKeydown">
    <p v-if="error" class="error" data-testid="app-error">{{ error }}</p>

    <section
      v-if="selectedMeeting?.requires_goal"
      class="meeting-goal-migration"
      data-testid="meeting-goal-migration"
    >
      <strong>請先設定會議名稱與目標</strong>
      <p>舊會議不會把原主題自動當成 AI 目標；保存後才能繼續執行。</p>
      <label>
        會議名稱
        <input v-model="migrationTitle" aria-label="舊會議名稱" />
      </label>
      <label>
        目標
        <textarea v-model="migrationGoal" aria-label="舊會議目標" />
      </label>
      <button
        type="button"
        class="btn btn-primary"
        data-testid="save-meeting-goal-button"
        :disabled="loading || !migrationTitle.trim() || !migrationGoal.trim()"
        @click="updateSelectedMeetingDetails(migrationTitle, migrationGoal)"
      >
        保存並啟用
      </button>
    </section>

    <div class="action-bar-status" data-testid="operation-status">
      <span><i class="status-dot" :data-status="operationStatus" aria-hidden="true"></i>狀態：{{ operationStatusText }}</span>
      <span v-if="lastStepLabel">最後步驟：{{ lastStepLabel }}</span>
      <span v-if="selectedMeeting">更新：{{ formatDateTime(selectedMeeting.updated_at) }}</span>
    </div>

    <p v-if="currentStepProgress" class="step-progress-indicator" data-testid="step-progress-indicator">
      第 {{ currentStepProgress.index }} 步／共 {{ currentStepProgress.total }} 步：{{ currentStepProgress.label }}中
    </p>

    <p v-if="failedRole && !isTerminalMeeting" class="failed-step-hint" data-testid="failed-step-hint">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
      {{ failedRoleName }}的回應失敗了，點擊席位可重試
    </p>

    <div class="action-bar-row">
      <button
        v-if="embedded"
        type="button"
        class="btn btn-secondary workspace-materials-button"
        data-testid="workspace-open-materials"
        aria-label="開啟案卷與證據"
        :disabled="!selectedMeeting"
        @click="$emit('open-materials')"
      >＋</button>
      <label class="chairman-action-select">
        主席動作
        <select
          v-model="chairmanAction"
          data-testid="chairman-action-select"
          :disabled="loading || !selectedMeeting || isTerminalMeeting || isMeetingRunning"
        >
          <option v-for="option in chairmanOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>
      <textarea
        v-model="chairMessage"
        data-testid="chair-message-input"
        aria-label="主席發言"
        :placeholder="chairmanPresentation.placeholder"
        :disabled="loading || !selectedMeeting || isTerminalMeeting || isMeetingRunning"
      />
      <button
        type="button"
        class="btn btn-primary"
        data-testid="send-chair-message-button"
        @click="submitChairmanAction"
        :disabled="!canSubmitChairman"
      >
        {{ chairmanPresentation.submitLabel }}
      </button>
      <button
        v-if="showPrimaryCta"
        type="button"
        class="btn btn-primary action-bar-cta"
        data-testid="start-meeting-button"
        @click="startOrContinueMeeting"
        :disabled="loading || !canRun || !!failedRole || primaryAction.disabled"
        :title="failedStepTitle"
      >
        {{ startButtonLabel }}
      </button>
      <div class="advanced-options">
        <button
          type="button"
          class="btn btn-secondary"
          aria-label="流程操作"
          data-testid="advanced-options-button"
          @click="advancedOpen = !advancedOpen"
        >
          流程操作 ⋯
        </button>
        <div v-if="advancedOpen" class="advanced-options-panel" data-testid="advanced-options-panel">
          <strong>流程操作</strong>
          <section v-if="selectedMeeting && !isTerminalMeeting" class="restart-controls" data-testid="restart-controls">
            <h3>重開審議</h3>
            <p>舊討論會封存於議事紀錄；案卷與證據不會複製或刪除。</p>
            <label v-if="selectedMeeting.mode_id === 'courtroom'">重開範圍
              <select v-model="restartScope" data-testid="restart-scope-select" :disabled="loading || isMeetingRunning">
                <option value="current_issue" :disabled="!restartableIssues.length">重開單一爭點（保留其他爭點判斷）</option>
                <option value="all_deliberation">重開全部審議（保留已確認爭點）</option>
                <option value="rebuild_issues">重新整理爭點（解鎖目標與案件類型）</option>
              </select>
            </label>
            <label v-if="selectedMeeting.mode_id === 'courtroom' && restartScope === 'current_issue'">選擇爭點
              <select v-model="restartIssueId" data-testid="restart-issue-select" :disabled="loading || isMeetingRunning">
                <option v-for="issue in restartableIssues" :key="issue.id" :value="issue.id">{{ issue.position }}. {{ issue.title }}</option>
              </select>
            </label>
            <label>原因（必填）<textarea v-model="restartReason" data-testid="restart-reason-input" :disabled="loading || isMeetingRunning" placeholder="例如：新增重要證物，需重新評估" /></label>
            <p v-if="selectedMeeting.case_materials?.pending_impact" class="materials-impact-inline">案卷已變更，必須完成其中一種重開才能繼續 AI。</p>
            <button type="button" class="btn btn-secondary" data-testid="restart-deliberation-button" :disabled="loading || restarting || isMeetingRunning || !restartReason.trim() || (restartScope === 'current_issue' && !restartIssueId)" @click="restartDiscussion">{{ restarting ? '重開中…' : '確認重開' }}</button>
          </section>
          <section v-if="sequencePresets.length && selectedMeeting?.mode_id !== 'courtroom'" class="sequence-panel" data-testid="role-sequence-controls">
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
              :disabled="loading || !canRun || !!failedRole"
              :title="failedStepTitle"
            >
              執行序列
            </button>
          </section>
          <small v-if="roundStepsSummary && selectedMeeting?.mode_id !== 'courtroom'">回合流程：{{ roundStepsSummary }}</small>
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
            <button
              type="button"
              class="btn btn-secondary"
              data-testid="reopen-meeting-button"
              @click="reopenSelectedMeeting"
              :disabled="loading || !selectedMeeting || !isTerminalMeeting"
            >
              重新開啟
            </button>
          </div>
        </div>
      </div>
    </div>
    <p v-if="chairmanActionFeedback" class="success" data-testid="chairman-action-feedback">
      {{ chairmanActionFeedback }}
    </p>
  </footer>
</template>
