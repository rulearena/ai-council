export type ChairmanParticipant = {
  role_id: string
  display_name?: string | null
  name?: string | null
}

export type ChairmanActionOption = { value: string; label: string }

export type CourtroomIssueProjection = {
  id: string
  title: string
  status: string
}

export type CourtroomProjection = {
  status?: string
  available_actions: string[]
  current_issue_id: string | null
  issues: CourtroomIssueProjection[]
}

type WorkflowEvent = {
  role: string
  step_id: string
  base_step_id?: string
  round?: number
  status: string
}

type WorkflowStep = { role: string; label: string; template: string }

export type PrimaryAction = {
  kind: 'start-round' | 'courtroom-arguments' | 'courtroom-ruling' | 'courtroom-final' | 'unavailable'
  issueId?: string
  label: string
  disabled: boolean
}

function participantName(participants: ChairmanParticipant[], roleId: string): string {
  const participant = participants.find((candidate) => candidate.role_id === roleId)
  return participant?.display_name || participant?.name || roleId
}

function pendingCourtroomIssue(courtroom: CourtroomProjection): CourtroomIssueProjection | undefined {
  if (courtroom.current_issue_id) {
    return courtroom.issues.find((issue) => issue.id === courtroom.current_issue_id)
  }
  return courtroom.issues.find((issue) => issue.status === 'pending')
}

export function projectCourtroomPrimaryAction(
  courtroom: CourtroomProjection,
): PrimaryAction {
  const actions = new Set(courtroom.available_actions)
  const issue = pendingCourtroomIssue(courtroom)
  if (actions.has('start-issue') && issue) {
    return {
      kind: 'courtroom-arguments',
      issueId: issue.id,
      label: `開始爭點攻防：${issue.title}（下一位是檢察官）`,
      disabled: false,
    }
  }
  if (actions.has('submit-ruling') && issue) {
    return {
      kind: 'courtroom-ruling',
      issueId: issue.id,
      label: `送交爭點裁定：${issue.title}（下一位是法官）`,
      disabled: false,
    }
  }
  if (actions.has('final-verdict')) {
    return {
      kind: 'courtroom-final',
      label: '請法官作成最終判決',
      disabled: false,
    }
  }
  return {
    kind: 'unavailable',
    label: courtroom.status === 'confirmed' ? '請先完成目前爭點的必要步驟' : '請先建立並確認爭點',
    disabled: true,
  }
}

export function chairmanActionOptions(input: {
  modeId: string
  modeCategory: string
  participants: ChairmanParticipant[]
  courtroom: CourtroomProjection | null
  nextActionLabel?: string
  failedRole?: string | null
}): ChairmanActionOption[] {
  const options: ChairmanActionOption[] = [
    { value: 'note', label: '記錄補充（不會呼叫 AI）' },
  ]
  if (input.failedRole) return options
  const courtroomActions = new Set(input.courtroom?.available_actions ?? [])
  const canAskAll = input.modeId !== 'courtroom' || projectCourtroomPrimaryAction(input.courtroom!).disabled === false
  const canDirect = input.modeCategory === 'relay' && (
    input.modeId !== 'courtroom' || courtroomActions.has('directed-response')
  )
  if (canAskAll) {
    const courtroomPrimary = input.modeId === 'courtroom'
      ? projectCourtroomPrimaryAction(input.courtroom!)
      : null
    const courtroomIssue = input.courtroom ? pendingCourtroomIssue(input.courtroom) : null
    const nextLabel = courtroomPrimary?.kind === 'courtroom-arguments' && courtroomIssue
      ? `開始爭點「${courtroomIssue.title}」`
      : (courtroomPrimary?.label ?? input.nextActionLabel)?.replace(/（下一位.*$/, '')
    const suffix = nextLabel ? `（下一步：${nextLabel}）` : ''
    options.push({ value: 'all', label: `請全體回應${suffix}` })
  }
  if (canDirect) {
    options.push(...input.participants.map((participant) => ({
      value: `role:${participant.role_id}`,
      label: `請${participantName(input.participants, participant.role_id)}回答`,
    })))
  }
  return options
}

export function chairmanActionBlockReason(
  action: string,
  failedRole: string | null,
  participants: ChairmanParticipant[],
): string | null {
  if (action === 'note' || !failedRole) return null
  return `${participantName(participants, failedRole)}的回應失敗，請先重試失敗步驟，再請 AI 回應。`
}

