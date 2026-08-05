import type { MeetingParticipant, ModelConfig } from './api'
import { modelDisplayLabel } from './providers.ts'

export type AssignmentWarningRole = {
  roleId: string
  name: string
}

export function resolveAssignmentModelName(
  models: readonly ModelConfig[],
  modelId: string,
): string {
  const model = models.find((candidate) => candidate.id === modelId)
  return model ? modelDisplayLabel(model) : modelId
}

export function projectAssignmentWarnings({
  participants,
  roles,
  models,
}: {
  participants: readonly Pick<MeetingParticipant, 'role_id' | 'model_assignment_warning'>[]
  roles: readonly AssignmentWarningRole[]
  models: readonly ModelConfig[]
}): string[] {
  const roleNames = new Map(roles.map((role) => [role.roleId, role.name]))

  return participants
    .filter((participant) => participant.model_assignment_warning)
    .map((participant) => {
      const roleName = roleNames.get(participant.role_id) ?? participant.role_id
      const warning = participant.model_assignment_warning!
      if (warning.toLowerCase().includes('no models are configured')) {
        return `${roleName}：模型登錄表目前沒有可用模型。`
      }
      if (warning.startsWith('No saved model assignment')) {
        const defaultMatch = warning.match(/using default model '([^']+)'/)
        const fallbackName = defaultMatch
          ? resolveAssignmentModelName(models, defaultMatch[1])
          : ''
        return fallbackName
          ? `${roleName}：未指派模型，已自動使用「${fallbackName}」。`
          : `${roleName}：未指派模型。`
      }
      const originalMatch = warning.match(/(?:Assigned|Recovered) model '([^']+)'/)
      const defaultMatch = warning.match(/using default model '([^']+)'/)
      const originalName = originalMatch
        ? resolveAssignmentModelName(models, originalMatch[1])
        : originalMatch?.[1] ?? ''
      const fallbackName = defaultMatch
        ? resolveAssignmentModelName(models, defaultMatch[1])
        : ''
      if (originalName && fallbackName) {
        return `${roleName}：模型「${originalName}」已失效，目前使用「${fallbackName}」。`
      }
      return `${roleName}：${warning}`
    })
}
