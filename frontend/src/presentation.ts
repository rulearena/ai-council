export type PresentationMode = {
  id: string
  roles: Array<{ id: string; name: string }>
  steps?: Array<{ role: string; label: string; template: string }>
  fanout?: { role: string; label: string }
  synthesis?: { role: string; label: string }
}

export type PresentationParticipant = {
  role_id?: string
  id?: string
  display_name?: string | null
  name?: string | null
}

export type PresentationEvent = {
  role: string
  step_id: string
  base_step_id?: string
  interaction_type?:
    | 'directed-role-instruction'
    | 'directed-role-response'
    | 'role-sequence-response'
    | 'courtroom-issue-draft'
    | 'courtroom-issue-phase'
    | 'courtroom-final-verdict'
    | 'courtroom-operation-reservation'
    | 'meeting-goal-changed'
  target_role_id?: string
  issue_phase?: 'charge' | 'defense' | 'rebuttal' | 'ruling'
  case_type?: 'civil' | 'criminal'
  role_display?: string
  phase_display?: string
  status?: string
}

export const OUTPUT_LABELS = {
  roleOutputs: '角色回應',
  summary: '摘要',
  decision: '裁決',
  findings: '判定事項',
  arguments: '論點',
  risks: '風險',
  recommendation: '建議處置',
  conditions: '附帶條件',
  unresolvedQuestions: '待釐清事項',
} as const

const DECISION_LABELS: Record<string, string> = {
  approve: '核准',
  'approve-with-conditions': '有條件核准',
  reject: '否決',
  'insufficient-evidence': '證據不足',
}

export function roleDisplayName(
  mode: PresentationMode,
  participants: PresentationParticipant[],
  roleId: string,
): string {
  if (roleId === 'Human') return '主席'
  if (roleId === 'System') return '系統'
  const participant = participants.find(
    (candidate) => (candidate.role_id ?? candidate.id) === roleId,
  )
  const participantName = participant?.display_name?.trim() || participant?.name?.trim()
  if (participantName) return participantName
  return mode.roles.find((role) => role.id === roleId)?.name ?? roleId
}

export function interactionDisplayLabel(
  mode: PresentationMode,
  participants: PresentationParticipant[],
  event: PresentationEvent,
): string | null {
  const roleName = event.role_display || roleDisplayName(mode, participants, event.role)
  if (event.interaction_type === 'directed-role-instruction' && event.target_role_id) {
    return `主席追問${roleDisplayName(mode, participants, event.target_role_id)}`
  }
  if (event.interaction_type === 'directed-role-response') return `${roleName}回應主席追問`
  if (event.interaction_type === 'role-sequence-response') return `${roleName}依序回應`
  if (event.interaction_type === 'meeting-goal-changed') return '主席修改會議目標'
  if (event.interaction_type === 'courtroom-issue-draft') return '法官提出爭點草稿'
  if (event.interaction_type === 'courtroom-final-verdict') return '法官作成最終判決'
  if (event.interaction_type === 'courtroom-issue-phase') {
    return ({
      charge: '檢察官提出爭點主張',
      defense: '辯護律師針對爭點答辯',
      rebuttal: '檢察官針對爭點反駁',
      ruling: '法官作成爭點裁定',
    } as Record<string, string>)[event.issue_phase ?? ''] ?? '爭點審理'
  }
  return null
}

export function stepDisplayLabel(
  mode: PresentationMode,
  participants: PresentationParticipant[],
  event: PresentationEvent,
): string {
  if (event.phase_display) return event.phase_display
  const interactionLabel = interactionDisplayLabel(mode, participants, event)
  if (interactionLabel) return interactionLabel
  if (event.role === 'Human') return event.step_id === 'human-correction' ? '主席訂正' : '主席發言'
  if (event.role === 'System' && event.step_id === 'meeting') {
    return {
      closed: '會議結案',
      cancelled: '會議取消',
      reopened: '重新開啟會議',
    }[event.status ?? ''] ?? '會議狀態更新'
  }

  const baseStepId = event.base_step_id ?? event.step_id.replace(/^round-\d+-/, '')
  const relayStep = mode.steps?.find(
    (step) => step.template.replaceAll('_', '-') === baseStepId,
  )
  if (relayStep) return relayStep.label

  if (mode.synthesis && event.role === mode.synthesis.role) return mode.synthesis.label
  if (mode.fanout && baseStepId.startsWith('member-')) {
    return `${roleDisplayName(mode, participants, event.role)}發想`
  }
  return roleDisplayName(mode, participants, event.role)
}

export function decisionDisplayLabel(decision: string): string {
  return DECISION_LABELS[decision] ?? decision
}

const STATUS_LABELS: Record<string, string> = {
  open: '進行中',
  closed: '已結案',
  cancelled: '已取消',
  idle: '尚未開始',
  running: '執行中',
  waiting: '等待中',
  completed: '已完成',
  failed: '失敗',
  reopened: '已重新開啟',
  unknown: '未知',
  available: '可用',
  unavailable: '不可用',
}

export function statusDisplayLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}
