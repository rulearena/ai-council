export type FanoutCapture = {
  id: string
  meetingId: string
  instruction: string
  preSendEventIds: string[]
  capturedAt: number
  expectedRoleIds: string[]
  humanEventId: string | null
  degraded: boolean
}

export type FanoutCorrelationEvent = {
  event_id: string
  meeting_id: string
  step_id: string
  role: string
  content?: string
}

export function createFanoutCapture(input: {
  meetingId: string
  instruction: string
  preSendEventIds: string[]
  expectedRoleIds: string[]
  capturedAt?: number
  id?: string
}): FanoutCapture {
  return {
    id: input.id ?? `fanout-capture-${input.meetingId}-${input.capturedAt ?? Date.now()}`,
    meetingId: input.meetingId,
    instruction: input.instruction,
    preSendEventIds: [...input.preSendEventIds],
    capturedAt: input.capturedAt ?? Date.now(),
    expectedRoleIds: [...new Set(input.expectedRoleIds.filter(Boolean))],
    humanEventId: null,
    degraded: false,
  }
}

export function isResolvableFanoutResponse(event: {
  step_id: string
  in_response_to_event_id?: string
}, humanEventIds: ReadonlySet<string>): boolean {
  return event.step_id.startsWith('chat-fanout-')
    && Boolean(event.in_response_to_event_id)
    && humanEventIds.has(event.in_response_to_event_id!)
}

export function bindOldestMatchingCapture(
  captures: FanoutCapture[],
  event: FanoutCorrelationEvent,
): FanoutCapture[] {
  if (event.role !== 'Human' || event.step_id !== 'human-message') return captures
  const next = captures.map((capture) => ({
    ...capture,
    preSendEventIds: [...capture.preSendEventIds],
    expectedRoleIds: [...capture.expectedRoleIds],
  }))
  const candidate = next.find((capture) =>
    capture.meetingId === event.meeting_id
      && capture.humanEventId === null
      && !capture.preSendEventIds.includes(event.event_id)
      && capture.instruction === event.content,
  )
  if (candidate) candidate.humanEventId = event.event_id
  return next
}

export function removeFanoutCapture(captures: FanoutCapture[], captureId: string): FanoutCapture[] {
  return captures.filter((capture) => capture.id !== captureId)
}

export function degradeFanoutCaptures(captures: FanoutCapture[], meetingId: string): FanoutCapture[] {
  return captures
    .filter((capture) => capture.meetingId !== meetingId)
    .concat(captures
      .filter((capture) => capture.meetingId === meetingId)
      .map((capture) => ({
        ...capture,
        preSendEventIds: [...capture.preSendEventIds],
        expectedRoleIds: [...capture.expectedRoleIds],
        humanEventId: null,
        degraded: true,
      })))
}
