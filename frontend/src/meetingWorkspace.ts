import type { FanoutCapture } from './chatroomFanout'

export type MeetingSettingsSource = {
  meeting_id: string
  title: string
  goal: string | null
  settings_revision: number
  scene: string
  mode_id: string
  case_type?: 'civil' | 'criminal' | null
  courtroom?: { status: string } | null
  participants: Array<{ role_id: string; model_config_id: string | null }>
}

export type MeetingSettingsDraft = {
  meetingId: string
  expectedRevision: number
  title: string
  goal: string
  caseType: 'civil' | 'criminal' | null
  scene: string
  participantModels: Record<string, string>
}

export type MeetingSettingsErrors = {
  title: string
  goal: string
  caseType: string
}

export function hydrateMeetingSettingsDraft(meeting: MeetingSettingsSource): MeetingSettingsDraft {
  return {
    meetingId: meeting.meeting_id,
    expectedRevision: meeting.settings_revision,
    title: meeting.title,
    goal: meeting.goal ?? '',
    caseType: meeting.mode_id === 'courtroom' ? meeting.case_type ?? null : null,
    scene: meeting.scene,
    participantModels: Object.fromEntries(
      meeting.participants.map((participant) => [
        participant.role_id,
        participant.model_config_id ?? '',
      ]),
    ),
  }
}

export function buildMeetingSettingsPayload(draft: MeetingSettingsDraft) {
  return {
    expected_revision: draft.expectedRevision,
    title: draft.title.trim(),
    goal: draft.goal.trim(),
    case_type: draft.caseType,
    scene: draft.scene,
    participant_models: { ...draft.participantModels },
  }
}

export function isMeetingSettingsDirty(
  draft: MeetingSettingsDraft,
  meeting: MeetingSettingsSource,
): boolean {
  return JSON.stringify(buildMeetingSettingsPayload(draft)) !== JSON.stringify(
    buildMeetingSettingsPayload(hydrateMeetingSettingsDraft(meeting)),
  )
}

export function validateMeetingSettingsDraft(
  draft: MeetingSettingsDraft,
  meeting: MeetingSettingsSource,
): MeetingSettingsErrors {
  const confirmedCourtroom = meeting.mode_id === 'courtroom' && meeting.courtroom?.status === 'confirmed'
  const legacyCaseTypeMissing = confirmedCourtroom && !meeting.case_type
  return {
    title: draft.title.trim() ? '' : '請輸入會議名稱。',
    goal: confirmedCourtroom && draft.goal !== (meeting.goal ?? '')
      ? '爭點已確認，AI 目標只能檢視；重新整理爭點後才可修改。'
      : draft.goal.trim() ? '' : '請輸入 AI 最終目標。',
    caseType: confirmedCourtroom && !legacyCaseTypeMissing && draft.caseType !== meeting.case_type
      ? '爭點已確認，案件類型只能檢視；重新整理爭點後才可修改。'
      : meeting.mode_id === 'courtroom' && !draft.caseType ? '請選擇民事或刑事。' : '',
  }
}

export function nextHistorySelection(
  previousMeetingId: string | null,
  nextMeetingId: string | null,
  selectedEpochId: string,
  activeEpochId: string,
): string {
  return previousMeetingId === nextMeetingId ? selectedEpochId : activeEpochId
}

export function materialImpactGuidance(modeId: string): string {
  return modeId === 'courtroom'
    ? '為避免新舊證據混用，目前已暫停 AI 與法官判斷。請到「流程操作」選擇重開目前爭點、重開全部審議或重新整理爭點。'
    : '為避免新舊資料混用，目前已暫停 AI。請到「流程操作」輸入原因並重開全部審議。'
}

/**
 * 是否有 AI 已發言（Human/System 以外的角色完成回應）。有 AI 發言後變更案卷
 * 會觸發 material_change_impact，AI 將暫停並需重開審議，因此需要先確認。
 */
export function hasAiOutput(events: Array<{ role: string; status?: string }> | undefined): boolean {
  return (events ?? []).some((event) => !['Human', 'System'].includes(event.role) && event.status === 'completed')
}

