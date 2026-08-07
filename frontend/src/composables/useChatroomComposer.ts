import type { ChatMention, ChatSourceToken } from '../api'
import type { ChairmanParticipant } from '../chairmanActions'

export type ChatMessageBoundary = {
  sendChatMessage: (meetingId: string, content: string, quotedEventId?: string) => Promise<unknown>
  sendChatMention: (
    meetingId: string,
    content: string,
    mentions: ChatMention[],
    sourceTokens?: ChatSourceToken[],
    sourceRefs?: string[],
    quotedEventId?: string,
  ) => Promise<unknown>
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
  mentionTokens?: ChatMention[]
  sourceTokens?: ChatSourceToken[]
  boundary: ChatMessageBoundary
}): Promise<{ ok: boolean; error?: string }> {
  const trimmed = input.content.trim()
  if (!trimmed) return { ok: false }

  try {
    // Keep the pure helper's historical seam usable for non-UI callers that do not
    // provide chip metadata. The actual chatroom composer always supplies the token
    // array, so its plain text path still goes through the Host-aware structured API.
    if (input.mentionTokens === undefined) {
      const legacyMentions = extractMentions(trimmed, input.participants)
      if (legacyMentions.length > 0) {
        await (input.boundary.sendChatMention as unknown as (
          meetingId: string, content: string, mentions: string[], quotedEventId?: string,
        ) => Promise<unknown>)(input.meetingId, trimmed, legacyMentions, input.quotedEventId ?? undefined)
      } else {
        await input.boundary.sendChatMessage(input.meetingId, trimmed, input.quotedEventId ?? undefined)
      }
      return { ok: true }
    }
    const mentions = input.mentionTokens ?? []
    const sourceTokens = input.sourceTokens ?? []
    const sourceRefs = [...new Set(sourceTokens.map((token) => token.source_ref))]
    await input.boundary.sendChatMention(
      input.meetingId,
      trimmed,
      mentions,
      sourceTokens,
      sourceRefs,
      input.quotedEventId ?? undefined,
    )
    return { ok: true }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}
