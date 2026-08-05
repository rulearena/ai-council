import { computed, onMounted, onUnmounted, ref, watch, watchEffect, type InjectionKey } from 'vue'
import roleBlueIcon from '../assets/roles/blue.png'
import roleRedIcon from '../assets/roles/red.png'
import roleJudgeIcon from '../assets/roles/judge.png'
import { DEFAULT_MODE_ID, getModeById, refreshModeCatalog, type ModeDefinition, type ModeRoleDefinition } from '../modes'
import { applyModeScene } from '../scenes'
import { roleDisplayName } from '../presentation'
import { canLeaveMeetingSettings } from '../meetingSettingsNavigation'
import { projectOperationStatusText } from '../operationStatus'
import {
  isSameModelAssignment,
  applyOptimisticModelUpdate,
  replaceServerParticipantModels,
} from '../meetingWorkspace'
import {
  bindOldestMatchingCapture,
  createFanoutCapture,
  removeFanoutCapture,
  type FanoutCapture,
} from '../chatroomFanout'
import { waitForSettledProjection } from '../meetingSettlement'
import {
  chatroomStartGuard,
  chairmanActionBlockReason,
  chairmanActionOptions,
  chairmanActionPresentation,
  executeChairmanAction,
  projectFixedRoundFailedRole,
  projectPrimaryAction,
  requestRoleSequenceWithFailureGuard,
  runWithPendingRoles,
  type PrimaryAction,
} from '../chairmanActions'
import {
  ApiError,
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
  sendChatMention,
  sendChatMessage,
  requestRoleSequence,
  reopenMeeting,
  restartDeliberation,
  retryStep,
  runCourtroomFinalVerdict,
  runCourtroomIssueArguments,
  runCourtroomIssueRuling,
  startMeeting,
  subscribeMeetingEvents,
  testModel,
  transcriptDownloadUrl,
  updateMeetingPinned,
  updateMeetingParticipantModels,
  updateMeetingDetails,
  updateMeetingTags,
  type Meeting,
  type MeetingEvent,
  type MeetingParticipant,
  type ModelConfig,
} from '../api'

// A role id as it appears in events.jsonl's `role` field. Used to be a hardcoded
// 'Blue' | 'Red' | 'Judge' union; as of slice B the backend supplies each meeting's
// mode_id and participant roster (spec.md 16.7), and the type stays a plain string so
// seat rendering/pendingRoles/drawers/event bucketing generalize to whichever mode's
// roster the selected meeting actually has (resolved dynamically - see activeModeSource
// below).
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

const ASSIGNMENT_UPDATE_ERROR_MESSAGE = '模型指派儲存失敗，請稍後再試。'

// The mode currently driving the open meeting, defaulting to red-blue when no meeting is
// selected (spec.md 16.7). A module-level singleton (not per-useCouncil() state) so every
// module-level helper below (roleIcon/roleClass/...) and every component's import of
// activeMode/activeModeRoles/councilRoles reads the one true "what's running right now" -
// useCouncil()'s selectedMeeting watcher (see below) is the sole writer. This assumes
// useCouncil() is only ever instantiated once (by App.vue) - a second concurrent instance
// would fight over the same singleton.
const activeModeSource = ref<ModeDefinition>(getModeById(DEFAULT_MODE_ID)!)
const activeRoleSource = ref<ModeRoleDefinition[]>(activeModeSource.value.roles)

// computed(...) wrappers (not activeModeSource itself) so existing `import { activeMode }`
// call sites keep working unchanged in `<template>` (auto-unwrapped) and only need a
// `.value` added where they're read from `<script>`.
export const activeMode = computed(() => activeModeSource.value)

// The active mode's roster (id + kind), for anything that needs to know each role's
// *kind* rather than just its id - currently just CouncilStage.vue, to resolve which
// scene slot (adjudicator/podium/ring) each role occupies (see scenes.ts's
// resolveSceneSeats). Kept as its own export rather than making callers reach into
// modes.ts directly, so there's one place that says "this is the mode running right now".
export const activeModeRoles = computed(() => activeRoleSource.value)

// Every AI role id in the active mode's roster, in display order - replaces the old
// hardcoded `['Blue', 'Red', 'Judge']` literal with whichever roster the active mode
// (see activeModeSource above) actually has.
export const councilRoles = computed<CouncilRole[]>(() => activeRoleSource.value.map((role) => role.id))

// Generic 2-role "auto-continue" presets, derived from the active mode's roster rather
// than red-blue's three role ids: `members` is every `kind: 'member'` role (relay's two
// peers), `adjudicator` is the first non-member role (relay's decision-maker). For
// red-blue this produces the exact same four presets slice A hand-wrote (members
// [Blue, Red], adjudicator Judge) - just under generic ids or a role-list roster of
// fewer than 2 members can't build a meaningful "swap order" preset.
export const sequencePresets = computed<SequencePreset[]>(() => {
  const mode = activeModeSource.value
  if (mode.category !== 'relay') return []
  const members = mode.roles.filter((role) => role.kind === 'member').map((role) => role.id)
  const adjudicator = mode.roles.find((role) => role.kind !== 'member')?.id
  if (!adjudicator || members.length < 2) return []
  const reversed = [...members].reverse()
  const presentationParticipants = activeRoleSource.value.map((role) => ({
    role_id: role.id,
    display_name: role.name,
  }))
  const label = (roles: string[]) =>
    roles.map((role) => roleDisplayName(mode, presentationParticipants, role)).join(' → ')
  const adjudicatorName = roleDisplayName(mode, presentationParticipants, adjudicator)
  return [
    { id: 'members-reversed-adj', label: label([...reversed, adjudicator]), roles: [...reversed, adjudicator] },
    { id: 'members-adj', label: label([...members, adjudicator]), roles: [...members, adjudicator] },
    { id: 'members-reversed', label: label(reversed), roles: reversed },
    { id: 'adj-only', label: `只請${adjudicatorName}`, roles: [adjudicator] },
  ]
})