export type MaterialVocabulary = {
  panelTitle: string
  tabLabel: string
  itemPlural: string
  notePlural: string
  addItem: string
  addNote: string
  changedTitle: string
  loading: string
}

/**
 * 「證物／案卷」是法庭用語。其他模式（聊天室、接力、平行）附加的只是參考檔案，
 * 沿用法庭詞彙會讓使用者困惑，因此依模式切換，與 materialImpactGuidance 一致。
 */
export function materialVocabulary(modeId: string): MaterialVocabulary {
  if (modeId === 'courtroom') {
    return {
      panelTitle: '案卷與證據',
      tabLabel: '案卷',
      itemPlural: '證物',
      notePlural: '案件備註',
      addItem: '新增證物',
      addNote: '新增案件備註',
      changedTitle: '案卷已在 AI 發言後變更',
      loading: '正在載入案卷…',
    }
  }
  return {
    panelTitle: '附件與資料',
    tabLabel: '資料',
    itemPlural: '附件',
    notePlural: '備註',
    addItem: '新增附件',
    addNote: '新增備註',
    changedTitle: '附件已在 AI 發言後變更',
    loading: '正在載入附件…',
  }
}

/**
 * AI 已發言時，儲存或停用案卷前顯示的確認訊息。用語與 materialImpactGuidance
 * 一致：法庭用「證物／案卷」，其他模式用中性的「附件／資料」。
 */
export function materialImpactConfirmMessage(modeId: string): string {
  return modeId === 'courtroom'
    ? '此變更會納入 AI 可見的案卷與證物；儲存後 AI 會暫停並需重開審議，確定儲存？'
    : '此變更會納入 AI 可見的附件與資料；儲存後 AI 會暫停並需重開審議，確定儲存？'
}

const ANCHOR_DIGITS = '零一二三四五六七八九'

/**
 * 引用錨點與後端 `citation_anchor` 同源：法院用「證物」，其他模式（聊天室、接力、平行）
 * 用中性的「附件」，與 materialVocabulary 一致。
 */
export function draftEvidenceAnchor(index: number, modeId: string): string {
  const section = (value: number) => {
    let result = ''
    let pendingZero = false
    for (const [divisor, unit] of [
      [1000, '千'],
      [100, '百'],
      [10, '十'],
      [1, ''],
    ] as const) {
      const digit = Math.floor(value / divisor)
      value %= divisor
      if (digit) {
        if (pendingZero && result) result += ANCHOR_DIGITS[0]
        if (!(divisor === 10 && digit === 1 && !result)) result += ANCHOR_DIGITS[digit]
        result += unit
        pendingZero = false
      } else if (result && value) {
        pendingZero = true
      }
    }
    return result
  }
  const high = Math.floor(index / 10_000)
  const low = index % 10_000
  const numeral = high
    ? `${section(high)}萬${low && low < 1000 ? ANCHOR_DIGITS[0] : ''}${low ? section(low) : ''}`
    : section(low)
  const label = modeId === 'courtroom' ? '證物' : '附件'
  return `[${label}${numeral}]`
}

type WorkspaceParticipant = {
  role_id: string
  display_name?: string | null
  name?: string | null
  kind?: string | null
}

type WorkspaceEvent = {
  event_id: string
  meeting_id: string
  step_id: string
  base_step_id?: string
  role: string
  attempt: number
  status: string
  output_schema_id?: string
  round?: number
  content?: string
  created_at?: string
  error?: string
  failure_kind?: string
  retry_scheduled?: boolean
  issue_id?: string
  issue_phase?: 'charge' | 'defense' | 'rebuttal' | 'ruling'
  interaction_type?: string
  file_id?: string
  filename?: string
  size?: number
  mime_type?: string
  extension?: string
  removed?: boolean
  parsed_output?: {
    message?: string
    attachment_refs?: Array<{ source_ref: string; label: string; segment_refs: string[] }>
    summary?: string
    decision?: string
    arguments?: Array<{ title: string; detail: string }>
    findings?: Array<{ title: string; detail: string; evidence_refs?: string[] }>
    risks?: Array<{ title: string; detail: string; evidence_refs?: string[] }>
    recommendation?: string
    conditions?: string[]
    unresolved_questions?: string[]
  } | null
  raw_output?: string
  in_response_to_event_id?: string
}

