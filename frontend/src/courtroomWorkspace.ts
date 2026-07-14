import type { CourtroomIssueProjection } from './api'

export type CourtroomDraftIssue = { id?: string; title: string }
export type CourtroomDraft = { revision: number; issues: CourtroomDraftIssue[] }

export function nextCourtroomDraft(
  drafts: Record<string, CourtroomDraft>,
  projection: { meetingId: string; revision: number; issues: CourtroomIssueProjection[] },
): CourtroomDraft {
  const existing = drafts[projection.meetingId]
  if (existing && existing.revision === projection.revision) return existing
  return {
    revision: projection.revision,
    issues: projection.issues.map(({ id, title }) => ({ id, title })),
  }
}

const ISSUE_STATUS_LABELS: Record<string, string> = {
  pending: '待審',
  'arguments-in-progress': '攻防中',
  'awaiting-ruling': '待裁定',
  ruled: '已裁定',
}

const OUTCOME_LABELS: Record<string, string> = {
  'proponent-wins': '主張方勝',
  'respondent-wins': '答辯方勝',
  'partially-upheld': '部分成立',
  'insufficient-evidence': '證據不足／無法判定',
}

export function courtroomIssueStatusLabel(status: string): string {
  return ISSUE_STATUS_LABELS[status] ?? status
}

export function courtroomOutcomeLabel(outcome: string): string {
  return OUTCOME_LABELS[outcome] ?? outcome
}
