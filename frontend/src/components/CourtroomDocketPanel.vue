<script setup lang="ts">
import { computed, inject, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  ApiError,
  confirmCourtroomIssues,
  draftCourtroomIssues,
  replaceCourtroomIssues,
  type CourtroomIssueProjection,
  type MeetingEvent,
  type CourtroomCivilFinal,
  type CourtroomCriminalFinal,
} from '../api'
import {
  activeMode,
  councilKey,
  formatDateTime,
  roleClass,
  roleColorVars,
  roleIcon,
  type CouncilRole,
} from '../composables/useCouncil'
import {
  courtroomFailedPhaseLabel,
  courtroomFinalOutcomeLabel,
  courtroomIssueStatusLabel,
  courtroomOutcomeLabel,
  nextCourtroomDraft,
  type CourtroomDraft,
} from '../courtroomWorkspace'
import {
  isAttachmentEvent,
  latestWorkspaceMessageTarget,
  materialCountFor,
  materialVocabulary,
  messageClampPolicy,
  nextWorkspaceRoleFilter,
  projectMeetingWorkspace,
  type CourtHearingWorkspaceProjection,
  type CourtHearingIssueGroup,
  type WorkspaceMessage,
  type WorkspaceProjectionMeeting,
  type WorkspaceRoleFilter,
} from '../meetingWorkspace'
import { uploadAttachment } from '../api'
import { useMaterialUploads } from '../materialUploads'
import { modelDisplayLabel } from '../providers'
import type { SceneConfig } from '../scenes'
import ActionBar from './ActionBar.vue'
import AttachmentBubble from './AttachmentBubble.vue'
import CouncilStage from './CouncilStage.vue'
import MaterialsPanel from './MaterialsPanel.vue'
import Modal from './Modal.vue'
import RecordsDrawer from './RecordsDrawer.vue'
import RoleSilhouette from './RoleSilhouette.vue'

defineProps<{ scene: SceneConfig }>()
const emit = defineEmits<{
  'open-meeting-settings': []
  'role-click': [role: CouncilRole | 'Chairman']
}>()

const store = inject(councilKey)!
const {
  selectedMeeting,
  events,
  isMeetingRunning,
  isTerminalMeeting,
  primaryAction,
  startOrContinueMeeting,
  openMeeting,
  refreshMeetingUntilSettled,
  retrySelectedStep,
  pendingRoles,
  selectedModels,
  models,
  updateSelectedModel,
  operationStatusText,
  currentStepProgress,
  assignmentUpdateError,
} = store

const drafts = reactive<Record<string, CourtroomDraft>>({})
const busy = ref(false)
const feedback = ref('')
const localError = ref('')
const roleFilter = ref<WorkspaceRoleFilter | null>(null)
const expandedMessageIds = ref(new Set<string>())
const contextCollapsed = ref(false)
const sceneLightboxOpen = ref(false)
type CourtContextTab = 'context' | 'records' | 'materials'
const activeCourtContextTab = ref<CourtContextTab>('context')

const materialCount = computed(() => materialCountFor(selectedMeeting.value))
const vocab = computed(() => materialVocabulary(selectedMeeting.value?.mode_id ?? ''))
const {
  uploads: uploadList,
  textDraft: textDraftRef,
  onPickedFiles,
  retryUpload,
  dismissUpload,
} = useMaterialUploads({
  meetingId: () => selectedMeeting.value?.meeting_id,
  uploadAttachment,
  openMeeting: (meetingId) => openMeeting(meetingId),
  openMaterialsTab: () => openMaterialsTab(),
})

// 法庭版側欄無 mobileContextOpen（不會在窄視窗變成 overlay），只切頁籤＋展開。
function openMaterialsTab() {
  activeCourtContextTab.value = 'materials'
  contextCollapsed.value = false
}

const courtroom = computed(() => selectedMeeting.value?.courtroom ?? null)
const meetingId = computed(() => selectedMeeting.value?.meeting_id ?? '')
const isCourtroom = computed(() => selectedMeeting.value?.mode_id === 'courtroom')
const draft = computed(() => drafts[meetingId.value] ?? { revision: 0, issues: [] })
const editable = computed(() => courtroom.value?.status !== 'confirmed' && !isMeetingRunning.value && !isTerminalMeeting.value)
const dirty = computed(() => {
  const projection = courtroom.value
  if (!projection) return false
  return JSON.stringify(draft.value.issues) !== JSON.stringify(
    projection.issues.map(({ id, title }) => ({ id, title })),
  )
})
const failedDraft = computed(() => [...events.value].reverse().find(
  (event) => event.interaction_type === 'courtroom-issue-draft' &&
    event.status === 'failed' &&
    event.docket_revision === courtroom.value?.revision,
) ?? null)
const finalEvent = computed(() => [...events.value].reverse().find(
  (event) => event.interaction_type === 'courtroom-final-verdict' &&
    event.status === 'completed' &&
    event.docket_revision === courtroom.value?.revision,
) ?? null)
const finalVerdict = computed(() => finalEvent.value?.parsed_output as
  | CourtroomCivilFinal
  | CourtroomCriminalFinal
  | undefined)