type WorkspaceCourtroom = {
  status: string
  issues: Array<{
    id: string
    title: string
    position: number
    status: string
    ruling?: unknown
    failed_step_id?: string
    failed_phase?: string
    failed_phase_display?: string
    failure_kind?: string
  }>
  current_issue_id: string | null
  final_status: string
  available_actions: string[]
  case_type: 'civil' | 'criminal' | null
  requires_case_type: boolean
}

export type WorkspaceProjectionMeeting = {
  meeting_id: string
  mode_id: string
  activity_status: string
  participants: WorkspaceParticipant[]
  events?: WorkspaceEvent[]
  courtroom: WorkspaceCourtroom | null
}

export type WorkspaceProjectionMode = {
  id: string
  category: string
  roles: Array<{ id: string; name: string; kind?: string }>
  steps?: Array<{ role: string; label: string; template: string }>
  fanout?: { role: string; label: string }
  synthesis?: { role: string; label: string }
}

export type WorkspaceMessage = {
  id: string
  order: number
  event: WorkspaceEvent
  kind: 'human' | 'ai' | 'synthesizer' | 'failed' | 'system'
  roleId: string
  roleName: string
  content: string
  createdAt: string | null
  issueId: string | null
}

export type FanoutRoleState = {
  roleId: string
  name: string
  state: 'pending' | 'completed' | 'failed' | 'unknown'
}

export type WorkspaceFanoutRound = {
  id: string
  humanEventId: string | null
  expectedRoleIds: string[]
  members: WorkspaceMessage[]
  roleStates: FanoutRoleState[]
  respondedCount: number
  failedCount: number
  terminal: 'pending' | 'completed' | 'partial' | 'unknown'
  degraded: boolean
}

export type ConversationFeedItem =
  | { kind: 'message'; message: WorkspaceMessage }
  | { kind: 'fanout-round'; round: WorkspaceFanoutRound }

export type WorkspaceRole = {
  roleId: string
  name: string
  state: 'waiting' | 'thinking' | 'completed' | 'failed'
  latestMessageId: string | null
}

export type ConversationWorkspaceProjection = {
  family: 'conversation'
  meetingId: string
  messages: WorkspaceMessage[]
  feedItems: ConversationFeedItem[]
  fanoutRounds: WorkspaceFanoutRound[]
  roles: WorkspaceRole[]
  parallel: null | {
    completed: number
    total: number
    synthesis: 'waiting' | 'running' | 'blocked' | 'completed' | 'failed'
  }
  capabilities: {
    addNote: true
    openMaterials: true
    requestAll: true
    directedRoleIds: string[]
  }
}

export type CourtHearingIssueGroup = {
  issue: WorkspaceCourtroom['issues'][number]
  messages: WorkspaceMessage[]
  phases: Array<{
    phase: NonNullable<WorkspaceEvent['issue_phase']>
    messages: WorkspaceMessage[]
  }>
  otherMessages: WorkspaceMessage[]
}

export type CourtHearingWorkspaceProjection = {
  family: 'court-hearing'
  meetingId: string
  roles: WorkspaceRole[]
  issues: CourtHearingIssueGroup[]
  ungroupedMessages: WorkspaceMessage[]
  availableActions: string[]
  capabilities: {
    addNote: boolean
    openMaterials: true
    directedRoleIds: string[]
    formalActions: string[]
  }
}

export type MeetingWorkspaceProjection =
  | ConversationWorkspaceProjection
  | CourtHearingWorkspaceProjection

function participantName(
  participant: WorkspaceParticipant,
  mode: WorkspaceProjectionMode,
): string {
  return participant.display_name?.trim()
    || participant.name?.trim()
    || mode.roles.find((role) => role.id === participant.role_id)?.name
    || participant.role_id
}

function messageKind(event: WorkspaceEvent, mode: WorkspaceProjectionMode): WorkspaceMessage['kind'] {
  if (event.status === 'failed') return 'failed'
  if (event.role === 'Human') return 'human'
  if (event.role === 'System') return 'system'
  if (mode.synthesis && (
    event.role === mode.synthesis.role
    || event.step_id.startsWith('synthesis-')
    || event.base_step_id?.startsWith('synthesis-')
  )) return 'synthesizer'
  return 'ai'
}

