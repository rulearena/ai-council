import { computed, onMounted, onUnmounted, ref, type InjectionKey } from 'vue'
import roleBlueIcon from '../assets/roles/blue.png'
import roleRedIcon from '../assets/roles/red.png'
import roleJudgeIcon from '../assets/roles/judge.png'
import {
  addMeetingMessage,
  cancelMeeting,
  closeMeeting,
  correctMeetingMessage,
  createMeeting,
  deleteMeeting,
  getMeeting,
  getMeetings,
  getModels,
  getTranscript,
  requestRoleResponse,
  requestRoleSequence,
  retryStep,
  startMeeting,
  subscribeMeetingEvents,
  testModel,
  transcriptDownloadUrl,
  updateMeetingPinned,
  updateMeetingTags,
  type Meeting,
  type MeetingEvent,
  type ModelConfig,
} from '../api'

export type CouncilRole = 'Blue' | 'Red' | 'Judge'
export type SeatOccupant = CouncilRole | 'Chairman'
export type SequencePreset = {
  id: string
  label: string
  roles: CouncilRole[]
}
export type ModelTestView = {
  status: 'unknown' | 'available' | 'unavailable'
  testedAt: string
  error: string
}
export type RoleSeatStatus = 'waiting' | 'thinking' | 'completed' | 'failed'

export const sequencePresets: SequencePreset[] = [
  { id: 'red-blue-judge', label: 'Red -> Blue -> Judge', roles: ['Red', 'Blue', 'Judge'] },
  { id: 'blue-red-judge', label: 'Blue -> Red -> Judge', roles: ['Blue', 'Red', 'Judge'] },
  { id: 'red-blue', label: 'Red -> Blue', roles: ['Red', 'Blue'] },
  { id: 'judge-only', label: 'Judge only', roles: ['Judge'] },
]

export const councilRoles: CouncilRole[] = ['Blue', 'Red', 'Judge']

// Backend fixed round flow (backend/ai_council/meetings/runner.py STEPS): retrying a
// failed step re-runs it plus every step after it, in the same synchronous call.
const FIXED_ROUND_STEP_ROLES: Record<string, CouncilRole[]> = {
  'blue-propose': ['Blue', 'Red', 'Blue', 'Judge'],
  'red-critique': ['Red', 'Blue', 'Judge'],
  'blue-revise': ['Blue', 'Judge'],
  'judge-decide': ['Judge'],
}

// The four base steps of one fixed round (backend/ai_council/meetings/runner.py STEPS).
// Directed/sequence responses reuse the same roles but under different base_step_ids
// ('blue-response' etc, see DIRECTED_RESPONSE_STEPS), so they never satisfy this list -
// only a genuine blue-propose/red-critique/blue-revise/judge-decide completion does.
const FIXED_ROUND_BASE_STEPS = ['blue-propose', 'red-critique', 'blue-revise', 'judge-decide'] as const

const ROLE_ICONS: Partial<Record<string, string>> = {
  Blue: roleBlueIcon,
  Red: roleRedIcon,
  Judge: roleJudgeIcon,
}

const ROLE_CLASSES: Partial<Record<string, string>> = {
  Blue: 'role-blue',
  Red: 'role-red',
  Judge: 'role-judge',
}

export function isCouncilRole(role: string): role is CouncilRole {
  return role === 'Blue' || role === 'Red' || role === 'Judge'
}

export function roleIcon(role: string): string | undefined {
  return ROLE_ICONS[role]
}

export function roleClass(role: string): string {
  return ROLE_CLASSES[role] ?? ''
}

