import type { ChatMention, ChatSourceToken } from '../api'

export type ChatMessageBoundary = {
  sendChatMention: (
    meetingId: string,
    content: string,
    mentions: ChatMention[],
    sourceTokens: ChatSourceToken[],
    sourceRefs: string[],
    quotedEventId?: string,
  ) => Promise<unknown>
}

type RebasedChatroomTokens = {
  content: string
  mentions: ChatMention[]
  sourceTokens: ChatSourceToken[]
  sourceRefs: string[]
}

function codePointOffset(content: string, codeUnitOffset: number): number {
  return Array.from(content.slice(0, codeUnitOffset)).length
}

function occurrences(content: string, needle: string): number[] {
  const result: number[] = []
  if (!needle) return result
  let offset = 0
  while (offset <= content.length) {
    const found = content.indexOf(needle, offset)
    if (found < 0) break
    result.push(found)
    offset = found + needle.length
  }
  return result
}

function rebaseTokenSpans<T extends ChatMention | ChatSourceToken>(
  content: string,
  tokens: T[],
): { tokens?: T[]; error?: string } {
  const byDisplay = new Map<string, T[]>()
  for (const token of tokens) {
    const displayText = token.display_text.normalize('NFC')
    const group = byDisplay.get(displayText) ?? []
    group.push({ ...token, display_text: displayText } as T)
    byDisplay.set(displayText, group)
  }

  const assigned = new Map<string, number[]>()
  for (const [displayText, group] of byDisplay) {
    const matches = occurrences(content, displayText)
    if (matches.length !== group.length) {
      return { error: `chip text occurrence mismatch: ${displayText}` }
    }
    assigned.set(displayText, matches)
  }

  const used = new Map<string, number>()
  return {
    tokens: Array.from(tokens, (token) => {
      const displayText = token.display_text.normalize('NFC')
      const matchOffsets = assigned.get(displayText) ?? []
      const occurrenceIndex = used.get(displayText) ?? 0
      used.set(displayText, occurrenceIndex + 1)
      const startInCodeUnits = matchOffsets[occurrenceIndex]
      const endInCodeUnits = startInCodeUnits + displayText.length
      return {
        ...token,
        display_text: displayText,
        start: codePointOffset(content, startInCodeUnits),
        end: codePointOffset(content, endInCodeUnits),
      } as T
    }),
  }
}

export function buildCanonicalChatroomPayload(input: {
  content: string
  mentionTokens?: ChatMention[]
  sourceTokens?: ChatSourceToken[]
}): RebasedChatroomTokens | { error: string } {
  const content = input.content.normalize('NFC')
  if (!input.content.trim()) return { error: 'Message cannot be blank' }
  const mentionResult = rebaseTokenSpans(content, input.mentionTokens ?? [])
  if (mentionResult.error) return { error: mentionResult.error }
  const sourceResult = rebaseTokenSpans(content, input.sourceTokens ?? [])
  if (sourceResult.error) return { error: sourceResult.error }
  const sourceTokens = sourceResult.tokens ?? []
  return {
    content,
    mentions: mentionResult.tokens ?? [],
    sourceTokens,
    sourceRefs: [...new Set(sourceTokens.map((token) => token.source_ref))],
  }
}

export async function parseAndSendChatMessage(input: {
  content: string
  meetingId: string
  quotedEventId: string | null
  mentionTokens?: ChatMention[]
  sourceTokens?: ChatSourceToken[]
  boundary: ChatMessageBoundary
}): Promise<{ ok: boolean; error?: string }> {
  const payload = buildCanonicalChatroomPayload(input)
  if ('error' in payload) return { ok: false, error: payload.error }

  try {
    await input.boundary.sendChatMention(
      input.meetingId,
      payload.content,
      payload.mentions,
      payload.sourceTokens,
      payload.sourceRefs,
      input.quotedEventId ?? undefined,
    )
    return { ok: true }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}