const DECISION_DISPLAY: Record<string, string> = {
  approve: '核准',
  'approve-with-conditions': '有條件核准',
  reject: '否決',
  'insufficient-evidence': '證據不足',
}

function titledItems(
  items: Array<{ title: string; detail: string; evidence_refs?: string[] }> | undefined,
): string[] {
  return (items ?? []).map((item) => {
    const evidence = item.evidence_refs?.length ? `（${item.evidence_refs.join('、')}）` : ''
    return `${item.title}：${item.detail}${evidence}`
  })
}

function formatStructuredOutput(output: NonNullable<WorkspaceEvent['parsed_output']>): string {
  const sections: string[] = []
  const addSection = (label: string, lines: Array<string | undefined>) => {
    const content = lines.filter((line): line is string => Boolean(line?.trim()))
    if (content.length) sections.push([label, ...content].join('\n'))
  }
  addSection('摘要', [output.summary])
  addSection('裁決', [output.decision ? DECISION_DISPLAY[output.decision] ?? output.decision : undefined])
  addSection('判定事項', titledItems(output.findings))
  addSection('論點', titledItems(output.arguments))
  addSection('風險', titledItems(output.risks))
  addSection('建議處置', [output.recommendation])
  addSection('附帶條件', output.conditions ?? [])
  addSection('待釐清事項', output.unresolved_questions ?? [])
  return sections.join('\n\n')
}

function messageContent(event: WorkspaceEvent): string {
  if (event.output_schema_id === 'chat-message/v1' && event.parsed_output?.message?.trim()) {
    return event.parsed_output.message
  }
  if (event.content !== undefined) return event.content
  if (event.status === 'failed') return event.error ?? '本次回應失敗。'
  if (event.parsed_output) {
    const formatted = formatStructuredOutput(event.parsed_output)
    if (formatted) return formatted
  }
  return event.raw_output ?? event.error ?? ''
}

function projectFanoutRounds(
  meeting: WorkspaceProjectionMeeting,
  mode: WorkspaceProjectionMode,
  messages: WorkspaceMessage[],
  captures: FanoutCapture[],
): WorkspaceFanoutRound[] {
  if (mode.category !== 'chatroom') return []
  const humanEvents = new Map(
    (meeting.events ?? [])
      .filter((event) => event.role === 'Human' && event.step_id === 'human-message')
      .map((event) => [event.event_id, event]),
  )
  const grouped = new Map<string, WorkspaceMessage[]>()
  for (const message of messages) {
    const reference = message.event.in_response_to_event_id
    if (
      message.event.step_id.startsWith('chat-fanout-')
      && reference
      && humanEvents.has(reference)
    ) {
      const members = grouped.get(reference) ?? []
      members.push(message)
      grouped.set(reference, members)
    }
  }

  const captureFor = (humanEventId: string): FanoutCapture | undefined => {
    return captures.find((capture) => capture.humanEventId === humanEventId)
  }

  const roundFor = (humanEventId: string | null, members: WorkspaceMessage[], capture?: FanoutCapture): WorkspaceFanoutRound => {
    const observed = members.map((message) => message.roleId)
    const expectedRoleIds = capture && !capture.degraded
      ? [...capture.expectedRoleIds]
      : [...new Set(observed)]
    const names = new Map(
      meeting.participants.map((participant) => [participant.role_id, participantName(participant, mode)]),
    )
    const states: FanoutRoleState[] = expectedRoleIds.map((roleId) => {
      const member = members.find((candidate) => candidate.roleId === roleId)
      return {
        roleId,
        name: names.get(roleId) ?? roleId,
        state: member ? member.kind === 'failed' ? 'failed' : 'completed' : 'pending',
      }
    })
    const isSettled = meeting.activity_status !== 'running' && Boolean(humanEventId)
    if (isSettled) {
      for (const state of states) {
        if (state.state === 'pending') state.state = 'unknown'
      }
    }
    const failedCount = states.filter((state) => state.state === 'failed').length
    const respondedCount = states.filter((state) => state.state === 'completed').length
    const hasUnknown = states.some((state) => state.state === 'unknown')
    const terminal: WorkspaceFanoutRound['terminal'] = !isSettled
      ? 'pending'
      : hasUnknown
        ? 'unknown'
        : failedCount > 0
        ? 'partial'
        : 'completed'
    return {
      id: humanEventId ? `fanout-round-${humanEventId}` : capture?.id ?? 'fanout-round-pending',
      humanEventId,
      expectedRoleIds,
      members,
      roleStates: states,
      respondedCount,
      failedCount,
      terminal,
      degraded: Boolean(capture?.degraded) || !capture,
    }
  }

  const rounds = [...grouped.entries()].flatMap(([humanEventId, members]) => {
    const capture = captureFor(humanEventId)
    // A durable event reference alone is insufficient: only this-session capture
    // proves that the Human request was @all. Reloaded/history/multi-role events
    // therefore remain ordinary flat messages.
    return capture ? [roundFor(humanEventId, members, capture)] : []
  })
  for (const capture of captures) {
    if (capture.meetingId !== meeting.meeting_id) continue
    if (capture.humanEventId && grouped.has(capture.humanEventId)) continue
    rounds.push(roundFor(capture.humanEventId, [], capture))
  }
  return rounds
}

