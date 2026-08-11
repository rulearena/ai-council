import type { ChatMention, ChatroomAcceptedResponse, ChatSourceToken } from '../api'

export type ChatMessageBoundary = {
  sendChatMention: (
    meetingId: string,
    content: string,
    mentions: ChatMention[],
    sourceTokens: ChatSourceToken[],
    sourceRefs: string[],
    quotedEventId?: string,
  ) => Promise<ChatroomAcceptedResponse | null>
}

type RebasedChatroomTokens = {
  content: string
  mentions: ChatMention[]
  sourceTokens: ChatSourceToken[]
  sourceRefs: string[]
}

export type TrackedChatroomToken = ChatMention | ChatSourceToken

const XID_CONTINUE = /[\p{L}\p{N}\p{M}]/u

function isXidContinue(char: string): boolean {
  return char === '_' || XID_CONTINUE.test(char)
}

function verifiedTrackedTokens(
  codePoints: string[],
  tokens: TrackedChatroomToken[],
): TrackedChatroomToken[] {
  return tokens.filter((token) => (
    token.start >= 0
    && token.end > token.start
    && token.end <= codePoints.length
    && codePoints.slice(token.start, token.end).join('') === token.display_text
  ))
}

/**
 * Finds role-like @ text that is not covered by a verified structured chip.
 *
 * This intentionally mirrors the backend's fail-closed scanner. It is only a
 * preflight diagnostic: the backend remains authoritative and raw # stays
 * ordinary text. Code-point offsets match the API contract rather than the
 * textarea's UTF-16 selection offsets.
 */
export function findUncoveredRoleLikeSpans(
  content: string,
  tokens: TrackedChatroomToken[] = [],
): Array<{ displayText: string; start: number; end: number }> {
  const codePoints = Array.from(content)
  const covered = verifiedTrackedTokens(codePoints, tokens)
    .map((token) => [token.start, token.end] as const)
  const result: Array<{ displayText: string; start: number; end: number }> = []
  let index = 0
  while (index < codePoints.length) {
    if (codePoints[index] !== '@' || covered.some(([start, end]) => start <= index && index < end)) {
      index += 1
      continue
    }
    const previous = codePoints[index - 1] ?? ''
    if (previous && (isXidContinue(previous) || '@.+-'.includes(previous))) {
      index += 1
      continue
    }
    let end = index + 1
    while (end < codePoints.length && isXidContinue(codePoints[end]) && end - index <= 64) end += 1
    if (end === index + 1) {
      index += 1
      continue
    }
    const following = codePoints[end] ?? ''
    if (following === '.' || (following && (isXidContinue(following) || following === '-'))) {
      index = end
      continue
    }
    result.push({ displayText: codePoints.slice(index, end).join(''), start: index, end })
    index = end
  }
  return result
}

export type UncoveredRoleLikeSpan = {
  displayText: string
  start: number
  end: number
}

/**
 * Finds the first uncovered role-like span that the composer can explain before
 * sending. Raw hashtags are always ordinary message text; only a selected source
 * chip can authorize source content. Structured spans win coverage, while a
 * selected @all preserves the backend's ignored-invalid-mention warning path.
 */
export function findFirstUncoveredRoleLikeSpan(
  content: string,
  tokens: TrackedChatroomToken[] = [],
): UncoveredRoleLikeSpan | null {
  const codePoints = Array.from(content)
  const verifiedTokens = verifiedTrackedTokens(codePoints, tokens)
  const allSelected = verifiedTokens.some((token) => 'role_id' in token && token.role_id === 'all')
  if (allSelected) return null
  return findUncoveredRoleLikeSpans(content, verifiedTokens)[0] ?? null
}

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
  return codePoints.map((_, index) => codePointLength(
    codePoints.slice(0, index).join('').normalize('NFC'),
  ))
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
  if (Array.from(normalizedContent).slice(start, end).join('') !== displayText) return null
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

export type ChatroomSendResult =
  | { ok: true; response: ChatroomAcceptedResponse }
  | { ok: false; error: string }

export async function parseAndSendChatMessage(input: {
  content: string
  meetingId: string
  quotedEventId: string | null
  mentionTokens?: ChatMention[]
  sourceTokens?: ChatSourceToken[]
  boundary: ChatMessageBoundary
}): Promise<ChatroomSendResult> {
  const payload = buildCanonicalChatroomPayload(input)
  if ('error' in payload) return { ok: false, error: payload.error }

  try {
    const response = await input.boundary.sendChatMention(
      input.meetingId,
      payload.content,
      payload.mentions,
      payload.sourceTokens,
      payload.sourceRefs,
      input.quotedEventId ?? undefined,
    )
    if (!response) return { ok: false, error: 'Chatroom request was rejected' }
    return { ok: true, response }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}