const civilFinal = computed(() => courtroom.value?.case_type === 'civil'
  ? finalVerdict.value as CourtroomCivilFinal | undefined
  : undefined)
const criminalFinal = computed(() => courtroom.value?.case_type === 'criminal'
  ? finalVerdict.value as CourtroomCriminalFinal | undefined
  : undefined)
const currentIssue = computed(() => courtroom.value?.issues.find(
  (issue) => issue.id === courtroom.value?.current_issue_id,
) ?? courtroom.value?.issues.find((issue) => issue.status === 'pending') ?? null)
const failedIssue = computed(() => courtroom.value?.issues.find(
  (issue) => issue.status === 'failed',
) ?? null)
const primaryLabel = computed(() => primaryAction.value.label)
const primaryExplanation = computed(() => ({
  'courtroom-arguments': '按下後才會開始目前爭點的三段攻防。',
  'courtroom-ruling': '按下後才會呼叫法官；不會自動判斷。',
  'courtroom-final': '所有爭點均已判斷；按下後才會請法官作成全案最終判決。',
} as Record<string, string>)[primaryAction.value.kind] ?? '')
const workspace = computed<CourtHearingWorkspaceProjection | null>(() => {
  const meeting = selectedMeeting.value
  if (!meeting || meeting.mode_id !== 'courtroom') return null
  const projected = projectMeetingWorkspace({
    meeting: meeting as WorkspaceProjectionMeeting,
    mode: activeMode.value,
    thinkingRoleIds: pendingRoles.value,
  })
  return projected.family === 'court-hearing' ? projected : null
})
const assignmentWarnings = computed(() => {
  const participants = selectedMeeting.value?.participants ?? []
  return participants
    .filter((p) => p.model_assignment_warning)
    .map((p) => {
      const role = workspace.value?.roles.find((r) => r.roleId === p.role_id)
      const roleName = role?.name ?? p.role_id
      const warning = p.model_assignment_warning!
      if (warning.toLowerCase().includes('no models are configured')) {
        return `${roleName}：模型登錄表目前沒有可用模型。`
      }
      if (warning.startsWith('No saved model assignment')) {
        const defaultMatch = warning.match(/using default model '([^']+)'/)
        const fallbackName = defaultMatch ? resolveModelName(defaultMatch[1]) : ''
        return fallbackName
          ? `${roleName}：未指派模型，已自動使用「${fallbackName}」。`
          : `${roleName}：未指派模型。`
      }
      const originalMatch = warning.match(/(?:Assigned|Recovered) model '([^']+)'/)
      const defaultMatch = warning.match(/using default model '([^']+)'/)
      const originalName = originalMatch ? resolveModelName(originalMatch[1]) : originalMatch?.[1] ?? ''
      const fallbackName = defaultMatch ? resolveModelName(defaultMatch[1]) : ''
      if (originalName && fallbackName) {
        return `${roleName}：模型「${originalName}」已失效，目前使用「${fallbackName}」。`
      }
      return `${roleName}：${warning}`
    })
})
const selectedRoleId = computed(() => {
  const filter = roleFilter.value
  return filter && filter.meetingId === workspace.value?.meetingId ? filter.roleId : null
})
const courtGeneralMessages = computed(() => (workspace.value?.ungroupedMessages ?? []).filter(
  (message) => !message.event.interaction_type?.startsWith('courtroom-'),
))

watch(
  () => {
    const meeting = selectedMeeting.value
    return meeting?.mode_id === 'courtroom' && meeting.courtroom
      ? `${meeting.meeting_id}:${meeting.courtroom.revision}:${meeting.courtroom.status}`
      : ''
  },
  () => {
    const meeting = selectedMeeting.value
    if (!meeting?.courtroom || meeting.mode_id !== 'courtroom') return
    drafts[meeting.meeting_id] = nextCourtroomDraft(drafts, {
      meetingId: meeting.meeting_id,
      revision: meeting.courtroom.revision,
      issues: meeting.courtroom.issues,
    })
    feedback.value = ''
    localError.value = ''
  },
  { immediate: true },
)