function projectMessages(
  meeting: WorkspaceProjectionMeeting,
  mode: WorkspaceProjectionMode,
): WorkspaceMessage[] {
  const names = new Map(
    meeting.participants.map((participant) => [participant.role_id, participantName(participant, mode)]),
  )
  return (meeting.events ?? [])
    .filter((event) => !(
      mode.category === 'chatroom'
      && event.status === 'failed'
      && event.retry_scheduled === true
    ))
    .map((event, order) => ({
      id: event.event_id,
      order,
      event,
      kind: messageKind(event, mode),
      roleId: event.role,
      roleName: event.role === 'Human'
        ? '主席'
        : event.role === 'System' ? '系統' : names.get(event.role) ?? event.role,
      content: messageContent(event),
      createdAt: event.created_at ?? null,
      issueId: event.issue_id ?? null,
    }))
}

function projectRoles(
  meeting: WorkspaceProjectionMeeting,
  mode: WorkspaceProjectionMode,
  messages: WorkspaceMessage[],
  thinkingRoleIds: string[],
  fanoutRounds: WorkspaceFanoutRound[] = [],
): WorkspaceRole[] {
  const queued = new Map<string, number>()
  thinkingRoleIds.forEach((roleId, index) => {
    if (!queued.has(roleId)) queued.set(roleId, index)
  })
  const parallel = parallelRoundState(meeting, mode)
  const fanoutStates = new Map<string, FanoutRoleState['state']>()
  for (const round of fanoutRounds) {
    for (const state of round.roleStates) fanoutStates.set(state.roleId, state.state)
  }
  return meeting.participants.map((participant) => {
    const latest = lastMessageForRole(messages, participant.role_id)
    let state: WorkspaceRole['state']
    if (mode.category === 'chatroom' && fanoutStates.has(participant.role_id)) {
      const fanoutState = fanoutStates.get(participant.role_id)
      state = fanoutState === 'pending' ? 'thinking'
        : fanoutState === 'failed' ? 'failed'
          : fanoutState === 'completed' ? 'completed' : 'waiting'
    } else if (mode.category !== 'parallel' && queued.has(participant.role_id)) {
      state = queued.get(participant.role_id) === 0 ? 'thinking' : 'waiting'
    } else if (parallel?.memberRoleIds.has(participant.role_id)) {
      const current = parallel.latestMembers.get(participant.role_id)
      state = queued.has(participant.role_id)
        ? 'thinking'
        : current?.status === 'completed'
          ? 'completed'
          : current?.status === 'failed'
            ? 'failed'
            : meeting.activity_status === 'running' ? 'thinking' : 'waiting'
    } else if (parallel && participant.role_id === mode.synthesis?.role) {
      state = parallel.latestSynthesis?.status === 'completed'
        ? 'completed'
        : parallel.latestSynthesis?.status === 'failed' && !queued.has(participant.role_id)
          ? 'failed'
          : meeting.activity_status === 'running' && parallel.completed === parallel.memberRoleIds.size
            ? 'thinking'
            : 'waiting'
    } else {
      state = latest?.kind === 'failed' ? 'failed' : latest ? 'completed' : 'waiting'
    }
    return {
      roleId: participant.role_id,
      name: participantName(participant, mode),
      state,
      latestMessageId: latest?.id ?? null,
    }
  })
}