export function formatDateTime(value: string | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export function useCouncil() {
  const models = ref<ModelConfig[]>([])
  const meetings = ref<Meeting[]>([])
  const selectedMeeting = ref<Meeting | null>(null)
  const selectedEvent = ref<MeetingEvent | null>(null)
  const topic = ref('先做後端核心流程')
  const selectedModels = ref({ Blue: '', Red: '', Judge: '' })
  const modelTestResults = ref<Record<CouncilRole, ModelTestView>>({
    Blue: { status: 'unknown', testedAt: '', error: '' },
    Red: { status: 'unknown', testedAt: '', error: '' },
    Judge: { status: 'unknown', testedAt: '', error: '' },
  })
  const chairMessage = ref('')
  const selectedSequencePresetId = ref(sequencePresets[0].id)
  const meetingSearch = ref('')
  const statusFilter = ref<'all' | Meeting['status']>('all')
  const transcriptSearchQuery = ref('')
  const transcriptSearchResults = ref<Meeting[] | null>(null)
  const transcript = ref('')
  const loading = ref(false)
  const error = ref('')
  const devMode = ref(false)
  let closeEventStream: (() => void) | null = null

  // event_ids this session has already processed for the currently-open meeting - lets
  // the WS handler tell a genuinely new event apart from one merely being resent (every
  // reconnect's first message is a "snapshot" of the *entire* event history, see
  // connectMeetingEvents/backend's meeting_events websocket handler). Deliberately NOT
  // reset on every reconnect (only on an actual meeting switch, in openMeeting below) -
  // event_ids are stable and unique per (step, round, attempt) (see runner.py's
  // `f"{meeting_id}:{event_step_id}:attempt-{attempt}:completed"`), so this survives
  // across the reconnects that startSelectedMeeting/retrySelectedStep/etc. trigger and
  // still lets a snapshot's *actually new* events (e.g. ones produced while briefly
  // disconnected) through - see applyPendingRoleUpdates's caller.
  let seenEventIds = new Set<string>()

  // Roles the backend has been asked to run but hasn't confirmed completed/failed yet.
  // The backend only emits completed/failed events (no "running" event), so this queue
  // is the sole source of the "thinking" state: pendingRoles[0] is thinking, the rest are queued.
  const pendingRoles = ref<CouncilRole[]>([])

  const meetingIdCopied = ref(false)
  let meetingIdCopiedTimeout: ReturnType<typeof setTimeout> | null = null

  // Briefly true right after a chair message is sent, so the Chairman seat can pop a
  // speech bubble even though the backend has no "speaking" concept of its own.
  const chairmanSpeaking = ref(false)
  let chairmanSpeakingTimeout: ReturnType<typeof setTimeout> | null = null

  // True right after a chair message is sent while the meeting is sitting idle, so the
  // action bar can nudge the user toward "繼續討論" / running a sequence next. Cleared
  // by any actual role action (see clearContinueHint), not by a timer.
  const showContinueHint = ref(false)

  const events = computed(() => selectedMeeting.value?.events ?? [])
  const isTerminalMeeting = computed(() =>
    events.value.some((event) => event.status === 'closed' || event.status === 'cancelled'),
  )
  const isMeetingRunning = computed(() => selectedMeeting.value?.activity_status === 'running')
  const startButtonLabel = computed(() => {
    if (isMeetingRunning.value) return '執行中...'
    return events.value.length ? '繼續討論' : '開始審議'
  })
  const selectedSequencePreset = computed(
    () => sequencePresets.find((preset) => preset.id === selectedSequencePresetId.value) ?? sequencePresets[0],
  )
  const operationStatus = computed(() => {
    if (loading.value) return 'running'
    return selectedMeeting.value?.activity_status ?? 'idle'
  })
  const filteredMeetings = computed(() => {
    const query = meetingSearch.value.trim().toLowerCase()
    return meetings.value
      .filter((meeting) => {
        const matchesStatus = statusFilter.value === 'all' || meeting.status === statusFilter.value
        const searchable = `${meeting.topic} ${meeting.meeting_id} ${meeting.last_step_id ?? ''} ${meeting.tags.join(' ')}`.toLowerCase()
        return matchesStatus && (!query || searchable.includes(query))
      })
      .sort(
        (left, right) =>
          Number(right.pinned) - Number(left.pinned) ||
          right.updated_at.localeCompare(left.updated_at),
      )
  })
  const roleOutputEvents = computed(() =>
    events.value.filter((event) => event.parsed_output),
  )
  const latestRoleEvent = computed<Record<CouncilRole, MeetingEvent | null>>(() => {
    const result: Record<CouncilRole, MeetingEvent | null> = { Blue: null, Red: null, Judge: null }
    for (const event of events.value) {
      if (isCouncilRole(event.role) && (event.status === 'completed' || event.status === 'failed')) {
        result[event.role] = event
      }
    }
    return result
  })
  const chairmanEvents = computed(() => events.value.filter((event) => event.role === 'Human'))
  // True once the *latest* fixed round (blue-propose/red-critique/blue-revise/judge-decide,
  // bucketed by base_step_id since a retried step keeps its original step_id/base_step_id)
  // has a completed event for all four base steps. Scoped to the latest `round` number so
  // a still-in-progress next round (or an intervening directed/sequence response, which
  // bumps the round counter under a different base_step_id) correctly reads as incomplete -
  // see startOrContinueMeeting.
  const isFixedRoundComplete = computed(() => {
    const roundEvents = events.value.filter((event) => isCouncilRole(event.role))
    if (!roundEvents.length) return false
    const latestRound = Math.max(...roundEvents.map((event) => event.round ?? 1))
    return FIXED_ROUND_BASE_STEPS.every((baseStepId) =>
      roundEvents.some(
        (event) =>
          (event.base_step_id ?? event.step_id) === baseStepId &&
          (event.round ?? 1) === latestRound &&
          event.status === 'completed',
      ),
    )
  })
  const canRun = computed(
    () =>
      selectedMeeting.value &&
      !isTerminalMeeting.value &&
      !isMeetingRunning.value &&
      selectedModels.value.Blue &&
      selectedModels.value.Red &&
      selectedModels.value.Judge,
  )
  // The role whose latest event is a failure, if any. Both /start and /sequences are a
  // known silent no-op once a step has failed (confirmed against the real backend: it
  // returns 200 "running" but appends zero events and never clears activity_status -
  // see runner.py's _first_incomplete_step_index returning None for a non-completed
  // latest event). Retrying the specific step via retrySelectedStep is the only way
  // forward, so callers use this to disable the round-level actions and point the user
  // at the failed seat instead of letting them hit that trap.
  const failedRole = computed<CouncilRole | null>(
    () => councilRoles.find((role) => roleSeatStatus(role) === 'failed') ?? null,
  )

  onMounted(async () => {
    await runAction(refreshAll)
  })

  onUnmounted(() => closeEventStream?.())

  async function refreshAll() {
    error.value = ''
    models.value = await getModels()
    meetings.value = await getMeetings()
    const firstModel = models.value[0]?.id ?? ''
    selectedModels.value = {
      Blue: selectedModels.value.Blue || firstModel,
      Red: selectedModels.value.Red || firstModel,
      Judge: selectedModels.value.Judge || firstModel,
    }
    if (selectedMeeting.value) {
      await openMeeting(selectedMeeting.value.meeting_id)
    }
  }

  async function createNewMeeting() {
    await runAction(async () => {
      const meeting = await createMeeting(topic.value)
      meetings.value = await getMeetings()
      await openMeeting(meeting.meeting_id)
    })
  }

  async function openMeeting(meetingId: string) {
    // Only reset the queue when actually switching meetings. requestSelectedRoleResponse /
    // requestSelectedRoleSequence / retrySelectedStep call openMeeting on the SAME meeting
    // right after enqueuing roles, so clearing unconditionally would erase what was just pushed.
    if (meetingId !== selectedMeeting.value?.meeting_id) {
      pendingRoles.value = []
      meetingIdCopied.value = false
      showContinueHint.value = false
      seenEventIds = new Set()
    }
    selectedMeeting.value = await getMeeting(meetingId)
    selectedEvent.value = selectedMeeting.value.events?.at(-1) ?? null
    transcript.value = await getTranscript(meetingId)
    connectMeetingEvents(meetingId)
  }

  function clearContinueHint() {
    showContinueHint.value = false
  }

  // The action bar's single primary CTA. Calling /start again once the latest fixed
  // round is already fully complete is a known no-op trap on the backend (it only
  // resumes an in-progress round or auto-advances into a *fresh* one - see runner.py's
  // start()); running the currently-selected sequence preset instead gives an actual,
  // lighter-weight way to keep the discussion going without silently doing nothing.
  async function startOrContinueMeeting() {
    if (isFixedRoundComplete.value) {
      await requestSelectedRoleSequence()
    } else {
      await startSelectedMeeting()
    }
  }

  async function startSelectedMeeting() {
    if (!selectedMeeting.value || !canRun.value) return
    clearContinueHint()
    const meetingId = selectedMeeting.value.meeting_id
    pendingRoles.value.push('Blue', 'Red', 'Blue', 'Judge')
    connectMeetingEvents(meetingId)
    await runAction(async () => {
      await startMeeting(meetingId, selectedModels.value)
      if (selectedMeeting.value?.meeting_id === meetingId) {
        selectedMeeting.value = { ...selectedMeeting.value, activity_status: 'running' }
      }
    })
  }

  function connectMeetingEvents(meetingId: string) {
    closeEventStream?.()
    closeEventStream = subscribeMeetingEvents(
      meetingId,
      (message) => {
        if (selectedMeeting.value?.meeting_id !== meetingId) return
        const currentEvents = message.type === 'snapshot' ? [] : (selectedMeeting.value.events ?? [])
        const nextEvents = [...currentEvents, ...message.events]
        const latestEvent = nextEvents.at(-1)
        selectedMeeting.value = {
          ...selectedMeeting.value,
          events: nextEvents,
          activity_status: message.activity_status,
          last_step_id: latestEvent?.step_id ?? null,
          updated_at: latestEvent?.created_at ?? selectedMeeting.value.updated_at,
        }
        // A reconnect's "snapshot" resends the meeting's *entire* history (not just what
        // happened since we disconnected), so most of its events are old news the
        // instant we've already lived through them once - only events this session has
        // never seen before should be allowed to resolve a pendingRoles entry. Without
        // this, starting round 2 right after round 1 completes reconnects the socket
        // before round 2 produces anything, and round 1's still-fresh-in-the-snapshot
        // completions immediately (and wrongly) clear round 2's just-pushed queue.
        const newEvents = message.events.filter((event) => !seenEventIds.has(event.event_id))
        for (const event of message.events) seenEventIds.add(event.event_id)
        applyPendingRoleUpdates(newEvents, message.activity_status)
        if (message.events.length) {
          selectedEvent.value = latestEvent ?? null
          void refreshMeetingOutputs(meetingId, message.activity_status)
        }
      },
      () => {
        error.value = 'Meeting event stream disconnected.'
        pendingRoles.value = []
      },
    )
  }

  function applyPendingRoleUpdates(newEvents: MeetingEvent[], activityStatus: Meeting['activity_status']) {
    for (const event of newEvents) {
      if (!isCouncilRole(event.role)) continue
      if (event.status !== 'completed' && event.status !== 'failed') continue
      const queueIndex = pendingRoles.value.indexOf(event.role)
      if (queueIndex === -1) continue
      if (event.status === 'failed') {
        // A failed step halts every remaining step in the same batch on the backend
        // (fixed round / role sequence / retry all stop after the first failure).
        pendingRoles.value = []
      } else {
        pendingRoles.value.splice(queueIndex, 1)
      }
    }
    if (activityStatus === 'closed' || activityStatus === 'cancelled') {
      pendingRoles.value = []
    }
  }

  async function refreshMeetingOutputs(meetingId: string, activityStatus: Meeting['activity_status']) {
    try {
      transcript.value = await getTranscript(meetingId)
      if (activityStatus !== 'running') {
        meetings.value = await getMeetings()
      }
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
    }
  }

  async function cancelSelectedMeeting() {
    if (!selectedMeeting.value) return
    if (!window.confirm('確定取消會議？會中止進行中的 AI 呼叫，且無法從介面復原。')) return
    await runAction(async () => {
      await cancelMeeting(selectedMeeting.value!.meeting_id)
      await openMeeting(selectedMeeting.value!.meeting_id)
    })
  }

  async function closeSelectedMeeting() {
    if (!selectedMeeting.value) return
    if (!window.confirm('確定結案？結案後無法再新增發言或回應。')) return
    await runAction(async () => {
      await closeMeeting(selectedMeeting.value!.meeting_id)
      await openMeeting(selectedMeeting.value!.meeting_id)
    })
  }

  async function deleteExistingMeeting(meeting: Meeting) {
    if (!window.confirm(`確定刪除「${meeting.topic}」？此操作無法復原。`)) return
    await runAction(async () => {
      await deleteMeeting(meeting.meeting_id)
      if (selectedMeeting.value?.meeting_id === meeting.meeting_id) {
        closeEventStream?.()
        closeEventStream = null
        selectedMeeting.value = null
        selectedEvent.value = null
        transcript.value = ''
        pendingRoles.value = []
        seenEventIds = new Set()
      }
      meetings.value = await getMeetings()
      if (transcriptSearchResults.value) {
        transcriptSearchResults.value = transcriptSearchResults.value.filter(
          (candidate) => candidate.meeting_id !== meeting.meeting_id,
        )
      }
    })
  }

  async function editMeetingTags(meeting: Meeting) {
    const input = window.prompt('編輯標籤（用逗號分隔）：', meeting.tags.join(', '))
    if (input === null) return
    const tags = input
      .split(',')
      .map((tag) => tag.trim())
      .filter((tag) => tag.length > 0)
    await runAction(async () => {
      await updateMeetingTags(meeting.meeting_id, tags)
      meetings.value = await getMeetings()
      if (selectedMeeting.value?.meeting_id === meeting.meeting_id) {
        selectedMeeting.value = meetings.value.find((m) => m.meeting_id === meeting.meeting_id) ?? null
      }
    })
  }

  async function toggleMeetingPinned(meeting: Meeting) {
    await runAction(async () => {
      await updateMeetingPinned(meeting.meeting_id, !meeting.pinned)
      meetings.value = await getMeetings()
      if (selectedMeeting.value?.meeting_id === meeting.meeting_id) {
        selectedMeeting.value = meetings.value.find((m) => m.meeting_id === meeting.meeting_id) ?? null
      }
    })
  }

  async function searchTranscripts() {
    const query = transcriptSearchQuery.value.trim()
    if (!query) return
    await runAction(async () => {
      transcriptSearchResults.value = await getMeetings(query)
    })
  }

  async function testSelectedModel(role: CouncilRole) {
    const modelId = selectedModels.value[role]
    if (!modelId) return
    await runAction(async () => {
      const result = await testModel(modelId)
      modelTestResults.value[role] = {
        status: result.status,
        testedAt: result.tested_at,
        error: result.error ?? '',
      }
    })
  }

  async function sendChairMessage() {
    if (!selectedMeeting.value || !chairMessage.value.trim()) return
    await runAction(async () => {
      await addMeetingMessage(selectedMeeting.value!.meeting_id, chairMessage.value.trim())
      chairMessage.value = ''
      await openMeeting(selectedMeeting.value!.meeting_id)
      chairmanSpeaking.value = true
      if (chairmanSpeakingTimeout) clearTimeout(chairmanSpeakingTimeout)
      chairmanSpeakingTimeout = setTimeout(() => {
        chairmanSpeaking.value = false
      }, 2500)
      // Nudge toward the next step only when the meeting is actually sitting idle
      // waiting on the user - not while a role is already running.
      if (!isMeetingRunning.value) {
        showContinueHint.value = true
      }
    })
  }

  async function correctSelectedMessage(event: MeetingEvent) {
    if (!selectedMeeting.value) return
    const corrected = window.prompt('修正主席發言：', event.content ?? '')
    if (corrected === null) return
    const trimmed = corrected.trim()
    if (!trimmed || trimmed === event.content) return
    await runAction(async () => {
      await correctMeetingMessage(selectedMeeting.value!.meeting_id, event.event_id, trimmed)
      await openMeeting(selectedMeeting.value!.meeting_id)
    })
  }

  async function requestSelectedRoleResponse(role: CouncilRole) {
    if (!selectedMeeting.value || !canRun.value) return
    clearContinueHint()
    pendingRoles.value.push(role)
    await runAction(async () => {
      await requestRoleResponse(selectedMeeting.value!.meeting_id, role, selectedModels.value)
      await openMeeting(selectedMeeting.value!.meeting_id)
    })
  }

  async function requestSelectedRoleSequence() {
    if (!selectedMeeting.value || !canRun.value) return
    clearContinueHint()
    pendingRoles.value.push(...selectedSequencePreset.value.roles)
    await runAction(async () => {
      await requestRoleSequence(
        selectedMeeting.value!.meeting_id,
        selectedSequencePreset.value.roles,
        selectedModels.value,
      )
      await openMeeting(selectedMeeting.value!.meeting_id)
    })
  }

  async function retrySelectedStep(event: MeetingEvent) {
    if (!selectedMeeting.value || !canRun.value || event.status !== 'failed') return
    clearContinueHint()
    const baseStepId = event.base_step_id ?? event.step_id
    const remainingRoles = FIXED_ROUND_STEP_ROLES[baseStepId] ?? (isCouncilRole(event.role) ? [event.role] : [])
    pendingRoles.value.push(...remainingRoles)
    await runAction(async () => {
      await retryStep(selectedMeeting.value!.meeting_id, event.step_id, selectedModels.value)
      await openMeeting(selectedMeeting.value!.meeting_id)
    })
  }

  async function copyMeetingId(meetingId: string) {
    try {
      await navigator.clipboard.writeText(meetingId)
      meetingIdCopied.value = true
      if (meetingIdCopiedTimeout) clearTimeout(meetingIdCopiedTimeout)
      meetingIdCopiedTimeout = setTimeout(() => {
        meetingIdCopied.value = false
      }, 1500)
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
    }
  }

  function roleQueueIndex(role: CouncilRole): number {
    return pendingRoles.value.indexOf(role)
  }

  function roleSeatStatus(role: CouncilRole): RoleSeatStatus {
    const queueIndex = roleQueueIndex(role)
    if (queueIndex === 0) return 'thinking'
    if (queueIndex > 0) return 'waiting'
    const latest = latestRoleEvent.value[role]
    if (latest) return latest.status === 'failed' ? 'failed' : 'completed'
    return 'waiting'
  }

  function roleSeatLabel(role: CouncilRole): string {
    const queueIndex = roleQueueIndex(role)
    if (queueIndex === 0) return '思考中…'
    if (queueIndex > 0) return '排隊中'
    const latest = latestRoleEvent.value[role]
    if (latest) return latest.status === 'failed' ? '失敗' : '已完成'
    return '等待中'
  }

  // All completed/failed events for a role, oldest first - the drawer's expandable
  // "past rounds" list.
  function roleHistory(role: CouncilRole): MeetingEvent[] {
    return events.value.filter(
      (event) => event.role === role && (event.status === 'completed' || event.status === 'failed'),
    )
  }

  async function runAction(action: () => Promise<void>) {
    loading.value = true
    error.value = ''
    try {
      await action()
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
    } finally {
      loading.value = false
    }
  }

  return {
    // state
    models,
    meetings,
    selectedMeeting,
    selectedEvent,
    topic,
    selectedModels,
    modelTestResults,
    chairMessage,
    selectedSequencePresetId,
    meetingSearch,
    statusFilter,
    transcriptSearchQuery,
    transcriptSearchResults,
    transcript,
    loading,
    error,
    devMode,
    pendingRoles,
    meetingIdCopied,
    chairmanSpeaking,
    showContinueHint,
    // computed
    events,
    isTerminalMeeting,
    isMeetingRunning,
    startButtonLabel,
    selectedSequencePreset,
    operationStatus,
    filteredMeetings,
    roleOutputEvents,
    latestRoleEvent,
    chairmanEvents,
    canRun,
    isFixedRoundComplete,
    failedRole,
    // actions
    refreshAll,
    createNewMeeting,
    openMeeting,
    startSelectedMeeting,
    startOrContinueMeeting,
    cancelSelectedMeeting,
    closeSelectedMeeting,
    deleteExistingMeeting,
    editMeetingTags,
    toggleMeetingPinned,
    searchTranscripts,
    testSelectedModel,
    sendChairMessage,
    correctSelectedMessage,
    requestSelectedRoleResponse,
    requestSelectedRoleSequence,
    retrySelectedStep,
    copyMeetingId,
    roleSeatStatus,
    roleSeatLabel,
    roleHistory,
    runAction,
    // constants re-exported for convenience
    sequencePresets,
    councilRoles,
    transcriptDownloadUrl,
  }
}

export type CouncilStore = ReturnType<typeof useCouncil>
export const councilKey: InjectionKey<CouncilStore> = Symbol('council')