watch(() => selectedMeeting.value?.meeting_id, () => {
  roleFilter.value = null
  expandedMessageIds.value = new Set()
})

function roleState(roleId: string) {
  return workspace.value?.roles.find((role) => role.roleId === roleId)?.state ?? 'waiting'
}

function roleStateLabel(state: ReturnType<typeof roleState>): string {
  if (state === 'thinking') return '思考中'
  if (state === 'completed') return '已完成'
  if (state === 'failed') return '失敗'
  return '等待中'
}

function roleModelLabel(roleId: string): string {
  const modelId = selectedModels.value[roleId]
  const model = models.value.find((candidate) => candidate.id === modelId)
  return model ? modelDisplayLabel(model) : modelId || '未選模型'
}

function resolveModelName(modelId: string): string {
  const model = models.value.find((m) => m.id === modelId)
  return model ? modelDisplayLabel(model) : modelId
}

const openModelSeatId = ref<string | null>(null)

function toggleModelSelect(roleId: string) {
  openModelSeatId.value = openModelSeatId.value === roleId ? null : roleId
}

async function switchSeatModel(roleId: CouncilRole, modelId: string) {
  await updateSelectedModel(roleId, modelId)
  openModelSeatId.value = null
}

function onDocumentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.workspace-role-model-select') && !target.closest('.workspace-role-model')) {
    openModelSeatId.value = null
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))

function filteredMessages(messages: WorkspaceMessage[]): WorkspaceMessage[] {
  const seen = new Set<string>()
  return messages.filter((message) => {
    if (seen.has(message.id)) return false
    seen.add(message.id)
    return !selectedRoleId.value || message.roleId === selectedRoleId.value
  })
}

function issueGroup(issueId: string): CourtHearingIssueGroup | undefined {
  return workspace.value?.issues.find((group) => group.issue.id === issueId)
}

function toggleMessage(messageId: string) {
  const next = new Set(expandedMessageIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  expandedMessageIds.value = next
}

function isExpanded(message: WorkspaceMessage): boolean {
  return expandedMessageIds.value.has(message.id)
}

async function selectRole(roleId?: string) {
  const currentWorkspace = workspace.value
  if (!currentWorkspace) return
  roleFilter.value = nextWorkspaceRoleFilter(roleFilter.value, currentWorkspace.meetingId, roleId)
  await nextTick()
  const target = latestWorkspaceMessageTarget(currentWorkspace, roleFilter.value)
  if (target) document.getElementById(`court-message-${target}`)?.scrollIntoView({ block: 'nearest' })
}

function phaseLabel(phase: string): string {
  return ({
    charge: courtroom.value?.case_type === 'civil' ? '原告代理人主張' : '檢察官主張',
    defense: courtroom.value?.case_type === 'civil' ? '被告代理人答辯' : '辯護律師答辯',
    rebuttal: courtroom.value?.case_type === 'civil' ? '原告代理人反駁' : '檢察官反駁',
    ruling: '法官判斷',
  } as Record<string, string>)[phase] ?? phase
}

function messageTime(message: WorkspaceMessage): string {
  return message.createdAt ? formatDateTime(message.createdAt) : ''
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return '爭點清單已由其他操作更新，已重新載入最新版本；請重新確認修改。'
    if (typeof error.detail === 'string') return error.detail
  }
  return error instanceof Error ? error.message : String(error)
}

async function refreshAfterConflict(id: string) {
  delete drafts[id]
  if (selectedMeeting.value?.meeting_id === id) await openMeeting(id)
}

async function runWorkspaceAction(action: () => Promise<void>) {
  busy.value = true
  feedback.value = ''
  localError.value = ''
  try {
    await action()
  } catch (error) {
    localError.value = errorMessage(error)
    if (error instanceof ApiError && error.status === 409) await refreshAfterConflict(meetingId.value)
  } finally {
    busy.value = false
  }
}

function addIssue() {
  drafts[meetingId.value].issues.push({ title: '' })
}

function removeIssue(index: number) {
  drafts[meetingId.value].issues.splice(index, 1)
}

function moveIssue(index: number, offset: number) {
  const nextIndex = index + offset
  if (nextIndex < 0 || nextIndex >= draft.value.issues.length) return
  const [issue] = drafts[meetingId.value].issues.splice(index, 1)
  drafts[meetingId.value].issues.splice(nextIndex, 0, issue)
}