function lastMessageForRole(
  messages: WorkspaceMessage[],
  roleId: string,
): WorkspaceMessage | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.roleId === roleId) return messages[index]
  }
  return undefined
}

export function seatIdToEventRoleId(seatId: string): string {
  return seatId === 'Chairman' ? 'Human' : seatId
}

function parallelMemberRoleIds(
  meeting: WorkspaceProjectionMeeting,
  mode: WorkspaceProjectionMode,
): Set<string> {
  if (mode.category !== 'parallel' || !mode.fanout) return new Set()
  return new Set(
    meeting.participants
      .filter((participant) => {
        const kind = participant.kind ?? mode.roles.find((role) => role.id === participant.role_id)?.kind
        return kind
          ? kind === 'member'
          : participant.role_id === mode.fanout?.role
            || participant.role_id.startsWith(`${mode.fanout?.role}-`)
      })
      .map((participant) => participant.role_id),
  )
}

function parallelRoundState(
  meeting: WorkspaceProjectionMeeting,
  mode: WorkspaceProjectionMode,
): null | {
  memberRoleIds: Set<string>
  latestMembers: Map<string, WorkspaceEvent>
  latestSynthesis: WorkspaceEvent | undefined
  completed: number
  hasFailedMember: boolean
} {
  if (mode.category !== 'parallel' || !mode.fanout) return null
  const memberRoleIds = parallelMemberRoleIds(meeting, mode)
  const events = meeting.events ?? []
  const memberEvents = events.filter((event) => memberRoleIds.has(event.role))
  const latestMemberRound = memberEvents.length
    ? Math.max(...memberEvents.map((event) => event.round ?? 1))
    : 1
  let latestCompletedSynthesisIndex = -1
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event && (
      event.step_id.startsWith('synthesis-') || event.base_step_id?.startsWith('synthesis-')
    ) && (event.round ?? 1) === latestMemberRound && event.status === 'completed') {
      latestCompletedSynthesisIndex = index
      break
    }
  }
  // A running snapshot can briefly contain the just-completed synthesis while the job
  // settles. Only a later chairman instruction identifies a genuinely new parallel round.
  const hasNewRoundInstruction = latestCompletedSynthesisIndex >= 0
    && events.slice(latestCompletedSynthesisIndex + 1).some((event) => event.role === 'Human')
  const round = meeting.activity_status === 'running' && hasNewRoundInstruction
    ? latestMemberRound + 1
    : latestMemberRound
  const latest = new Map<string, WorkspaceEvent>()
  for (const event of memberEvents) {
    if ((event.round ?? 1) !== round) continue
    const previous = latest.get(event.role)
    if (!previous || event.attempt >= previous.attempt) latest.set(event.role, event)
  }
  const synthesisEvents = events.filter((event) =>
    (event.step_id.startsWith('synthesis-') || event.base_step_id?.startsWith('synthesis-'))
    && (event.round ?? 1) === round,
  )
  const latestSynthesis = synthesisEvents.at(-1)
  return {
    memberRoleIds,
    latestMembers: latest,
    latestSynthesis,
    completed: [...latest.values()].filter((event) => event.status === 'completed').length,
    hasFailedMember: [...latest.values()].some((event) => event.status === 'failed'),
  }
}

function projectParallel(
  meeting: WorkspaceProjectionMeeting,
  mode: WorkspaceProjectionMode,
): ConversationWorkspaceProjection['parallel'] {
  const parallel = parallelRoundState(meeting, mode)
  if (!parallel) return null
  const synthesis = parallel.latestSynthesis?.status === 'completed'
    ? 'completed'
    : parallel.latestSynthesis?.status === 'failed'
      ? 'failed'
      : parallel.latestSynthesis
        ? 'running'
        : parallel.hasFailedMember
          ? 'blocked'
          : parallel.completed === parallel.memberRoleIds.size && parallel.memberRoleIds.size > 0 && meeting.activity_status === 'running'
            ? 'running'
            : 'waiting'
  return { completed: parallel.completed, total: parallel.memberRoleIds.size, synthesis }
}

