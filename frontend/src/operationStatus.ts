import { projectCourtroomWorkflowStatus, type CourtroomProjection } from './chairmanActions.ts'
import { statusDisplayLabel } from './presentation.ts'

const WORKFLOW_ACTIVITY_STATUSES = new Set(['idle', 'waiting', 'completed', 'failed'])

export function projectOperationStatusText(
  activityStatus: string,
  courtroom: CourtroomProjection | null,
  terminalStatus: 'closed' | 'cancelled' | null = null,
): string {
  if (terminalStatus) return statusDisplayLabel(terminalStatus)
  if (courtroom && WORKFLOW_ACTIVITY_STATUSES.has(activityStatus)) {
    return projectCourtroomWorkflowStatus(courtroom)
  }
  return statusDisplayLabel(activityStatus)
}