async function generateDraft() {
  const id = meetingId.value
  const revision = courtroom.value?.revision ?? 0
  await runWorkspaceAction(async () => {
    await draftCourtroomIssues(id, revision)
    feedback.value = 'AI 正在產生爭點草稿；完成後仍需由主席確認。'
    if (selectedMeeting.value?.meeting_id === id) await openMeeting(id)
    void refreshMeetingUntilSettled(id)
  })
}

async function saveIssues() {
  const id = meetingId.value
  await runWorkspaceAction(async () => {
    await replaceCourtroomIssues(id, draft.value.revision, draft.value.issues)
    delete drafts[id]
    if (selectedMeeting.value?.meeting_id === id) await openMeeting(id)
    feedback.value = '爭點草稿已儲存，尚未開始審理。'
  })
}

async function confirmIssues() {
  const id = meetingId.value
  await runWorkspaceAction(async () => {
    await confirmCourtroomIssues(id, courtroom.value!.revision)
    delete drafts[id]
    if (selectedMeeting.value?.meeting_id === id) await openMeeting(id)
    feedback.value = '爭點已確認，現在可逐一開始攻防。'
  })
}

async function retryDraft() {
  if (!failedDraft.value) return
  await retrySelectedStep(failedDraft.value)
}

function failedEvent(issue: CourtroomIssueProjection): MeetingEvent | null {
  if (issue.status !== 'failed' || !issue.failed_step_id) return null
  return [...events.value].reverse().find(
    (event) => event.step_id === issue.failed_step_id && event.status === 'failed',
  ) ?? null
}

async function retryIssue(issue: CourtroomIssueProjection) {
  const event = failedEvent(issue)
  if (!event) return
  await runWorkspaceAction(async () => {
    const accepted = await retrySelectedStep(event)
    if (accepted) feedback.value = `${courtroomFailedPhaseLabel(issue.failed_phase)}已重新執行。`
  })
}

function ruling(issue: CourtroomIssueProjection) {
  return issue.ruling
}
</script>

