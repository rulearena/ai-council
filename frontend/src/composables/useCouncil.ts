import { computed, onMounted, onUnmounted, ref, type InjectionKey } from 'vue'
import roleBlueIcon from '../assets/roles/blue.png'
import roleRedIcon from '../assets/roles/red.png'
import roleJudgeIcon from '../assets/roles/judge.png'
import { DEFAULT_MODE_ID, getModeById, type ModeRoleDefinition } from '../modes'
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

// A role id as it appears in events.jsonl's `role` field. Used to be a hardcoded
// 'Blue' | 'Red' | 'Judge' union; every meeting is still actually red-blue in slice A (no
// backend mode_id yet - spec.md 16.7), but the type itself no longer bakes that in, so
// seat rendering/pendingRoles/drawers/event bucketing generalize to any mode's roster
// once slice B/C add real participants.
export type CouncilRole = string
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

// The only mode slice A can actually create meetings for (spec.md 16.7). Every meeting
// today is implicitly this mode - there's no per-meeting mode_id from the backend yet -
// so this is the single source of truth for "which roles exist" until slice B ships
// GET /modes and a real participants list per meeting. Exported so the step-progress
// indicator (ActionBar.vue) can read its `steps`/`category` for display purposes.
export const activeMode = getModeById(DEFAULT_MODE_ID)!

// The active mode's roster (id + kind), for anything that needs to know each role's
// *kind* rather than just its id - currently just CouncilStage.vue, to resolve which
// scene slot (adjudicator/podium/ring) each role occupies (see scenes.ts's
// resolveSceneSeats). Kept as its own export rather than making callers reach into
// modes.ts directly, so there's one place that says "this is the mode running right now".
export const activeModeRoles: ModeRoleDefinition[] = activeMode.roles

export const sequencePresets: SequencePreset[] = [
  { id: 'red-blue-judge', label: 'Red -> Blue -> Judge', roles: ['Red', 'Blue', 'Judge'] },
  { id: 'blue-red-judge', label: 'Blue -> Red -> Judge', roles: ['Blue', 'Red', 'Judge'] },
  { id: 'red-blue', label: 'Red -> Blue', roles: ['Red', 'Blue'] },
  { id: 'judge-only', label: 'Judge only', roles: ['Judge'] },
]

// Every AI role id in the active mode's roster, in display order - replaces the old
// hardcoded `['Blue', 'Red', 'Judge']` literal with the same three ids, sourced from
// modes.ts so there's exactly one place that spells out red-blue's roster.
export const councilRoles: CouncilRole[] = activeMode.roles.map((role) => role.id)

// Backend fixed round flow (backend/ai_council/meetings/runner.py STEPS): retrying a
// failed step re-runs it plus every step after it, in the same synchronous call. This
// stays hand-written (not derived from modes.ts's steps[]) on purpose: the backend is
// unchanged in slice A and only ever emits these four red-blue base_step_ids, so
// deriving this from catalog data would add a mapping layer with no runtime benefit and
// a real risk of silently drifting from what the backend actually does.
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

// Maps modes.ts's abstract `portrait` key (the small-icon identity, not the scene's
// full-body art) to the actual asset. Only three exist by hand today; any role without a
// matching key (every non-red-blue mode's roles, by design - see modes.ts) falls back to
// RoleSilhouette instead, tinted with that role's catalog color.
const ROLE_ICON_ASSETS: Partial<Record<string, string>> = {
  blue: roleBlueIcon,
  red: roleRedIcon,
  judge: roleJudgeIcon,
}

const NEUTRAL_ROLE_COLOR = '#9aa5b5'

function activeRoleDefinition(role: string): ModeRoleDefinition | undefined {
  return activeMode.roles.find((candidate) => candidate.id === role)
}

export function isCouncilRole(role: string): role is CouncilRole {
  return councilRoles.includes(role)
}

// undefined => no hand-drawn icon asset for this role; callers render RoleSilhouette
// (tinted via roleColor) instead. Never true for 'Human'/'Chairman', which aren't
// members of any mode's roster and always go through their own dedicated UI branch.
export function roleIcon(role: string): string | undefined {
  const portraitKey = activeRoleDefinition(role)?.portrait
  return portraitKey ? ROLE_ICON_ASSETS[portraitKey] : undefined
}

// Generic 'role-<id>' class, e.g. 'role-blue' - still literal-matches the CSS/e2e
// expectations for today's three roles, but now derived from the role id itself rather
// than an enumerated map, so it generalizes to any future role without edits here.
// Empty string (no class) for anything outside the active mode's roster (e.g. 'Human'),
// matching the old ROLE_CLASSES map's behavior of leaving those un-styled.
export function roleClass(role: string): string {
  return isCouncilRole(role) ? `role-${role.toLowerCase()}` : ''
}