export function chairmanActionPresentation(
  action: string,
  participants: ChairmanParticipant[],
): { placeholder: string; submitLabel: string; successMessage: string } {
  if (action === 'note') {
    return {
      placeholder: '輸入要加入會議紀錄的補充；不會呼叫 AI…',
      submitLabel: '記錄主席補充',
      successMessage: '已加入會議紀錄，未呼叫 AI。',
    }
  }
  if (action === 'all') {
    return {
      placeholder: '輸入要請全體回應的問題或補充…',
      submitLabel: '請全體回應',
      successMessage: '已記錄主席發言，並啟動畫面所示的下一步。',
    }
  }
  const roleId = action.startsWith('role:') ? action.slice('role:'.length) : ''
  const roleName = participantName(participants, roleId)
  return {
    placeholder: `輸入要請${roleName}回答的問題或指示…`,
    submitLabel: `請${roleName}回答`,
    successMessage: `已請${roleName}針對這項指示回答。`,
  }
}

export type ChairmanActionBoundary = {
  appendNote: (content: string) => Promise<boolean>
  requestAll: () => Promise<boolean>
  requestRole: (roleId: string, instruction: string) => Promise<boolean>
}

export async function executeChairmanAction(
  action: string,
  content: string,
  boundary: ChairmanActionBoundary,
): Promise<boolean> {
  if (action === 'note') return boundary.appendNote(content)
  if (action === 'all') {
    if (!await boundary.appendNote(content)) return false
    return boundary.requestAll()
  }
  if (action.startsWith('role:')) {
    return boundary.requestRole(action.slice('role:'.length), content)
  }
  return false
}

export async function runWithPendingRoles(
  pendingRoles: string[],
  queuedRoles: string[],
  action: () => Promise<boolean>,
): Promise<boolean> {
  const previous = [...pendingRoles]
  pendingRoles.push(...queuedRoles)
  try {
    const succeeded = await action()
    if (!succeeded) pendingRoles.splice(0, pendingRoles.length, ...previous)
    return succeeded
  } catch (error) {
    pendingRoles.splice(0, pendingRoles.length, ...previous)
    throw error
  }
}

export function projectPrimaryAction(input: {
  modeId: string
  steps: WorkflowStep[]
  participants: ChairmanParticipant[]
  events: WorkflowEvent[]
  courtroom: CourtroomProjection | null
}): PrimaryAction {
  if (input.modeId === 'courtroom' && input.courtroom) {
    return projectCourtroomPrimaryAction(input.courtroom)
  }
  if (!input.steps.length) {
    const hasAiOutput = input.events.some((event) => !['Human', 'System'].includes(event.role))
    return {
      kind: 'start-round',
      label: hasAiOutput ? '開始新回合：請全體成員回應' : '開始審議：請全體成員回應',
      disabled: false,
    }
  }
  const stepIds = input.steps.map((step) => step.template.replaceAll('_', '-'))
  const aiEvents = input.events.filter((event) => stepIds.includes(event.base_step_id ?? event.step_id))
  const latestRound = aiEvents.length ? Math.max(...aiEvents.map((event) => event.round ?? 1)) : 1
  const currentRound = aiEvents.filter((event) => (event.round ?? 1) === latestRound)
  const nextIndex = stepIds.findIndex((stepId) => !currentRound.some(
    (event) => (event.base_step_id ?? event.step_id) === stepId && event.status === 'completed',
  ))
  const isFresh = aiEvents.length === 0
  const index = nextIndex < 0 ? 0 : nextIndex
  const nextRole = participantName(input.participants, input.steps[index].role)
  return {
    kind: 'start-round',
    label: nextIndex < 0
      ? `開始新回合：下一位是${nextRole}`
      : isFresh
        ? `開始審議：下一位是${nextRole}`
        : `繼續本回合：下一位是${nextRole}`,
    disabled: false,
  }
}

export function meetingEditPolicy(input: {
  modeId: string
  activityStatus: string
  courtroomStatus: string | null
  hasAiOutput: boolean
}): { canEdit: boolean; goalReadonly: boolean; confirmGoalChange: boolean } {
  const goalReadonly = input.modeId === 'courtroom' && input.courtroomStatus === 'confirmed'
  return {
    canEdit: input.activityStatus !== 'running',
    goalReadonly,
    confirmGoalChange: input.hasAiOutput && !goalReadonly,
  }
}
