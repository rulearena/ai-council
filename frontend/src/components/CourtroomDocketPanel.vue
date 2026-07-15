<script setup lang="ts">
import { computed, inject, reactive, ref, watch } from 'vue'
import {
  ApiError,
  confirmCourtroomIssues,
  draftCourtroomIssues,
  replaceCourtroomIssues,
  updateCourtroomCaseType,
  type CourtroomIssueProjection,
  type MeetingEvent,
  type CourtroomCivilFinal,
  type CourtroomCriminalFinal,
} from '../api'
import { councilKey } from '../composables/useCouncil'
import {
  courtroomFailedPhaseLabel,
  courtroomIssueStatusLabel,
  courtroomOutcomeLabel,
  nextCourtroomDraft,
  type CourtroomDraft,
} from '../courtroomWorkspace'

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
} = store

const drafts = reactive<Record<string, CourtroomDraft>>({})
const busy = ref(false)
const feedback = ref('')
const localError = ref('')
const selectedCaseType = ref<'' | 'civil' | 'criminal'>('')

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
const primaryLabel = computed(() => {
  const projection = courtroom.value
  const issue = currentIssue.value
  if (!projection || !issue) return primaryAction.value.label
  if (primaryAction.value.kind === 'courtroom-arguments') {
    const hasRuled = projection.issues.some((candidate) => candidate.status === 'ruled')
    return hasRuled
      ? `進入下一爭點：${issue.title}（下一位是檢察官）`
      : `開始此爭點：${issue.title}（下一位是檢察官）`
  }
  return primaryAction.value.label
})

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

async function selectCaseType() {
  if (!selectedCaseType.value) return
  const id = meetingId.value
  await runWorkspaceAction(async () => {
    await updateCourtroomCaseType(id, selectedCaseType.value as 'civil' | 'criminal')
    await openMeeting(id)
    feedback.value = '案件類型已設定。'
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
  <section v-if="isCourtroom && courtroom" class="courtroom-docket" data-testid="courtroom-docket-panel">
    <header class="courtroom-docket-header">
      <div>
        <h2>爭點審理</h2>
        <p v-if="courtroom.status !== 'confirmed'">先建立並確認爭點；確認前不會開始審理。</p>
        <p v-else>一次只處理一個爭點；每次攻防與法官判斷後都會停下等待主席。</p>
      </div>
      <span class="docket-state" data-testid="courtroom-docket-status">
        {{ courtroom.status === 'confirmed' ? '已確認' : '草稿，尚未開始審理' }}
      </span>
    </header>

    <div v-if="courtroom.requires_case_type" class="courtroom-case-type-gate" data-testid="legacy-courtroom-case-type-gate">
      <p>這是舊法院會議。請先選擇案件類型，AI 才能依正確角色與法律流程繼續。</p>
      <select v-model="selectedCaseType" data-testid="legacy-courtroom-case-type-select" aria-label="案件類型">
        <option value="" disabled>請選擇民事或刑事</option>
        <option value="civil">民事</option>
        <option value="criminal">刑事</option>
      </select>
      <button type="button" class="btn btn-primary" data-testid="save-courtroom-case-type-button" :disabled="busy || !selectedCaseType" @click="selectCaseType">套用案件類型</button>
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
      <li v-for="issue in courtroom.issues" :key="issue.id" :class="{ current: issue.id === courtroom.current_issue_id }" :data-issue-id="issue.id">
        <header>
          <strong>{{ issue.position }}. {{ issue.title }}</strong>
          <span>{{ courtroomIssueStatusLabel(issue.status) }}</span>
        </header>
        <p v-if="issue.id === courtroom.current_issue_id" class="current-focus">目前焦點</p>
        <section v-if="issue.status === 'failed'" class="issue-failure" :data-testid="`courtroom-issue-failure-${issue.id}`">
          <p><strong>{{ issue.failed_phase_display || courtroomFailedPhaseLabel(issue.failed_phase) }}執行失敗，請重試。</strong></p>
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :data-testid="`retry-courtroom-issue-${issue.id}`"
            :disabled="busy || isMeetingRunning || !failedEvent(issue)"
            @click="retryIssue(issue)"
          >
            {{ busy || isMeetingRunning ? '重新執行中…' : `重試${issue.failed_phase_display || courtroomFailedPhaseLabel(issue.failed_phase)}` }}
          </button>
          <p v-if="!failedEvent(issue)" class="error">找不到可重試的失敗紀錄，請到「會議紀錄」查看診斷。</p>
        </section>
        <section v-if="ruling(issue)" class="issue-ruling" :data-testid="`courtroom-ruling-${issue.id}`">
          <h3>法官對此爭點的判斷：{{ courtroomOutcomeLabel(ruling(issue)!.outcome, courtroom.case_type) }}</h3>
          <p><strong>理由：</strong>{{ ruling(issue)!.reasoning }}</p>
          <p><strong>證據：</strong>{{ ruling(issue)!.evidence_refs.length ? ruling(issue)!.evidence_refs.join('、') : '未引用證據' }}</p>
          <p><strong>未解問題：</strong>{{ ruling(issue)!.unresolved_questions.length ? ruling(issue)!.unresolved_questions.join('；') : '無' }}</p>
        </section>
      </li>
    </ol>

    <div v-if="courtroom.status === 'confirmed' && courtroom.final_status !== 'completed' && !failedIssue" class="courtroom-primary-action">
      <p v-if="currentIssue">目前焦點：{{ currentIssue.title }}</p>
      <button type="button" class="btn btn-primary" data-testid="courtroom-primary-action" :disabled="busy || isMeetingRunning || primaryAction.disabled" @click="startOrContinueMeeting">
        {{ isMeetingRunning ? '執行中…' : primaryLabel }}
      </button>
    </div>

    <section v-if="finalVerdict" class="courtroom-final-verdict" data-testid="courtroom-final-verdict">
      <h3>最終判決</h3>
      <p>{{ finalVerdict.summary }}</p>
      <template v-if="civilFinal">
        <article v-for="claim in civilFinal.claims" :key="claim.claim">
          <h4>{{ claim.claim }}：{{ claim.outcome }}</h4>
          <p><strong>理由：</strong>{{ claim.reasoning }}</p>
          <p><strong>給付／義務：</strong>{{ claim.relief.obligation }}</p>
          <p v-if="claim.relief.monetary_amount"><strong>金額：</strong>{{ claim.relief.monetary_amount }}</p>
          <p v-if="claim.relief.calculation_basis"><strong>計算基礎：</strong>{{ claim.relief.calculation_basis }}</p>
          <p><strong>證據：</strong>{{ claim.evidence_refs.join('、') || '未引用證據' }}</p>
        </article>
      </template>
      <template v-else-if="criminalFinal">
        <article v-for="charge in criminalFinal.charges" :key="charge.charge">
          <h4>{{ charge.charge }}：{{ charge.decision }}</h4>
          <p><strong>理由：</strong>{{ charge.reasoning }}</p>
          <p><strong>證據：</strong>{{ charge.evidence_refs.join('、') || '未引用證據' }}</p>
        </article>
        <p><strong>量刑考量：</strong>{{ criminalFinal.sentencing_factors.join('、') || '無' }}</p>
      </template>
    </section>

    <p v-if="feedback" class="success" data-testid="courtroom-workspace-feedback">{{ feedback }}</p>
    <p v-if="localError" class="error" data-testid="courtroom-workspace-error">{{ localError }}</p>
  </section>
</template>