export function projectMeetingWorkspace(input: {
  meeting: WorkspaceProjectionMeeting
  mode: WorkspaceProjectionMode
  thinkingRoleIds?: string[]
  fanoutCaptures?: FanoutCapture[]
}): MeetingWorkspaceProjection {
  const messages = projectMessages(input.meeting, input.mode)
  const fanoutRounds = projectFanoutRounds(
    input.meeting,
    input.mode,
    messages,
    (input.fanoutCaptures ?? []).filter((capture) => capture.meetingId === input.meeting.meeting_id),
  )
  const roles = projectRoles(
    input.meeting,
    input.mode,
    messages,
    input.thinkingRoleIds ?? [],
    fanoutRounds,
  )
  if (input.meeting.mode_id === 'courtroom' && input.meeting.courtroom) {
    const courtroom = input.meeting.courtroom
    const issueIds = new Set(courtroom.issues.map((issue) => issue.id))
    const availableActions = [...courtroom.available_actions]
    const issueGroup = (issue: WorkspaceCourtroom['issues'][number]): CourtHearingIssueGroup => {
      const issueMessages = messages.filter((message) => message.issueId === issue.id)
      const phaseOrder: Array<NonNullable<WorkspaceEvent['issue_phase']>> = []
      const byPhase = new Map<NonNullable<WorkspaceEvent['issue_phase']>, WorkspaceMessage[]>()
      for (const message of issueMessages) {
        const phase = message.event.issue_phase
        if (!phase) continue
        if (!byPhase.has(phase)) {
          phaseOrder.push(phase)
          byPhase.set(phase, [])
        }
        byPhase.get(phase)?.push(message)
      }
      return {
        issue,
        messages: issueMessages,
        phases: phaseOrder.map((phase) => ({ phase, messages: byPhase.get(phase) ?? [] })),
        otherMessages: issueMessages.filter((message) => !message.event.issue_phase),
      }
    }
    return {
      family: 'court-hearing',
      meetingId: input.meeting.meeting_id,
      roles,
      issues: courtroom.issues.map(issueGroup),
      ungroupedMessages: messages.filter((message) => !message.issueId || !issueIds.has(message.issueId)),
      availableActions,
      capabilities: {
        addNote: availableActions.includes('add-note'),
        openMaterials: true,
        directedRoleIds: availableActions.includes('directed-response')
          ? input.meeting.participants.map((participant) => participant.role_id)
          : [],
        formalActions: availableActions,
      },
    }
  }
  return {
    family: 'conversation',
    meetingId: input.meeting.meeting_id,
    messages,
    fanoutRounds,
    feedItems: buildConversationFeedItems(messages, fanoutRounds),
    roles,
    parallel: projectParallel(input.meeting, input.mode),
    capabilities: {
      addNote: true,
      openMaterials: true,
      requestAll: true,
      directedRoleIds: input.mode.category === 'relay'
        ? input.meeting.participants.map((participant) => participant.role_id)
        : [],
    },
  }
}

function buildConversationFeedItems(
  messages: WorkspaceMessage[],
  rounds: WorkspaceFanoutRound[],
): ConversationFeedItem[] {
  const roundByMemberId = new Map<string, WorkspaceFanoutRound>()
  for (const round of rounds) {
    for (const member of round.members) roundByMemberId.set(member.id, round)
  }
  const emittedRounds = new Set<string>()
  const items: ConversationFeedItem[] = []
  for (const message of messages) {
    const round = roundByMemberId.get(message.id)
    if (!round) {
      items.push({ kind: 'message', message })
      continue
    }
    if (!emittedRounds.has(round.id)) {
      emittedRounds.add(round.id)
      items.push({ kind: 'fanout-round', round })
    }
  }
  for (const round of rounds) {
    if (!emittedRounds.has(round.id)) items.push({ kind: 'fanout-round', round })
  }
  return items
}

export type WorkspaceRoleFilter = {
  meetingId: string
  roleId: string
}

