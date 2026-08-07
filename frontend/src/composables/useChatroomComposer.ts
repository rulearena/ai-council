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

export type TrackedChatroomToken = ChatMention | ChatSourceToken

function codePointLength(content: string): number {
  return Array.from(content).length
}

export function rebaseTrackedChatroomTokens<T extends TrackedChatroomToken>(
  previousContent: string,
  nextContent: string,
  tokens: T[],
): T[] {
  const previous = Array.from(previousContent)
  const next = Array.from(nextContent)
  let prefix = 0
  while (prefix < previous.length && prefix < next.length && previous[prefix] === next[prefix]) {
    prefix += 1
  }
  let suffix = 0
  while (
    suffix < previous.length - prefix
    && suffix < next.length - prefix
    && previous[previous.length - 1 - suffix] === next[next.length - 1 - suffix]
  ) {
    suffix += 1
  }

  const previousEditEnd = previous.length - suffix
  const nextEditEnd = next.length - suffix
  const delta = nextEditEnd - previousEditEnd
  return tokens.flatMap((token) => {
    if (previousEditEnd <= token.start) {
      return [{ ...token, start: token.start + delta, end: token.end + delta } as T]
    }
    if (prefix >= token.end) return [token]
    // Any overlap, including deletion/replacement of the chip itself, fails closed.
    return []
  })
}

function normalizedBoundaryMap(content: string): number[] {
  const codePoints = Array.from(content)
  return codePoints.map((_, index) => codePointLength(content.slice(0, index).normalize('NFC')))
    .concat(codePointLength(content.normalize('NFC')))
}

function normalizeTrackedToken<T extends TrackedChatroomToken>(
  content: string,
  token: T,
  boundaries: number[],
): T | null {
  const displayText = token.display_text.normalize('NFC')
  const start = boundaries[token.start]
  const end = boundaries[token.end]
  if (start === undefined || end === undefined || end <= start) return null
  const normalizedContent = content.normalize('NFC')
  if (normalizedContent.slice(start, end) !== displayText) return null
  return { ...token, display_text: displayText, start, end } as T
}

export function buildCanonicalChatroomPayload(input: {
  content: string
  mentionTokens?: ChatMention[]
  sourceTokens?: ChatSourceToken[]
}): RebasedChatroomTokens | { error: string } {
  const content = input.content.normalize('NFC')
  if (!input.content.trim()) return { error: 'Message cannot be blank' }
  const boundaries = normalizedBoundaryMap(input.content)
  const mentions = (input.mentionTokens ?? []).flatMap((token) => {
    const normalized = normalizeTrackedToken(input.content, token, boundaries)
    return normalized ? [normalized] : []
  })
  const sourceTokens = (input.sourceTokens ?? []).flatMap((token) => {
    const normalized = normalizeTrackedToken(input.content, token, boundaries)
    return normalized ? [normalized] : []
  })
  if (mentions.length !== (input.mentionTokens ?? []).length) {
    return { error: 'mention token span no longer matches content' }
  }
  if (sourceTokens.length !== (input.sourceTokens ?? []).length) {
    return { error: 'source token span no longer matches content' }
  }
  return {
    content,
    mentions,
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