// The active mode's step_ids, in order (backend/ai_council/meetings/modes.py's
// relay_plan: step_id = template name with `_` -> `-` - see docs/plans/2026-07-12-
// mode-system-slice-b.md's naming convention). Derived from catalog data (not
// hand-written per mode) now that the backend itself is mode-driven as of slice B, so
// this tracks whichever mode is actually running instead of assuming red-blue's four
// steps.
const roundBaseSteps = computed(() =>
  (activeModeSource.value.steps ?? []).map((step) => step.template.replace(/_/g, '-')),
)

// Retrying a failed step re-runs it plus every step after it in the same round (backend's
// retry_failed_step - see runner.py). baseStepId is the failed event's base_step_id/
// step_id; this returns that step's role plus every subsequent step's role, in the
// active mode's step order. Falls back to just the failed role itself for a base_step_id
// outside the round's steps (e.g. a directed/sequence response's own step_id).
function retryCascadeRoles(baseStepId: string): CouncilRole[] {
  const steps = activeModeSource.value.steps ?? []
  const index = roundBaseSteps.value.indexOf(baseStepId)
  if (index < 0) return []
  return steps.slice(index).map((step) => step.role)
}

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
  return activeModeSource.value.roles.find((candidate) => candidate.id === role)
}

export function isCouncilRole(role: string): role is CouncilRole {
  return councilRoles.value.includes(role)
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

// The mode a given meeting resolves to (or the default mode for no meeting/an unknown
// mode_id) - shared by the two watchers below so both agree on "what mode is this" without
// one depending on the other having already run (see the scene-override watcher's comment
// for why that independence matters).
function resolveActiveMode(meeting: Meeting | null): ModeDefinition {
  return getModeById(meeting?.mode_id ?? DEFAULT_MODE_ID) ?? getModeById(DEFAULT_MODE_ID)!
}

function participantToRoleDefinition(participant: MeetingParticipant): ModeRoleDefinition {
  return {
    id: participant.role_id,
    name: participant.display_name || participant.name,
    color: participant.color,
    portrait: participant.portrait ?? undefined,
    kind: participant.kind as ModeRoleDefinition['kind'],
  }
}

export function useCouncil() {
  const models = ref<ModelConfig[]>([])
  const meetings = ref<Meeting[]>([])
  const selectedMeeting = ref<Meeting | null>(null)
  const selectedEvent = ref<MeetingEvent | null>(null)
  const title = ref('')
  const goal = ref('')
  // Populated by the councilRoles watcher below - the roster (and therefore which keys
  // these need) now changes whenever the selected meeting's mode does, not just once at
  // startup.
  const selectedModels = ref<Record<CouncilRole, string>>({})
  const modelTestResults = ref<Record<CouncilRole, ModelTestView>>({})
  const chairMessage = ref('')
  const chairmanAction = ref('note')
  const chairmanActionFeedback = ref('')
  const selectedSequencePresetId = ref(sequencePresets.value[0]?.id ?? '')
  const meetingSearch = ref('')
  const statusFilter = ref<'all' | Meeting['status']>('all')
  const transcriptSearchQuery = ref('')
  const transcriptSearchResults = ref<Meeting[] | null>(null)
  const transcript = ref('')
  const loading = ref(false)
  const error = ref('')
  const meetingCreationError = ref('')
  const assignmentUpdateError = ref('')
  const devMode = ref(false)
  let closeEventStream: (() => void) | null = null
  let assignmentSaveGeneration = 0
  let meetingSelectionGeneration = 0
  let meetingOutputGeneration = 0
  let meetingSettlementGeneration = 0

  // event_ids this session has already processed for the currently-open meeting - lets
  // the WS handler tell a genuinely new event apart from one merely being resent (every
  // reconnect's first message is a snapshot of the active deliberation, see
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
  const fanoutCaptures = ref<FanoutCapture[]>([])

  const meetingInfoCopied = ref(false)
  let meetingInfoCopiedTimeout: ReturnType<typeof setTimeout> | null = null

  // Briefly true right after a chair message is sent, so the Chairman seat can pop a
  // speech bubble even though the backend has no "speaking" concept of its own.
  const chairmanSpeaking = ref(false)
  let chairmanSpeakingTimeout: ReturnType<typeof setTimeout> | null = null

  // Drives activeModeSource (module-level, see top of file) from whichever meeting is
  // currently selected - the whole point of slice B's mode system: the active mode
  // follows the open meeting instead of being a fixed red-blue constant. `watchEffect`
  // (not `watch(selectedMeeting, ...)`) on purpose: it also re-reads `getModeById` after
  // `refreshModeCatalog()` (called from refreshAll() on mount, further down) replaces
  // modeCatalog's contents (a `splice`, tracked the same way `selectedMeeting` is), so a
  // mode fetched from the backend after this effect's first run still gets picked up - a
  // plain `watch(selectedMeeting, ...)` would only re-run on a meeting change and could
  // stay stuck on the local fallback mode object. No meeting selected (back at the list)
  // falls back to DEFAULT_MODE_ID, same as before any meeting is ever opened.
  watchEffect(() => {
    activeModeSource.value = resolveActiveMode(selectedMeeting.value)
    activeRoleSource.value = selectedMeeting.value
      ? selectedMeeting.value.participants.map(participantToRoleDefinition)
      : activeModeSource.value.roles
  })

  // Applies (spec.md 16.7) the resolved mode's default_scene as a non-persisted scene
  // override (see scenes.ts's applyModeScene) - deliberately a *separate* watcher from the
  // activeModeSource one above, keyed on a `${meeting_id}::${defaultScene}` string rather
  // than `selectedMeeting` itself. `selectedMeeting.value` gets reassigned to a brand-new
  // object on every websocket event/run-start/openMeeting call while staying the *same*
  // meeting (see e.g. the WS handler and openMeeting further down) - a watcher keyed on
  // the ref (or on a freshly-built tuple/array, which Vue also treats as a new identity
  // every run) would re-fire on every one of those and reapply default_scene each time,
  // silently stomping a scene the user just picked manually in Settings mid-meeting. A
  // primitive string key only changes value when the meeting identity or its mode's
  // default_scene actually changes, so the override is (re-)applied exactly on a genuine
  // meeting switch (reopening it after switching away included) and left alone otherwise -
  // matching setScene's "manual pick wins for the rest of this meeting" contract.
  const sceneOverrideKey = computed(() => {
    const meeting = selectedMeeting.value
    return meeting ? `${meeting.meeting_id}::${meeting.scene || resolveActiveMode(meeting).defaultScene}` : null
  })
  watch(sceneOverrideKey, () => {
    const meeting = selectedMeeting.value
    applyModeScene(meeting ? meeting.scene || resolveActiveMode(meeting).defaultScene : null)
  })

  // The open meeting projection is authoritative. With no meeting selected, seed the
  // inactive stage from the first configured model only so its controls remain usable.
  watch(
    [councilRoles, models],
    ([roles]) => {
      const firstModel = models.value[0]?.id ?? ''
      selectedModels.value = Object.fromEntries(
        roles.map((role) => [
          role,
          selectedMeeting.value?.participants.find((participant) => participant.role_id === role)
            ?.model_config_id ?? firstModel,
        ]),
      )
      modelTestResults.value = Object.fromEntries(
        roles.map((role) => [
          role,
          modelTestResults.value[role] ?? ({ status: 'unknown', testedAt: '', error: '' } satisfies ModelTestView),
        ]),
      )
    },
    { immediate: true },
  )

  const events = computed(() => selectedMeeting.value?.events ?? [])
  const terminalMeetingStatus = computed<'closed' | 'cancelled' | null>(() => {
    const lifecycleEvent = [...events.value]
      .reverse()
      .find((event) => ['closed', 'cancelled', 'reopened'].includes(event.status))
    return lifecycleEvent?.status === 'closed' || lifecycleEvent?.status === 'cancelled'
      ? lifecycleEvent.status
      : null
  })
  const isTerminalMeeting = computed(() => terminalMeetingStatus.value !== null)
  const isMeetingRunning = computed(() => selectedMeeting.value?.activity_status === 'running')
  // A failed role step must be retried before any new AI batch. The backend cannot
  // advance that fixed round through generic /start, so every AI composer path shares
  // this gate while plain chairman notes remain available.
  const failedRole = computed<CouncilRole | null>(() => projectFixedRoundFailedRole(
    activeMode.value.steps ?? [],
    events.value,
  ))
  const primaryAction = computed<PrimaryAction>(() => projectPrimaryAction({
    modeId: selectedMeeting.value?.mode_id ?? activeMode.value.id,
    steps: activeMode.value.steps ?? [],
    participants: selectedMeeting.value?.participants ?? [],
    events: events.value,
    courtroom: selectedMeeting.value?.courtroom ?? null,
  }))
  const chairmanOptions = computed(() => chairmanActionOptions({
    modeId: selectedMeeting.value?.mode_id ?? activeMode.value.id,
    modeCategory: activeMode.value.category,
    participants: selectedMeeting.value?.participants ?? [],
    courtroom: selectedMeeting.value?.courtroom ?? null,
    nextActionLabel: primaryAction.value.label,
    failedRole: failedRole.value,
  }))
  watch(chairmanOptions, (options) => {
    if (!options.some((option) => option.value === chairmanAction.value)) {
      chairmanAction.value = options[0]?.value ?? 'note'
    }
  }, { immediate: true })
  const chairmanPresentation = computed(() => chairmanActionPresentation(
    chairmanAction.value,
    selectedMeeting.value?.participants ?? [],
    selectedMeeting.value?.mode_id ?? activeMode.value.id,
  ))
  const startButtonLabel = computed(() => isMeetingRunning.value ? '執行中…' : primaryAction.value.label)
  const selectedSequencePreset = computed(
    () =>
      sequencePresets.value.find((preset) => preset.id === selectedSequencePresetId.value) ??
      sequencePresets.value[0],
  )
  const operationStatus = computed(() => {
    if (loading.value) return 'running'
    return selectedMeeting.value?.activity_status ?? 'idle'
  })
  const operationStatusText = computed(() => projectOperationStatusText(
    operationStatus.value,
    selectedMeeting.value?.mode_id === 'courtroom'
      ? selectedMeeting.value.courtroom ?? null
      : null,
    terminalMeetingStatus.value,
  ))
  const filteredMeetings = computed(() => {
    const query = meetingSearch.value.trim().toLowerCase()
    return meetings.value
      .filter((meeting) => {
        const matchesStatus = statusFilter.value === 'all' || meeting.status === statusFilter.value
        const searchable = `${meeting.title} ${meeting.meeting_id} ${meeting.last_step_id ?? ''} ${meeting.tags.join(' ')}`.toLowerCase()
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
      councilRoles.value.map((role) => [role, null]),
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
    if (!roundEvents.length || !roundBaseSteps.value.length) return false
    const latestRound = Math.max(...roundEvents.map((event) => event.round ?? 1))
    return roundBaseSteps.value.every((baseStepId) =>
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
      !selectedMeeting.value.requires_goal &&
      !isTerminalMeeting.value &&
      !isMeetingRunning.value &&
      councilRoles.value.every((role) => selectedModels.value[role]),
  )
  // Relay step-progress display (spec.md 16.6: "第 2 步／共 4 步：紅軍質詢中"), derived
  // purely from mode.steps + pendingRoles - display-only, and deliberately does not
  // drive any runtime behavior (the actual queue logic - applyPendingRoleUpdates et al -
  // stays independent of this catalog read). pendingRoles reflects whichever action
  // queued it (a fresh round, a retried tail, a directed response, a sequence preset) -
  // this only renders when that queue happens to line up with a *suffix* of the mode's
  // full step list. That's always true for a fresh round ("開始審議"/"開始新回合") and for
  // any retry (retrying re-queues the failed step through the end - see
  // retrySelectedStep). It also happens to be true for some directed responses/sequence
  // presets whose roles coincide with a real tail (e.g. a lone adjudicator directed
  // response, or the "members-reversed-adj" preset) - harmless, since the label is
  // accurate in those cases too (that role genuinely is thinking at that point in the
  // flow); a preset like "members-reversed" that doesn't match any tail correctly shows
  // nothing instead.
  const currentStepProgress = computed<{ index: number; total: number; label: string } | null>(() => {
    const steps = activeMode.value.steps
    const pending = pendingRoles.value
    if (activeMode.value.category !== 'relay' || !steps || !pending.length || pending.length > steps.length) {
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

  // Re-fetches the model list and lets the [councilRoles, models] watcher above (re-)sync
  // selectedModels/modelTestResults against it - the sole GET /models call site, reused by
  // both startup (refreshAll) and ModelManagerPanel after a create/update/delete
  // so a freshly added/removed model shows up in the role dropdowns without a page reload.
  async function refreshModels(shouldCommit: () => boolean = () => true) {
    const refreshedModels = await getModels()
    if (!shouldCommit()) return
    models.value = refreshedModels
    const meetingId = selectedMeeting.value?.meeting_id
    if (meetingId) {
      const refreshedMeeting = await getMeeting(meetingId)
      if (!shouldCommit() || selectedMeeting.value?.meeting_id !== meetingId) return
      selectedMeeting.value = refreshedMeeting
      selectedModels.value = Object.fromEntries(
        refreshedMeeting.participants.map((participant) => [
          participant.role_id,
          participant.model_config_id ?? '',
        ]),
      )
    }
  }

  async function refreshAll() {
    error.value = ''
    // Failure here doesn't block startup - refreshModeCatalog() already catches and
    // leaves modeCatalog on its local fallback data (see modes.ts), so the rest of
    // refreshAll proceeds exactly as it would if the backend catalog had loaded.
    await refreshModeCatalog()
    await refreshModels()
    meetings.value = await getMeetings()
    if (selectedMeeting.value) {
      await openMeeting(selectedMeeting.value.meeting_id)
    }
  }

  // NewCaseModal passes the user's actual mode picker choice (selectedMode.id) and the
  // participants step's input form values here. modeId/inputs still default to
  // red-blue/{} as a defensive fallback for any other/future call site that omits them,
  // not because anything live still relies on that default.
  async function createNewMeeting(
    modeId: string = DEFAULT_MODE_ID,
    inputs: Record<string, string> = {},
    participants: Array<{
      role_id: string
      model_config_id?: string | null
      display_name?: string | null
      instance_prompt?: string | null
    }> = [],
    caseFiles: Array<{
      title: string
      content: string
      visible_roles: string[]
    }> = [],
    caseType?: 'civil' | 'criminal',
  ) {
    loading.value = true
    error.value = ''
    meetingCreationError.value = ''
    try {
      const meeting = await createMeeting(title.value, goal.value, {
        modeId,
        inputs,
        participants,
        caseFiles,
        caseType,
      })
      meetings.value = await getMeetings()
      await openMeeting(meeting.meeting_id)
      return true
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
      meetingCreationError.value =
        caught instanceof ApiError && typeof caught.detail === 'string'
          ? caught.detail
          : error.value
      return false
    } finally {
      loading.value = false
    }
  }

  function clearMeetingCreationError() {
    meetingCreationError.value = ''
  }

  async function openMeeting(meetingId: string) {
    ++meetingSettlementGeneration
    const selectionGeneration = ++meetingSelectionGeneration
    ++meetingOutputGeneration
    // Only reset the queue when actually switching meetings. requestSelectedRoleResponse /
    // requestSelectedRoleSequence / retrySelectedStep call openMeeting on the SAME meeting
    // right after enqueuing roles, so clearing unconditionally would erase what was just pushed.
    if (meetingId !== selectedMeeting.value?.meeting_id) {
      if (!canLeaveMeetingSettings()) return false
      pendingRoles.value = []
      fanoutCaptures.value = []
      meetingInfoCopied.value = false
      chairmanActionFeedback.value = ''
      seenEventIds = new Set()
    }
    const meeting = await getMeeting(meetingId)
    if (selectionGeneration !== meetingSelectionGeneration) return false
    selectedMeeting.value = meeting
    assignmentUpdateError.value = ''
    selectedModels.value = Object.fromEntries(
      selectedMeeting.value.participants.map((participant) => [
        participant.role_id,
        participant.model_config_id ?? '',
      ]),
    )
    selectedEvent.value = selectedMeeting.value.events?.at(-1) ?? null
    const outputGeneration = ++meetingOutputGeneration
    const refreshedTranscript = await getTranscript(meetingId)
    if (
      selectionGeneration !== meetingSelectionGeneration ||
      outputGeneration !== meetingOutputGeneration ||
      selectedMeeting.value?.meeting_id !== meetingId
    ) return false
    transcript.value = refreshedTranscript
    connectMeetingEvents(meetingId)
    return true
  }

  async function updateSelectedMeetingDetails(nextTitle: string, nextGoal: string) {
    if (!selectedMeeting.value || !nextTitle.trim() || !nextGoal.trim()) return false
    if (isMeetingRunning.value) return false
    const previousMeeting = selectedMeeting.value
    const goalChanged = nextGoal.trim() !== previousMeeting.goal
    if (
      goalChanged &&
      previousMeeting.mode_id === 'courtroom' &&
      previousMeeting.courtroom?.status === 'confirmed'
    ) return false
    const hasAiOutput = events.value.some((event) =>
      !['Human', 'System'].includes(event.role) && event.status === 'completed',
    )
    if (
      goalChanged &&
      hasAiOutput &&
      !window.confirm('修改目標只會影響後續 AI 回應，既有發言不會重新產生。確定修改？')
    ) return false
    const meetingId = selectedMeeting.value.meeting_id
    return runAction(async () => {
      await updateMeetingDetails(meetingId, nextTitle.trim(), nextGoal.trim())
      selectedMeeting.value = await getMeeting(meetingId)
      meetings.value = await getMeetings()
    })
  }

  function clearContinueHint() {
    chairmanActionFeedback.value = ''
  }

  // The action bar consumes one explicit projection for both its label and behavior.
  // A completed ordinary round starts a new fixed round; courtroom actions always use
  // their dedicated issue endpoint and can never fall through to generic /start.
  async function startOrContinueMeeting() {
    await executePrimaryAction()
  }

  async function executePrimaryAction(): Promise<boolean> {
    if (!selectedMeeting.value || !canRun.value || primaryAction.value.disabled) return false
    if (primaryAction.value.kind === 'start-round') {
      return startSelectedMeeting()
    }
    const meetingId = selectedMeeting.value.meeting_id
    const action = primaryAction.value
    if (action.kind === 'courtroom-retry' && action.stepId) {
      const failed = [...events.value].reverse().find(
        (event) => event.step_id === action.stepId && event.status === 'failed',
      )
      return failed ? retrySelectedStep(failed) : false
    }
    const queuedRoles = action.kind === 'courtroom-arguments'
      ? ['Prosecutor', 'Defense', 'Prosecutor']
      : ['Judge']
    return runWithPendingRoles(pendingRoles.value, queuedRoles, () => {
      connectMeetingEvents(meetingId)
      return runAction(async () => {
        if (action.kind === 'courtroom-arguments' && action.issueId) {
          await runCourtroomIssueArguments(meetingId, action.issueId)
        } else if (action.kind === 'courtroom-ruling' && action.issueId) {
          await runCourtroomIssueRuling(meetingId, action.issueId)
        } else if (action.kind === 'courtroom-final') {
          await runCourtroomFinalVerdict(meetingId)
        }
        if (selectedMeeting.value?.meeting_id === meetingId) {
          selectedMeeting.value = { ...selectedMeeting.value, activity_status: 'running' }
        }
        void refreshMeetingUntilSettled(meetingId)
      })
    })
  }

  async function startSelectedMeeting(): Promise<boolean> {
    if (!selectedMeeting.value || !canRun.value) return false
    if (chatroomStartGuard(activeModeSource.value.category)) return false
    clearContinueHint()
    const meetingId = selectedMeeting.value.meeting_id
    // The active mode's full step roster, in order (was a literal ['Blue','Red','Blue',
    // 'Judge']) - a round always runs every step, so this is roundBaseSteps' roles, not
    // just retryCascadeRoles' tail.
    const queuedRoles =
      activeModeSource.value.category === 'parallel'
        ? [
            ...activeModeRoles.value.filter((role) => role.kind === 'member').map((role) => role.id),
            ...activeModeRoles.value.filter((role) => role.kind === 'synthesizer').map((role) => role.id),
          ]
        : (activeModeSource.value.steps ?? []).map((step) => step.role)
    return runWithPendingRoles(pendingRoles.value, queuedRoles, () => {
      connectMeetingEvents(meetingId)
      return runAction(async () => {
        await startMeeting(meetingId)
        if (selectedMeeting.value?.meeting_id === meetingId) {
          selectedMeeting.value = { ...selectedMeeting.value, activity_status: 'running' }
        }
        void refreshMeetingUntilSettled(meetingId)
      })
    })
  }

  function connectMeetingEvents(meetingId: string) {
    closeEventStream?.()
    closeEventStream = subscribeMeetingEvents(
      meetingId,
      (message) => {
        if (selectedMeeting.value?.meeting_id !== meetingId) return
        const currentEvents = message.type === 'snapshot' ? [] : (selectedMeeting.value.events ?? [])
        for (const event of message.events) {
          fanoutCaptures.value = bindOldestMatchingCapture(fanoutCaptures.value, event)
        }
        const nextEvents = [...currentEvents, ...message.events]
        const latestEvent = nextEvents.at(-1)
        selectedMeeting.value = {
          ...selectedMeeting.value,
          events: nextEvents,
          activity_status: message.activity_status,
          last_step_id: latestEvent?.step_id ?? null,
          updated_at: latestEvent?.created_at ?? selectedMeeting.value.updated_at,
        }
        // A reconnect's "snapshot" resends the active deliberation (not just what
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
        error.value = '會議事件串流已中斷。'
        pendingRoles.value = []
        // A provisional capture has no durable identity. Dropping it on disconnect
        // forces the next snapshot to project only events that actually survived in
        // the append-only log, so client-only placeholders cannot live forever.
        fanoutCaptures.value = []
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
        if (activeModeSource.value.category === 'chatroom' && event.step_id.startsWith('chat-fanout-')) {
          pendingRoles.value.splice(queueIndex, 1)
          continue
        }
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
    const generation = ++meetingOutputGeneration
    try {
      const refreshedTranscript = await getTranscript(meetingId)
      if (generation !== meetingOutputGeneration || selectedMeeting.value?.meeting_id !== meetingId) return
      transcript.value = refreshedTranscript
      if (activityStatus !== 'running') {
        const refreshedMeeting = await getMeeting(meetingId)
        if (generation !== meetingOutputGeneration || selectedMeeting.value?.meeting_id !== meetingId) return
        selectedMeeting.value = refreshedMeeting
        const refreshedMeetings = await getMeetings()
        if (generation !== meetingOutputGeneration || selectedMeeting.value?.meeting_id !== meetingId) return
        meetings.value = refreshedMeetings
      }
    } catch (caught) {
      if (generation !== meetingOutputGeneration || selectedMeeting.value?.meeting_id !== meetingId) return
      error.value = caught instanceof Error ? caught.message : String(caught)
    }
  }

  async function refreshMeetingUntilSettled(meetingId: string) {
    // Completion events can be broadcast while the backend job still owns its running
    // slot. Poll the read projection until that slot is released so workflow-only
    // fields (courtroom status/actions/rulings) become visible without a page reload.
    const settlementGeneration = ++meetingSettlementGeneration
    const isCurrent = () => (
      settlementGeneration === meetingSettlementGeneration &&
      selectedMeeting.value?.meeting_id === meetingId
    )
    try {
      const refreshed = await waitForSettledProjection({
        load: () => getMeeting(meetingId),
        wait: () => new Promise((resolve) => setTimeout(resolve, 250)),
        isCurrent,
      })
      if (!refreshed || !isCurrent()) return
      selectedMeeting.value = refreshed
      const generation = ++meetingOutputGeneration
      const refreshedTranscript = await getTranscript(meetingId)
      if (generation !== meetingOutputGeneration || !isCurrent()) return
      transcript.value = refreshedTranscript
      const refreshedMeetings = await getMeetings()
      if (generation !== meetingOutputGeneration || !isCurrent()) return
      meetings.value = refreshedMeetings
    } catch (caught) {
      if (!isCurrent()) return
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

  async function reopenSelectedMeeting() {
    if (!selectedMeeting.value) return
    if (!window.confirm('確定重新開啟這場會議？')) return
    await runAction(async () => {
      await reopenMeeting(selectedMeeting.value!.meeting_id)
      await openMeeting(selectedMeeting.value!.meeting_id)
    })
  }

  async function restartSelectedDeliberation(
    scope: 'current_issue' | 'all_deliberation' | 'rebuild_issues',
    reason: string,
    selectedIssueId?: string,
  ): Promise<boolean> {
    if (!selectedMeeting.value || !reason.trim() || isMeetingRunning.value || isTerminalMeeting.value) return false
    const meetingId = selectedMeeting.value.meeting_id
    const issueId = scope === 'current_issue'
      ? selectedIssueId || selectedMeeting.value.courtroom?.current_issue_id || undefined
      : undefined
    if (scope === 'current_issue' && !issueId) return false
    return runAction(async () => {
      await restartDeliberation(meetingId, scope, reason.trim(), issueId)
      await openMeeting(meetingId)
      meetings.value = await getMeetings()
    })
  }

  async function deleteExistingMeeting(meeting: Meeting) {
    if (!window.confirm(`確定刪除「${meeting.title}」？此操作無法復原。`)) return
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

  async function updateSelectedModel(role: CouncilRole, modelId: string) {
    if (isSameModelAssignment(selectedModels.value, role, modelId)) return
    if (!selectedMeeting.value) {
      selectedModels.value = applyOptimisticModelUpdate(selectedModels.value, role, modelId)
      return
    }
    const meetingId = selectedMeeting.value.meeting_id
    const requestGeneration = ++assignmentSaveGeneration
    const previous = { ...selectedModels.value }
    const next = applyOptimisticModelUpdate(selectedModels.value, role, modelId)
    selectedModels.value = next
    assignmentUpdateError.value = ''
    loading.value = true
    try {
      const meeting = await updateMeetingParticipantModels(
        meetingId,
        next,
      )
      if (requestGeneration !== assignmentSaveGeneration) return
      meetings.value = meetings.value.map((candidate) =>
        candidate.meeting_id === meetingId
          ? {
              ...candidate,
              ...meeting,
              events: candidate.events,
              case_files: candidate.case_files,
            }
          : candidate,
      )
      if (selectedMeeting.value?.meeting_id !== meetingId) return
      selectedMeeting.value = {
        ...selectedMeeting.value,
        ...meeting,
        events: selectedMeeting.value.events,
        case_files: selectedMeeting.value.case_files,
      }
      selectedModels.value = replaceServerParticipantModels(
        selectedModels.value,
        meeting.participants,
      )
    } catch {
      if (
        requestGeneration !== assignmentSaveGeneration ||
        selectedMeeting.value?.meeting_id !== meetingId
      ) {
        return
      }
      selectedModels.value = previous
      assignmentUpdateError.value = ASSIGNMENT_UPDATE_ERROR_MESSAGE
    } finally {
      if (requestGeneration === assignmentSaveGeneration) loading.value = false
    }
  }

  async function sendChairMessage(): Promise<boolean> {
    if (!selectedMeeting.value || !chairMessage.value.trim()) return false
    const succeeded = await runAction(async () => {
      await addMeetingMessage(selectedMeeting.value!.meeting_id, chairMessage.value.trim())
      chairMessage.value = ''
      await openMeeting(selectedMeeting.value!.meeting_id)
      chairmanSpeaking.value = true
      if (chairmanSpeakingTimeout) clearTimeout(chairmanSpeakingTimeout)
      chairmanSpeakingTimeout = setTimeout(() => {
        chairmanSpeaking.value = false
      }, 2500)
    })
    return succeeded
  }

  async function submitChairmanAction(): Promise<boolean> {
    const content = chairMessage.value.trim()
    if (!selectedMeeting.value || !content || isMeetingRunning.value || isTerminalMeeting.value) return false
    chairmanActionFeedback.value = ''
    const blockedReason = chairmanActionBlockReason(
      chairmanAction.value,
      failedRole.value,
      selectedMeeting.value.participants,
    )
    if (blockedReason) {
      chairmanActionFeedback.value = blockedReason
      return false
    }
    const succeeded = await executeChairmanAction(chairmanAction.value, content, {
      appendNote: () => sendChairMessage(),
      requestAll: () => executePrimaryAction(),
      requestRole: (role, instruction) => requestSelectedRoleResponse(role, instruction),
    })
    if (succeeded && chairmanAction.value.startsWith('role:')) chairMessage.value = ''
    if (succeeded) chairmanActionFeedback.value = chairmanPresentation.value.successMessage
    return succeeded
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

  async function requestSelectedRoleResponse(role: CouncilRole, instruction: string) {
    if (!selectedMeeting.value || !canRun.value || !instruction.trim()) return false
    const blockedReason = chairmanActionBlockReason(
      `role:${role}`,
      failedRole.value,
      selectedMeeting.value.participants,
    )
    if (blockedReason) {
      error.value = blockedReason
      chairmanActionFeedback.value = blockedReason
      return false
    }
    clearContinueHint()
    const meetingId = selectedMeeting.value.meeting_id
    return runWithPendingRoles(pendingRoles.value, [role], () => runAction(async () => {
      await requestRoleResponse(meetingId, role, instruction.trim())
      await openMeeting(meetingId)
      void refreshMeetingUntilSettled(meetingId)
    }))
  }

  // The chatroom composer used to call the API modules directly, which meant its
  // sends never touched pendingRoles — so a mentioned role showed no thinking bubble
  // and no seat pulse, and the Chairman had no way to tell whether anything was
  // happening. Routing through here gives chatroom the same in-progress feedback
  // relay and parallel already had.
  //
  // Deliberately no openMeeting()/refresh here: the live event stream already delivers
  // the new events. Re-opening the meeting mid-send re-renders the workspace and wipes
  // the composer's own draft state, which left the send button disabled on the next
  // message.
  async function sendChatroomMessage(
    meetingId: string,
    content: string,
    quotedEventId?: string,
  ): Promise<boolean> {
    return runAction(async () => {
      await sendChatMessage(meetingId, content, quotedEventId)
    })
  }

  async function sendChatroomMention(
    meetingId: string,
    content: string,
    mentions: string[],
    quotedEventId?: string,
  ): Promise<boolean> {
    // '@all' resolves to every participant so each seat reports its own progress.
    const queuedRoles = mentions.includes('all')
      ? (selectedMeeting.value?.participants ?? []).map((participant) => participant.role_id)
      : mentions
    const capture = mentions.includes('all')
      ? createFanoutCapture({
        meetingId,
        instruction: content,
        preSendEventIds: (selectedMeeting.value?.events ?? []).map((event) => event.event_id),
        expectedRoleIds: (selectedMeeting.value?.participants ?? []).map((participant) => participant.role_id),
      })
      : null
    if (capture) fanoutCaptures.value = [...fanoutCaptures.value, capture]
    try {
      const succeeded = await runWithPendingRoles(pendingRoles.value, queuedRoles, () => runAction(async () => {
        await sendChatMention(meetingId, content, mentions, quotedEventId)
      }))
      if (!succeeded && capture) fanoutCaptures.value = removeFanoutCapture(fanoutCaptures.value, capture.id)
      return succeeded
    } catch (error) {
      if (capture) fanoutCaptures.value = removeFanoutCapture(fanoutCaptures.value, capture.id)
      throw error
    }
  }

  async function requestSelectedRoleSequence(): Promise<boolean> {
    // selectedSequencePreset can be undefined when the active mode's roster can't build
    // any presets (fewer than 2 members, or no adjudicator - see sequencePresets above,
    // which returns []). Parallel modes deliberately have no sequence presets, so guard
    // against the TypeError up front.
    if (!selectedMeeting.value || !canRun.value || !selectedSequencePreset.value) return false
    const meetingId = selectedMeeting.value.meeting_id
    const roles = [...selectedSequencePreset.value.roles]
    clearContinueHint()
    return requestRoleSequenceWithFailureGuard({
      failedRole: failedRole.value,
      participants: selectedMeeting.value.participants,
      pendingRoles: pendingRoles.value,
      queuedRoles: roles,
      onBlocked: (reason) => {
        error.value = reason
        chairmanActionFeedback.value = reason
      },
      request: () => runAction(async () => {
        await requestRoleSequence(meetingId, roles)
        await openMeeting(meetingId)
        void refreshMeetingUntilSettled(meetingId)
      }),
    })
  }

  async function retrySelectedStep(event: MeetingEvent): Promise<boolean> {
    if (!selectedMeeting.value || !canRun.value || event.status !== 'failed') return false
    clearContinueHint()
    const baseStepId = event.base_step_id ?? event.step_id
    const cascade = retryCascadeRoles(baseStepId)
    const remainingRoles = cascade.length ? cascade : isCouncilRole(event.role) ? [event.role] : []
    const meetingId = selectedMeeting.value.meeting_id
    return runWithPendingRoles(
      pendingRoles.value,
      remainingRoles,
      () => runAction(async () => {
        await retryStep(meetingId, event.step_id)
        await openMeeting(meetingId)
        void refreshMeetingUntilSettled(meetingId)
      }),
    )
  }

  async function copyMeetingInfo(meeting: Meeting) {
    try {
      await navigator.clipboard.writeText(`${meeting.title}\n會議 ID：${meeting.meeting_id}`)
      meetingInfoCopied.value = true
      if (meetingInfoCopiedTimeout) clearTimeout(meetingInfoCopiedTimeout)
      meetingInfoCopiedTimeout = setTimeout(() => {
        meetingInfoCopied.value = false
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

  async function runAction(action: () => Promise<void>): Promise<boolean> {
    loading.value = true
    error.value = ''
    try {
      await action()
      return true
    } catch (caught) {
      error.value = caught instanceof ApiError && typeof caught.detail === 'string'
        ? caught.detail
        : caught instanceof Error ? caught.message : String(caught)
      return false
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
    title,
    goal,
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
    meetingCreationError,
    assignmentUpdateError,
    devMode,
    pendingRoles,
    fanoutCaptures,
    meetingInfoCopied,
    chairmanSpeaking,
    chairmanAction,
    chairmanActionFeedback,
    // computed
    events,
    isTerminalMeeting,
    isMeetingRunning,
    startButtonLabel,
    chairmanOptions,
    chairmanPresentation,
    primaryAction,
    selectedSequencePreset,
    operationStatus,
    operationStatusText,
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
    refreshModels,
    createNewMeeting,
    clearMeetingCreationError,
    openMeeting,
    refreshMeetingUntilSettled,
    updateSelectedMeetingDetails,
    startSelectedMeeting,
    startOrContinueMeeting,
    cancelSelectedMeeting,
    closeSelectedMeeting,
    reopenSelectedMeeting,
    restartSelectedDeliberation,
    deleteExistingMeeting,
    editMeetingTags,
    toggleMeetingPinned,
    searchTranscripts,
    testSelectedModel,
    updateSelectedModel,
    sendChairMessage,
    submitChairmanAction,
    correctSelectedMessage,
    requestSelectedRoleResponse,
    sendChatroomMessage,
    sendChatroomMention,
    requestSelectedRoleSequence,
    retrySelectedStep,
    copyMeetingInfo,
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
