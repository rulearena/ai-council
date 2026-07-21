import type { ChatMention } from '../api'
import type { ChairmanParticipant } from '../chairmanActions'

export type ChatMessageBoundary = {
  sendChatMessage: (meetingId: string, content: string, quotedEventId?: string) => Promise<unknown>
  sendChatMention: (meetingId: string, content: string, mentions: ChatMention[], quotedEventId?: string) => Promise<unknown>
}

const MENTION_RE = /(?:^|\s)@(all|\w+)/g

export function extractMentions(
  content: string,
  participants: ChairmanParticipant[],
): string[] {
  const validRoleIds = new Set(participants.map((p) => p.role_id))
  const seen = new Set<string>()
  const mentions: string[] = []
  let match: RegExpExecArray | null

  while ((match = MENTION_RE.exec(content)) !== null) {
    const token = match[1]
    if (seen.has(token)) continue
    seen.add(token)

    if (token === 'all') {
      mentions.push('all')
    } else if (validRoleIds.has(token)) {
      mentions.push(token)
    }
  }

  return mentions
}

export async function parseAndSendChatMessage(input: {
  content: string
  meetingId: string
  participants: ChairmanParticipant[]
  quotedEventId: string | null
  boundary: ChatMessageBoundary
}): Promise<{ ok: boolean; error?: string }> {
  const trimmed = input.content.trim()
  if (!trimmed) return { ok: false }

  try {
    const mentions = extractMentions(trimmed, input.participants)
    if (mentions.length > 0) {
      await input.boundary.sendChatMention(
        input.meetingId,
        trimmed,
        mentions,
        input.quotedEventId ?? undefined,
      )
    } else {
      await input.boundary.sendChatMessage(
        input.meetingId,
        trimmed,
        input.quotedEventId ?? undefined,
      )
    }
    return { ok: true }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}
