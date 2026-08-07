import type { ChatMention } from './api'

/** Public chatroom routing seam shared by the store and pending-seat projection. */
export function chatroomQueuedRoleIds(
  mentions: ChatMention[],
  projectedParticipantRoleIds: string[],
): string[] {
  const roleIds = mentions.map((mention) => mention.role_id)
  if (roleIds.includes('all')) {
    const projected = [...new Set(projectedParticipantRoleIds)]
    return projected.includes('host') ? projected : ['host', ...projected]
  }
  const explicit = [...new Set(roleIds)]
  return explicit.length > 0 ? explicit : ['host']
}

/** Reconcile an optimistic queue with the server-authoritative routing target set. */
export function reconcileChatroomAcceptedTargets(
  pendingRoleIds: string[],
  queuedRoleIds: string[],
  targetRoleIds: string[],
): string[] {
  const queued = new Set(queuedRoleIds)
  const accepted = new Set(targetRoleIds)
  return pendingRoleIds.filter((roleId) => !queued.has(roleId) || accepted.has(roleId))
}