// The role's catalog color (modes.ts), or a neutral grey for anything outside the active
// mode's roster - used as the fallback so a stray role id never renders as pure black.
export function roleColor(role: string): string {
  return activeRoleDefinition(role)?.color ?? NEUTRAL_ROLE_COLOR
}

function hexToRgbTriplet(hex: string): string {
  const clean = hex.replace('#', '')
  const r = parseInt(clean.slice(0, 2), 16)
  const g = parseInt(clean.slice(2, 4), 16)
  const b = parseInt(clean.slice(4, 6), 16)
  return `${r}, ${g}, ${b}`
}

// CSS custom properties consumed by styles.css's seat/badge/card rules (--role-color,
// --role-tint, --role-glow, --role-tint-strong) - computed from the catalog hex exactly
// the way the old hardcoded --color-role-{blue,red,judge}-{glow,tint} constants were
// (same alpha steps), so swapping a static class-keyed rule for an inline-bound one
// reproduces identical colors for Blue/Red/Judge. Returns {} for roles outside the active
// mode's roster (e.g. 'Human'/'Chairman') so those elements keep using the CSS rule's own
// fallback instead of being forced into the neutral color.
export function roleColorVars(role: string): Record<string, string> {
  if (!isCouncilRole(role)) return {}
  const color = roleColor(role)
  const rgb = hexToRgbTriplet(color)
  return {
    '--role-color': color,
    '--role-tint': `rgba(${rgb}, 0.1)`,
    '--role-glow': `rgba(${rgb}, 0.35)`,
    '--role-tint-strong': `rgba(${rgb}, 0.55)`,
  }
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
  // Built from councilRoles (not a hardcoded {Blue,Red,Judge} literal) so the model-slot
  // set generalizes to whatever the active mode's roster is - still exactly those three
  // keys today since councilRoles itself is still just red-blue's roster (see modes.ts).
  const selectedModels = ref<Record<CouncilRole, string>>(
    Object.fromEntries(councilRoles.map((role) => [role, ''])),
  )
  const modelTestResults = ref<Record<CouncilRole, ModelTestView>>(
    Object.fromEntries(
      councilRoles.map((role) => [role, { status: 'unknown', testedAt: '', error: '' } satisfies ModelTestView]),
    ),
  )
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
    const result: Record<CouncilRole, MeetingEvent | null> = Object.fromEntries(
      councilRoles.map((role) => [role, null]),
    )
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
      councilRoles.every((role) => selectedModels.value[role]),
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

  // Relay step-progress display (spec.md 16.6: "第 2 步／共 4 步：紅軍質詢中"), derived
  // purely from mode.steps + pendingRoles - display-only, and deliberately does not
  // drive any runtime behavior (see the FIXED_ROUND_STEP_ROLES comment above for why the
  // real queue logic stays independent of this catalog). pendingRoles reflects whichever
  // action queued it (a fresh round, a retried tail, a directed response, a sequence
  // preset) - this only renders when that queue happens to line up with a *suffix* of
  // the mode's full step list. That's always true for a fresh round ("開始審議"/"開始新回合")
  // and for any retry (retrying re-queues the failed step through the end - see
  // retrySelectedStep). It also happens to be true for some directed responses/sequence
  // presets whose roles coincide with a real tail (e.g. a lone Judge directed response,
  // or the "red-blue-judge" preset) - harmless, since the label is accurate in those
  // cases too (that role genuinely is thinking at that point in the flow); a preset like
  // "red-blue" that doesn't match any tail correctly shows nothing instead.
  const currentStepProgress = computed<{ index: number; total: number; label: string } | null>(() => {
    const steps = activeMode.steps
    const pending = pendingRoles.value
    if (activeMode.category !== 'relay' || !steps || !pending.length || pending.length > steps.length) {
      return null
    }
    const startIndex = steps.length - pending.length
    const tailMatches = steps.slice(startIndex).every((step, offset) => step.role === pending[offset])
    if (!tailMatches) return null
    return { index: startIndex + 1, total: steps.length, label: steps[startIndex].label }
  })

  onMounted(async () => {
    await runAction(refreshAll)
  })

  onUnmounted(() => closeEventStream?.())

  async function refreshAll() {
    error.value = ''
    models.value = await getModels()
    meetings.value = await getMeetings()
    const firstModel = models.value[0]?.id ?? ''
    selectedModels.value = Object.fromEntries(
      councilRoles.map((role) => [role, selectedModels.value[role] || firstModel]),
    )
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
    currentStepProgress,
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