<template>
  <section v-if="isCourtroom && courtroom && workspace && selectedMeeting" class="conversation-workspace court-hearing-workspace" data-testid="court-hearing-workspace">
    <nav class="workspace-role-rail" data-testid="workspace-role-rail" aria-label="法庭角色">
      <div class="workspace-role-seats">
      <!-- Same seat contract as the conversation workspace: the seat is a plain
           container, its primary action is a real <button> that filters the docket, and
           the ℹ and model controls sit beside it instead of nested inside another
           interactive element. The Chairman seat behaves like every other seat. -->
      <div
        class="workspace-role-seat workspace-role-chairman"
        :class="{ active: selectedRoleId === 'Chairman' }"
      >
        <button
          type="button"
          class="workspace-role-button"
          data-testid="role-seat-chairman"
          data-status="chairman"
          aria-label="主席"
          :aria-pressed="selectedRoleId === 'Chairman'"
          @click="selectRole('Chairman')"
        >
          <span class="workspace-role-avatar"><RoleSilhouette color="currentColor" :size="26" /></span>
          <span class="workspace-role-name">主席</span>
        </button>
        <button
          type="button"
          class="workspace-role-info-btn"
          data-testid="role-seat-chairman-info"
          aria-label="主席詳情"
          @click="emit('role-click', 'Chairman')"
        >ℹ</button>
      </div>
      <div
        v-for="role in workspace.roles"
        :key="role.roleId"
        class="workspace-role-seat"
        :class="[roleClass(role.roleId), { active: selectedRoleId === role.roleId }]"
        :style="roleColorVars(role.roleId)"
      >
        <button
          type="button"
          class="workspace-role-button"
          :class="roleClass(role.roleId)"
          :data-testid="`role-seat-${role.roleId.toLowerCase()}`"
          :data-status="role.state"
          :aria-label="`${role.name}，${roleStateLabel(role.state)}`"
          :aria-pressed="selectedRoleId === role.roleId"
          @click="selectRole(role.roleId)"
        >
          <span class="workspace-role-avatar">
            <img v-if="roleIcon(role.roleId)" :src="roleIcon(role.roleId)" :alt="role.name" />
            <RoleSilhouette v-else :color="'var(--role-color)'" :size="26" />
            <i v-if="role.state === 'thinking'" class="workspace-thinking-pulse" aria-hidden="true"></i>
          </span>
          <span class="workspace-role-name">{{ role.name }}</span>
          <span class="workspace-role-state">{{ roleStateLabel(role.state) }}</span>
        </button>
        <button v-if="openModelSeatId !== role.roleId" type="button" class="workspace-role-model"
          :title="isMeetingRunning ? '會議執行中無法更換模型' : `目前模型：${roleModelLabel(role.roleId)}（點擊更換）`"
          :aria-label="`更換${role.name}的模型，目前為 ${roleModelLabel(role.roleId)}`"
          :data-testid="`seat-model-label-${role.roleId.toLowerCase()}`"
          @click="toggleModelSelect(role.roleId)"
        >
          <span class="workspace-role-model-text">{{ roleModelLabel(role.roleId) }}</span>
          <svg class="workspace-role-model-caret" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <select v-else class="workspace-role-model-select"
          :data-testid="`seat-model-select-${role.roleId.toLowerCase()}`"
          :value="selectedModels[role.roleId]"
          :disabled="isMeetingRunning"
          title="會議執行中無法更換模型"
          aria-label="會議執行中無法更換模型"
          @change="switchSeatModel(role.roleId, ($event.target as HTMLSelectElement).value)"
          @click.stop
        >
          <option v-for="model in models" :key="model.id" :value="model.id">{{ modelDisplayLabel(model) }}</option>
        </select>
        <button
          type="button"
          class="workspace-role-info-btn"
          :data-testid="`role-seat-${role.roleId.toLowerCase()}-info`"
          :aria-label="`${role.name}詳情`"
          @click.stop="emit('role-click', role.roleId)"
        >ℹ</button>
      </div>
      </div>
      <div v-if="assignmentWarnings.length" class="assignment-fallback-warning" data-testid="assignment-fallback-warning">
        <p v-for="(warning, idx) in assignmentWarnings" :key="idx">{{ warning }}</p>
      </div>
      <div v-if="assignmentUpdateError" class="assignment-update-error" role="alert" data-testid="assignment-update-error">
        {{ assignmentUpdateError }}
      </div>
    </nav>

    <section class="workspace-conversation-column" data-testid="court-hearing-record">
      <div class="court-hearing-toolbar" :class="{ active: selectedRoleId }">
        <button v-if="selectedRoleId" type="button" class="btn btn-ghost btn-sm" data-testid="workspace-clear-role-filter" @click="selectRole()">顯示全部庭審紀錄</button>
      </div>

      <div class="court-hearing-scroll" data-testid="court-hearing-scroll">
        <section class="courtroom-docket" data-testid="courtroom-docket-panel">
          <header class="courtroom-docket-header">
            <div>
              <h2>爭點審理</h2>
              <p v-if="courtroom.status !== 'confirmed'">先建立並確認爭點；確認前不會開始審理。</p>
              <p v-else>一次只處理一個爭點；攻防與法官判斷分階段保存。</p>
            </div>
            <span class="docket-state" data-testid="courtroom-docket-status">{{ courtroom.status === 'confirmed' ? '已確認' : '草稿，尚未開始審理' }}</span>
          </header>

          <section v-if="courtGeneralMessages.length" class="court-hearing-phase court-hearing-supplements" data-testid="court-hearing-general-record">
            <h3>主席與程序補充</h3>
            <article
              v-for="message in filteredMessages(courtGeneralMessages)"
              :id="`court-message-${message.id}`"
              :key="message.id"
              class="court-hearing-message"
              :data-role="message.roleId"
            >
              <header><strong>{{ message.roleName }}</strong><time v-if="message.createdAt" :datetime="message.createdAt">{{ messageTime(message) }}</time></header>
              <AttachmentBubble
                v-if="isAttachmentEvent(message.event)"
                :meeting-id="meetingId"
                :event="message.event"
                attachment-label="證物"
              />
              <template v-else>
                <p class="workspace-message-content" :class="{ collapsed: messageClampPolicy(message.content).collapsible && !isExpanded(message) }">{{ message.content || '（沒有文字內容）' }}</p>
                <button v-if="messageClampPolicy(message.content).collapsible" type="button" class="workspace-message-toggle" :aria-expanded="isExpanded(message)" @click="toggleMessage(message.id)">{{ isExpanded(message) ? '收合長文' : '展開完整發言' }}</button>
              </template>
            </article>
          </section>

          <div v-if="courtroom.requires_case_type" class="courtroom-case-type-gate" data-testid="legacy-courtroom-case-type-gate">
            <p>這是舊法院會議。請到會議設定選擇案件類型並一次儲存全部設定，AI 才能依正確角色與法律流程繼續。</p>
            <button type="button" class="btn btn-primary" data-testid="open-meeting-settings-from-courtroom" @click="emit('open-meeting-settings')">前往會議設定</button>
          </div>

          <template v-else-if="courtroom.status !== 'confirmed'">
            <div class="courtroom-draft-actions">
              <button type="button" class="btn btn-secondary" data-testid="generate-courtroom-draft-button" :disabled="busy || isMeetingRunning" @click="generateDraft">
                <span v-if="busy || isMeetingRunning" class="loading-spinner" aria-hidden="true"></span>
                {{ busy || isMeetingRunning ? '正在產生爭點草稿…' : '讓 AI 產生爭點草稿' }}
              </button>
              <button type="button" class="btn btn-secondary" data-testid="add-courtroom-issue-button" :disabled="!editable" @click="addIssue">手動新增爭點</button>
            </div>
            <p v-if="failedDraft" class="error" data-testid="courtroom-draft-error">
              AI 草稿產生失敗：{{ failedDraft.error || '請重試，或改用手動新增爭點。' }}
              <button type="button" class="btn btn-secondary btn-sm" data-testid="retry-courtroom-draft-button" :disabled="busy || isMeetingRunning" @click="retryDraft">重試 AI 草稿</button>
            </p>
            <ol v-if="draft.issues.length" class="courtroom-issue-editor" data-testid="courtroom-issue-editor">
              <li v-for="(issue, index) in draft.issues" :key="issue.id ?? `new-${index}`">
                <span class="issue-number">{{ index + 1 }}</span>
                <input v-model="issue.title" :data-testid="`courtroom-issue-title-${index}`" :aria-label="`爭點 ${index + 1}`" :disabled="!editable" />
                <button type="button" class="btn btn-ghost btn-sm" :aria-label="`上移爭點 ${index + 1}`" :disabled="!editable || index === 0" @click="moveIssue(index, -1)">↑</button>
                <button type="button" class="btn btn-ghost btn-sm" :aria-label="`下移爭點 ${index + 1}`" :disabled="!editable || index === draft.issues.length - 1" @click="moveIssue(index, 1)">↓</button>
                <button type="button" class="btn btn-ghost btn-sm" :aria-label="`刪除爭點 ${index + 1}`" :disabled="!editable" @click="removeIssue(index)">刪除</button>
              </li>
            </ol>
            <p v-else class="empty-state" data-testid="courtroom-empty-docket">尚無爭點。可請 AI 產生草稿，或由主席手動新增。</p>
            <div class="courtroom-confirm-actions">
              <button type="button" class="btn btn-secondary" data-testid="save-courtroom-issues-button" :disabled="busy || !dirty || !draft.issues.length || draft.issues.some(issue => !issue.title.trim())" @click="saveIssues">儲存爭點草稿</button>
              <button type="button" class="btn btn-primary" data-testid="confirm-courtroom-issues-button" :disabled="busy || dirty || !courtroom.issues.length" @click="confirmIssues">確認爭點並鎖定目標</button>
            </div>
          </template>

          <ol v-else class="courtroom-issue-progress" data-testid="courtroom-issue-progress">
            <li
              v-for="issue in courtroom.issues"
              :key="issue.id"
              :class="{ current: issue.id === courtroom.current_issue_id }"
              :data-issue-id="issue.id"
              :data-testid="`court-issue-group-${issue.id}`"
            >
              <header><strong>{{ issue.position }}. {{ issue.title }}</strong><span>{{ courtroomIssueStatusLabel(issue.status) }}</span></header>
              <p v-if="issue.id === courtroom.current_issue_id" class="current-focus">目前焦點</p>

              <section
                v-for="phase in issueGroup(issue.id)?.phases ?? []"
                :key="phase.phase"
                class="court-hearing-phase"
                :data-testid="`court-phase-${phase.phase}-${issue.id}`"
              >
                <h3>{{ phaseLabel(phase.phase) }}</h3>
                <article
                  v-for="message in filteredMessages(phase.messages)"
                  :id="`court-message-${message.id}`"
                  :key="message.id"
                  class="court-hearing-message"
                  :style="roleColorVars(message.roleId)"
                  :data-role="message.roleId"
                >
                  <header><strong>{{ message.roleName }}</strong><time v-if="message.createdAt" :datetime="message.createdAt">{{ messageTime(message) }}</time></header>
                  <AttachmentBubble
                    v-if="isAttachmentEvent(message.event)"
                    :meeting-id="meetingId"
                    :event="message.event"
                    attachment-label="證物"
                  />
                  <template v-else>
                    <p class="workspace-message-content" :class="{ collapsed: messageClampPolicy(message.content).collapsible && !isExpanded(message) }">{{ message.content || '（沒有文字內容）' }}</p>
                    <button v-if="messageClampPolicy(message.content).collapsible" type="button" class="workspace-message-toggle" :aria-expanded="isExpanded(message)" @click="toggleMessage(message.id)">{{ isExpanded(message) ? '收合長文' : '展開完整發言' }}</button>
                  </template>
                </article>
                <p v-if="selectedRoleId && !filteredMessages(phase.messages).length" class="court-filter-empty">此階段沒有這個角色的發言。</p>
              </section>

              <section v-if="issueGroup(issue.id)?.otherMessages.length" class="court-hearing-phase court-hearing-supplements">
                <h3>庭審補充</h3>
                <article v-for="message in filteredMessages(issueGroup(issue.id)?.otherMessages ?? [])" :id="`court-message-${message.id}`" :key="message.id" class="court-hearing-message" :data-role="message.roleId">
                  <header><strong>{{ message.roleName }}</strong><time v-if="message.createdAt" :datetime="message.createdAt">{{ messageTime(message) }}</time></header>
                  <AttachmentBubble
                    v-if="isAttachmentEvent(message.event)"
                    :meeting-id="meetingId"
                    :event="message.event"
                    attachment-label="證物"
                  />
                  <template v-else>
                    <p class="workspace-message-content" :class="{ collapsed: messageClampPolicy(message.content).collapsible && !isExpanded(message) }">{{ message.content || '（沒有文字內容）' }}</p>
                    <button v-if="messageClampPolicy(message.content).collapsible" type="button" class="workspace-message-toggle" :aria-expanded="isExpanded(message)" @click="toggleMessage(message.id)">{{ isExpanded(message) ? '收合長文' : '展開完整發言' }}</button>
                  </template>
                </article>
              </section>

              <section v-if="issue.status === 'failed'" class="issue-failure" :data-testid="`courtroom-issue-failure-${issue.id}`">
                <p><strong>{{ issue.failed_phase_display || courtroomFailedPhaseLabel(issue.failed_phase) }}執行失敗，請重試。</strong></p>
                <button type="button" class="btn btn-primary btn-sm" :data-testid="`retry-courtroom-issue-${issue.id}`" :disabled="busy || isMeetingRunning || !failedEvent(issue)" @click="retryIssue(issue)">{{ busy || isMeetingRunning ? '重新執行中…' : `重試${issue.failed_phase_display || courtroomFailedPhaseLabel(issue.failed_phase)}` }}</button>
                <p v-if="!failedEvent(issue)" class="error">找不到可重試的失敗紀錄，請到「會議紀錄」查看診斷。</p>
              </section>
              <p v-if="issue.status === 'awaiting-ruling'" class="awaiting-ruling-explanation" :data-testid="`courtroom-awaiting-ruling-${issue.id}`">攻防已完成，等待主席送交法官；不會自動判斷。</p>
              <section v-if="ruling(issue)" class="issue-ruling" :data-testid="`courtroom-ruling-${issue.id}`">
                <h3>法官對此爭點的判斷：{{ courtroomOutcomeLabel(ruling(issue)!.outcome, courtroom.case_type) }}</h3>
                <p><strong>理由：</strong>{{ ruling(issue)!.reasoning }}</p>
                <p><strong>證據：</strong>{{ ruling(issue)!.evidence_refs.length ? ruling(issue)!.evidence_refs.join('、') : '未引用證據' }}</p>
                <p><strong>未解問題：</strong>{{ ruling(issue)!.unresolved_questions.length ? ruling(issue)!.unresolved_questions.join('；') : '無' }}</p>
              </section>
            </li>
          </ol>

          <section v-if="finalVerdict" class="courtroom-final-verdict" data-testid="courtroom-final-verdict">
            <h3>最終判決</h3><p>{{ finalVerdict.summary }}</p>
            <template v-if="civilFinal">
              <article v-for="claim in civilFinal.claims" :key="claim.claim">
                <h4>{{ claim.claim }}：{{ courtroomFinalOutcomeLabel(claim.outcome, 'civil') }}</h4>
                <p><strong>理由：</strong>{{ claim.reasoning }}</p><p><strong>給付／義務：</strong>{{ claim.relief.obligation }}</p>
                <p v-if="claim.relief.monetary_amount"><strong>金額：</strong>{{ claim.relief.monetary_amount }}</p>
                <p v-if="claim.relief.calculation_basis"><strong>計算基礎：</strong>{{ claim.relief.calculation_basis }}</p>
                <p><strong>證據：</strong>{{ claim.evidence_refs.join('、') || '未引用證據' }}</p>
              </article>
            </template>
            <template v-else-if="criminalFinal">
              <article v-for="charge in criminalFinal.charges" :key="charge.charge">
                <h4>{{ charge.charge }}：{{ courtroomFinalOutcomeLabel(charge.decision, 'criminal') }}</h4><p><strong>理由：</strong>{{ charge.reasoning }}</p><p><strong>證據：</strong>{{ charge.evidence_refs.join('、') || '未引用證據' }}</p>
              </article>
              <p><strong>量刑考量：</strong>{{ criminalFinal.sentencing_factors.join('、') || '無' }}</p>
            </template>
          </section>

          <p v-if="feedback" class="success" data-testid="courtroom-workspace-feedback">{{ feedback }}</p>
          <p v-if="localError" class="error" data-testid="courtroom-workspace-error">{{ localError }}</p>
        </section>
      </div>

      <ActionBar
        embedded
        @pick-files="onPickedFiles"
        @manage-materials="openMaterialsTab"
      />
    </section>

    <aside class="workspace-context-panel court-formal-context" :class="{ collapsed: contextCollapsed }" data-testid="court-formal-context">
      <header>
        <div class="workspace-context-tabs">
          <button type="button" class="workspace-context-tab" :class="{ active: activeCourtContextTab === 'context' }" data-testid="court-context-tab-context" @click="activeCourtContextTab = 'context'">正式流程</button>
          <button type="button" class="workspace-context-tab" :class="{ active: activeCourtContextTab === 'records' }" data-testid="court-context-tab-records" @click="activeCourtContextTab = 'records'">紀錄</button>
          <button type="button" class="workspace-context-tab" :class="{ active: activeCourtContextTab === 'materials' }" data-testid="court-context-tab-materials" @click="activeCourtContextTab = 'materials'">{{ vocab.tabLabel }}（{{ materialCount }}）</button>
        </div>
        <button type="button" class="btn btn-ghost btn-icon" :aria-label="contextCollapsed ? '展開正式流程' : '收合正式流程'" :aria-expanded="!contextCollapsed" @click="contextCollapsed = !contextCollapsed">{{ contextCollapsed ? '‹' : '›' }}</button>
      </header>
      <div v-if="!contextCollapsed" class="workspace-context-body">
        <template v-if="activeCourtContextTab === 'context'">
        <section><span>AI 最終目標</span><p>{{ selectedMeeting.goal }}</p></section>
        <section class="workspace-context-status"><span>目前狀態</span><strong>{{ operationStatusText }}</strong><small v-if="currentStepProgress">第 {{ currentStepProgress.index }}／{{ currentStepProgress.total }} 步 · {{ currentStepProgress.label }}</small></section>
        <div v-if="courtroom.status === 'confirmed' && courtroom.final_status !== 'completed' && !failedIssue" class="courtroom-primary-action" data-testid="courtroom-sticky-primary-action">
          <p v-if="currentIssue">目前焦點：{{ currentIssue.title }}</p>
          <small v-if="primaryExplanation" data-testid="courtroom-primary-action-explanation">{{ primaryExplanation }}</small>
          <button type="button" class="btn btn-primary" data-testid="courtroom-primary-action" :disabled="busy || isMeetingRunning || primaryAction.disabled" @click="startOrContinueMeeting">{{ isMeetingRunning ? '執行中…' : primaryLabel }}</button>
        </div>
        <section><span>庭審補充</span><p>下方輸入框只會記錄補充，或請後端允許的指定角色回應；不會裁定或推進正式流程。</p></section>
        <details class="workspace-scene-details" data-testid="workspace-scene-details"><summary>角色場景（次要狀態視圖）</summary><CouncilStage :scene="scene" seat-test-id-prefix="scene-role-seat" model-test-id-prefix="scene-seat-model-label" @seat-click="emit('role-click', $event)" @scene-click="sceneLightboxOpen = true" /></details>
        </template>
        <div v-else data-testid="court-context-records-section">
          <RecordsDrawer :show="true" inline />
        </div>
        <MaterialsPanel
          v-show="activeCourtContextTab === 'materials'"
          :active="activeCourtContextTab === 'materials'"
          :meeting-id="selectedMeeting.meeting_id"
          :uploads="uploadList"
          :text-draft="textDraftRef"
          @retry-upload="retryUpload"
          @dismiss-upload="dismissUpload"
          @text-draft-consumed="textDraftRef = null"
        />
      </div>
    </aside>
  </section>

  <Modal :show="sceneLightboxOpen" title="場景全覽" test-id="scene-lightbox-modal" @close="sceneLightboxOpen = false">
    <div class="scene-lightbox">
      <CouncilStage
        :scene="scene"
        seat-test-id-prefix="lb-role-seat"
        model-test-id-prefix="lb-seat-model-label"
      />
    </div>
  </Modal>
</template>