export function nextWorkspaceRoleFilter(
  previous: WorkspaceRoleFilter | null,
  meetingId: string,
  roleId?: string,
): WorkspaceRoleFilter | null {
  if (!roleId) return null
  if (previous?.meetingId === meetingId && previous.roleId === roleId) return null
  return { meetingId, roleId }
}

/**
 * 附件事件（attachment-added）沒有文字內容，由 AttachmentBubble 呈現，
 * 不走一般文字氣泡。AI 對附件一無所知，因此它也不是 AI 發言。
 */
export function isAttachmentEvent(event: { step_id?: string }): boolean {
  return event.step_id === 'attachment-added'
}

export function formatAttachmentSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// Text uploads (chatroom) now produce BOTH an evidence entry and an
// attachment event, so counting `evidence + attachments_summary.count` would
// show N+1 for N data items. Count attachment events while excluding the text
// MIME types that were mirrored into evidence, then add active evidence. When
// `events` is absent (pure list projection — in practice `selectedMeeting`
// always carries events) fall back to `attachments_summary.count`; that branch
// is near-dead and kept only for type safety. Courtroom is unaffected because
// its .txt files never create an attachment event.
const TEXT_ATTACHMENT_MIMES = new Set(['text/plain', 'text/markdown'])

export function materialCountFor(meeting: {
  case_materials?: { evidence?: Array<{ status: string }> } | null
  case_files?: Array<unknown> | null
  attachments_summary?: { count: number } | null
  events?: Array<{ step_id?: string; mime_type?: string; removed?: boolean }> | null
} | null | undefined): number {
  if (!meeting) return 0
  const evidence = meeting.case_materials?.evidence?.filter((item) => item.status === 'active').length
    ?? meeting.case_files?.length
    ?? 0
  const attachmentCount = meeting.events
    ? meeting.events.filter(
        (event) =>
          event.step_id === 'attachment-added' &&
          !event.removed &&
          !TEXT_ATTACHMENT_MIMES.has(event.mime_type ?? ''),
      ).length
    : (meeting.attachments_summary?.count ?? 0)
  return evidence + attachmentCount
}

function allWorkspaceMessages(workspace: MeetingWorkspaceProjection): WorkspaceMessage[] {
  if (workspace.family === 'conversation') return workspace.messages
  return [
    ...workspace.ungroupedMessages,
    ...workspace.issues.flatMap((group) => group.messages),
  ].sort((left, right) => left.order - right.order)
}

export function latestWorkspaceMessageTarget(
  workspace: MeetingWorkspaceProjection,
  filter: WorkspaceRoleFilter | null,
): string | null {
  if (!filter || filter.meetingId !== workspace.meetingId) return null
  return lastMessageForRole(allWorkspaceMessages(workspace), seatIdToEventRoleId(filter.roleId))?.id ?? null
}

export type MessageClampPolicy = {
  collapsible: boolean
  collapsedByDefault: boolean
  lineClamp: 3
}

export function shouldShowChatroomComposer(modeCategory: string): boolean {
  return modeCategory === 'chatroom'
}

export function messageClampPolicy(content: string): MessageClampPolicy {
  const collapsible = content.length > 240 || content.split(/\r?\n/).length > 3
  return {
    collapsible,
    collapsedByDefault: collapsible,
    lineClamp: 3,
  }
}

// ── Model-assignment pure helpers ─────────────────────────────────────────────
// Extracted from useCouncil.updateSelectedModel so the core logic lives in a
// testable layer that unit tests can import directly (useCouncil.ts itself
// depends on import.meta.env via api.ts and is incompatible with Node --test).

export function isSameModelAssignment(
  selectedModels: Record<string, string>,
  role: string,
  modelId: string,
): boolean {
  return selectedModels[role] === modelId
}

export function applyOptimisticModelUpdate(
  selectedModels: Record<string, string>,
  role: string,
  modelId: string,
): Record<string, string> {
  return { ...selectedModels, [role]: modelId }
}

export function replaceServerParticipantModels(
  participants: Array<{ role_id: string; model_config_id: string | null }>,
): Record<string, string> {
  return Object.fromEntries(
    participants.map((participant) => [
      participant.role_id,
      participant.model_config_id ?? '',
    ]),
  )
}
